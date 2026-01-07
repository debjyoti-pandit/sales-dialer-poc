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
    
    def add_to_queue(self, agent_name: str, call_sid: str, phone: str):
        """Add a call to the global wait queue"""
        if "wait" not in call_queues:
            call_queues["wait"] = []

        call_queues["wait"].append({
            "call_sid": call_sid,
            "phone": phone,
            "agent_name": agent_name,
            "queued_at": datetime.now().isoformat(),
            "status": "queued"
        })

        logger.call(phone, f"Added to global wait queue for agent {agent_name}")

    def remove_from_queue(self, agent_name: str, call_sid: str):
        """Remove a call from the global wait queue"""
        if "wait" in call_queues:
            call_queues["wait"] = [
                call for call in call_queues["wait"]
                if call["call_sid"] != call_sid
            ]
    
    def get_queue(self, agent_name: str = None) -> list:
        """Get all queued calls from the global wait queue"""
        return call_queues.get("wait", [])
    
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
        
        # Check if this call is still in the global wait queue
        queue_item = None
        if "wait" in call_queues:
            for item in call_queues["wait"]:
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
