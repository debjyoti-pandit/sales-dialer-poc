"""Call queue service for managing queued calls"""
import asyncio
from datetime import datetime
from typing import Optional
from app.storage import call_queues, campaigns, detection_results, agents
from app.services.twilio_service import twilio_service
from app.websocket.manager import broadcast_to_agent
from app.logger import logger


class CallQueueService:
    """Service for managing call queues"""

    def __init__(self):
        # call_sid -> asyncio.Task
        self._amd_timers: dict[str, asyncio.Task] = {}

    def cancel_amd_timer(self, call_sid: str) -> None:
        """Cancel any AMD gating timer for a call."""
        if not call_sid:
            return
        prev = self._amd_timers.pop(call_sid, None)
        if prev:
            prev.cancel()
    
    def add_to_queue(self, agent_name: str, call_sid: str, phone: str):
        """Add a call to the agent's queue"""
        if agent_name not in call_queues:
            call_queues[agent_name] = []

        call_queues[agent_name].append({
            "call_sid": call_sid,
            "phone": phone,
            "queued_at": datetime.now().isoformat(),
            "status": "queued"
        })

        logger.call(phone, f"Added to queue for agent {agent_name}")

    async def start_amd_gate(
        self,
        *,
        campaign_id: str,
        agent_name: str,
        phone: str,
        call_sid: str,
        answered_at_ms: int,
    ) -> None:
        """
        Start the AMD gating timers for an answered call.

        - 0-3s: status=amd_listening (do not connect)
        - at 3s if still undecided: status=amd_unknown (show Connect button)
        - fail-safe: handled by Twilio TwiML (Pause+Redirect) in /contact-to-queue
        """
        if not (campaign_id and agent_name and phone and call_sid):
            return
        if campaign_id not in campaigns:
            return

        campaign = campaigns[campaign_id]
        campaign.setdefault("amd_answered_at_ms", {})[phone] = answered_at_ms

        # Ensure initial status
        contact_status = campaign.setdefault("contact_status", {})
        if contact_status.get(phone) not in ("voicemail", "dropped_by_system", "in-progress", "connected"):
            contact_status[phone] = "amd_listening"

        # Broadcast status update so UI reflects AMD listening state
        await broadcast_to_agent(agent_name, {
            "type": "status_update",
            "phone": phone,
            "status": "amd_listening",
            "contact_status": campaign.get("contact_status", {}),
        })

        # Cancel any existing timer for same call_sid
        prev = self._amd_timers.pop(call_sid, None)
        if prev:
            prev.cancel()

        async def _timer():
            try:
                await asyncio.sleep(3.0)
                # After 3s: if still not connected and not decided, mark UNKNOWN (manual connect)
                c = campaigns.get(campaign_id)
                if not c:
                    return
                cs = c.get("contact_status", {})
                if cs.get(phone) == "amd_listening":
                    cs[phone] = "amd_unknown"
                    await broadcast_to_agent(agent_name, {
                        "type": "status_update",
                        "phone": phone,
                        "status": "amd_unknown",
                        "contact_status": cs,
                    })
            except asyncio.CancelledError:
                return
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error(f"AMD timer error call_sid={call_sid} err={e}")
            finally:
                self._amd_timers.pop(call_sid, None)

        self._amd_timers[call_sid] = asyncio.create_task(_timer())

    async def handle_rule_based_amd(
        self,
        *,
        agent_name: str,
        phone: str,
        call_sid: str,
        amd: dict,
    ) -> None:
        """
        Handle AMD messages coming from the transcription service.

        Expected shape:
          amd = {"decision": "VOICEMAIL"|"HUMAN"|"UNKNOWN", "confidence": float, ...}
        """
        if not agent_name or not phone or not call_sid or not isinstance(amd, dict):
            return

        agent = agents.get(agent_name) or {}
        campaign_id = agent.get("campaign_id")
        if not campaign_id or campaign_id not in campaigns:
            return

        decision = (amd.get("decision") or "").upper()
        decided_flag = amd.get("decided")

        campaign = campaigns[campaign_id]
        cs = campaign.setdefault("contact_status", {})

        # Interim UNKNOWN (e.g. after 3s) -> enable manual connect, do not auto-connect
        if decision == "UNKNOWN" and decided_flag is False:
            if cs.get(phone) == "amd_listening":
                cs[phone] = "amd_unknown"
                await broadcast_to_agent(agent_name, {
                    "type": "status_update",
                    "phone": phone,
                    "status": "amd_unknown",
                    "contact_status": cs,
                })
            return

        if decision == "VOICEMAIL":
            # Drop immediately
            logger.call(phone, f"Rule-based AMD: VOICEMAIL (dropping) call_sid={call_sid}")
            self.cancel_amd_timer(call_sid)
            twilio_service.hangup_call(call_sid)
            cs[phone] = "voicemail"
            await broadcast_to_agent(agent_name, {
                "type": "status_update",
                "phone": phone,
                "status": "voicemail",
                "contact_status": cs,
                "amd": amd,
            })
            return

        if decision == "HUMAN":
            # Connect immediately and drop other calls for this agent/campaign
            logger.call(phone, f"Rule-based AMD: HUMAN (connecting) call_sid={call_sid}")
            await self.connect_selected_call(
                agent_name=agent_name,
                campaign_id=campaign_id,
                selected_phone=phone,
                reason="amd_human",
                amd=amd,
            )
            return

        if decision == "UNKNOWN":
            # Final unknown (e.g. hard-stop) -> auto connect topmost if still nothing connected
            await self.auto_connect_topmost_if_needed(campaign_id=campaign_id, agent_name=agent_name)

    async def connect_selected_call(
        self,
        *,
        agent_name: str,
        campaign_id: str,
        selected_phone: str,
        reason: str,
        amd: Optional[dict] = None,
    ) -> None:
        """
        Connect a selected pending call to the agent queue, and drop all other active calls.
        """
        if campaign_id not in campaigns:
            return
        campaign = campaigns[campaign_id]

        queue_name = campaign.get("queue_name")
        if not queue_name:
            logger.error(f"Missing agent queue name for campaign {campaign_id}")
            return

        call_sids = campaign.get("call_sids", {}) or {}
        selected_sid = call_sids.get(selected_phone)
        if not selected_sid:
            logger.warning(f"No call_sid found for phone {selected_phone}")
            return

        # Check if already connected to prevent duplicate processing
        if campaign.get("connected_phone") == selected_phone:
            logger.warning(f"Call {selected_phone} already connected, skipping duplicate connect (reason: {reason})")
            return

        # Drop everyone else first (so agent doesn't get multiple connects racing)
        for phone, sid in list(call_sids.items()):
            if phone == selected_phone:
                continue
            status = (campaign.get("contact_status", {}) or {}).get(phone)
            if status in ("dialing", "ringing", "amd_listening", "amd_unknown", "queued"):
                twilio_service.hangup_call(sid)
                campaign["contact_status"][phone] = "dropped_by_system"

        # Redirect selected call into agent queue via TwiML.
        from urllib.parse import quote
        encoded_campaign = quote(campaign_id, safe="")
        encoded_phone = quote(selected_phone, safe="")
        encoded_agent = quote(agent_name or "", safe="")
        encoded_queue = quote(queue_name, safe="")
        # Build an absolute URL so Twilio can fetch TwiML.
        from app.config import BASE_URL
        redirect_url = f"{BASE_URL}/api/voice/amd-bridge?campaign_id={encoded_campaign}&phone={encoded_phone}&agent_name={encoded_agent}&queue_name={encoded_queue}&reason={quote(reason, safe='')}"

        ok = twilio_service.redirect_call(selected_sid, redirect_url)
        if not ok:
            logger.warning(f"Failed to redirect call {selected_sid} to agent queue")
            return

        campaign["connected_phone"] = selected_phone
        campaign["status"] = "connected"
        campaign["contact_status"][selected_phone] = "in-progress"
        agents.get(agent_name, {}).update({"connected_phone": selected_phone, "in_call": True})

        await broadcast_to_agent(agent_name, {
            "type": "customer_connected",
            "phone": selected_phone,
            "call_sid": selected_sid,
            "queue_name": queue_name,
            "reason": reason,
            "amd": amd,
            "campaign": {
                "contact_status": campaign.get("contact_status", {}),
            }
        })

    async def auto_connect_topmost_if_needed(self, *, campaign_id: str, agent_name: str) -> None:
        """
        At 10 seconds, if still UNKNOWN, connect the topmost pending call and drop the rest.
        """
        if campaign_id not in campaigns:
            return
        campaign = campaigns[campaign_id]

        # If already connected, do nothing
        if campaign.get("connected_phone"):
            return

        cs = campaign.get("contact_status", {}) or {}
        answered_at = campaign.get("amd_answered_at_ms", {}) or {}
        pending = [p for p, st in cs.items() if st in ("amd_unknown", "amd_listening")]
        if not pending:
            return

        pending.sort(key=lambda p: int(answered_at.get(p, 0) or 0))
        selected_phone = pending[0]
        await self.connect_selected_call(
            agent_name=agent_name,
            campaign_id=campaign_id,
            selected_phone=selected_phone,
            reason="auto_10s_unknown",
            amd={"decision": "UNKNOWN", "confidence": 0.30, "decided": True},
        )

    def remove_from_queue(self, agent_name: str, call_sid: str):
        """Remove a call from the agent's queue"""
        if agent_name in call_queues:
            call_queues[agent_name] = [
                call for call in call_queues[agent_name]
                if call["call_sid"] != call_sid
            ]
    
    def get_queue(self, agent_name: str) -> list:
        """Get all queued calls for an agent"""
        return call_queues.get(agent_name, [])
    
    async def process_detection_result(self, campaign_id: str, call_sid: str, phone: str, detection_result: dict, agent_name: str = None):
        """Process detection result and connect call to agent's queue if appropriate"""
        if campaign_id not in campaigns:
            logger.warning(f"Campaign {campaign_id} not found")
            return
        
        campaign = campaigns[campaign_id]
        
        # Get agent name from campaign if not provided
        if not agent_name:
            agent_name = campaign.get("agent_name")
        
        if not agent_name or agent_name not in agents:
            logger.warning(f"Agent {agent_name} not found")
            return
        
        # Store detection result
        detection_results[call_sid] = detection_result
        
        # Check if this call is still in queue
        queue_item = None
        if agent_name in call_queues:
            for item in call_queues[agent_name]:
                if item["call_sid"] == call_sid:
                    queue_item = item
                    break
        
        if not queue_item:
            logger.warning(f"Call {call_sid} not found in queue for agent {agent_name}")
            return
        
        # Get detection result
        answered_by = detection_result.get("AnsweredBy", "unknown")
        machine_detection_status = detection_result.get("MachineDetectionStatus", "unknown")
        
        logger.call(phone, f"Detection result: AnsweredBy={answered_by}, Status={machine_detection_status}")
        
        # Decision logic: connect unless it's clearly voicemail
        should_connect = True  # Default to connect

        if answered_by == "machine":
            # Hang up voicemail/answering machine
            should_connect = False

        if should_connect:
            # Customer has passed AMD and should be connected to agent
            # Since agent is in "waiting" state, notify them to connect to the queue
            self.remove_from_queue(agent_name, call_sid)

            # Update campaign state
            campaign["contact_status"][phone] = "in-progress"
            agents[agent_name]["connected_phone"] = phone
            campaign["connected_phone"] = phone
            campaign["status"] = "connected"

            # Notify agent to connect to the global wait queue (hang up waiting call and connect to queue)
            await broadcast_to_agent(agent_name, {
                "type": "customer_ready",
                "phone": phone,
                "queue_name": "wait",  # Global wait queue
                "detection_result": detection_result,
                "campaign": campaign
            })
        else:
            # Hang up the call (voicemail/answering machine)
            logger.call(phone, f"Hanging up - voicemail detected: {answered_by}")
            twilio_service.hangup_call(call_sid)
            self.remove_from_queue(agent_name, call_sid)

            # Update status for voicemail
            campaign["contact_status"][phone] = "voicemail"

            # Broadcast update
            await broadcast_to_agent(agent_name, {
                "type": "call_rejected",
                "phone": phone,
                "reason": f"Voicemail: {answered_by}",
                "detection_result": detection_result
            })
    
    async def _hangup_other_calls(self, campaign_id: str, connected_phone: str):
        """Hang up all other calls except the connected one"""
        if campaign_id not in campaigns:
            return
        
        campaign = campaigns[campaign_id]
        call_sids = campaign.get("call_sids", {})
        
        for phone, call_sid in call_sids.items():
            if phone != connected_phone:
                twilio_service.hangup_call(call_sid)


# Singleton instance
call_queue_service = CallQueueService()
