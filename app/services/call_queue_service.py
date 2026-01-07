"""Call queue service for managing queued calls"""
import asyncio
from datetime import datetime
from typing import Optional
from app.storage import call_queues, campaigns, detection_results, agents
from app.services.twilio_service import twilio_service
from app.websocket.manager import broadcast_to_agent


class CallQueueService:
    """Service for managing call queues"""
    
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
        
        print(f"Added call {call_sid} ({phone}) to queue for agent {agent_name}")
    
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
            print(f"Campaign {campaign_id} not found")
            return
        
        campaign = campaigns[campaign_id]
        
        # Get agent name from campaign if not provided
        if not agent_name:
            agent_name = campaign.get("agent_name")
        
        if not agent_name or agent_name not in agents:
            print(f"Agent {agent_name} not found")
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
            print(f"Call {call_sid} not found in queue for agent {agent_name}")
            return
        
        # Get detection result
        answered_by = detection_result.get("AnsweredBy", "unknown")
        machine_detection_status = detection_result.get("MachineDetectionStatus", "unknown")
        
        print(f"Detection result for {phone} (SID: {call_sid}): AnsweredBy={answered_by}, Status={machine_detection_status}")
        
        # Decision logic: connect unless it's clearly voicemail
        should_connect = True  # Default to connect

        if answered_by == "machine":
            # Hang up voicemail/answering machine
            should_connect = False
        
        if should_connect:
            # Dequeue the call and dial it to the agent's device
            # The agent's device will receive an incoming call
            queue_name = f"agent_{agent_name}"
            
            # Get agent's identity to dial their device
            agent = agents.get(agent_name)
            if not agent:
                print(f"Agent {agent_name} not found")
                return
            
            agent_identity = agent.get("identity")
            if not agent_identity:
                print(f"Agent {agent_name} has no identity")
                return
            
            # Dequeue the call and redirect it to dial the agent's device
            # First, remove from our internal queue
            self.remove_from_queue(agent_name, call_sid)
            
            # Dequeue from Twilio queue and redirect to dial agent
            queue_name = f"agent_{agent_name}"
            from app.config import BASE_URL
            from urllib.parse import quote
            
            # Create TwiML URL that will dial the agent's client
            encoded_identity = quote(agent_identity, safe="")
            dequeue_url = f"{BASE_URL}/api/voice/connect-agent?agent_identity={encoded_identity}"
            
            # Dequeue and redirect
            success = twilio_service.dequeue_call(queue_name, call_sid, dequeue_url)
            
            if success:
                # Update campaign state
                campaign["contact_status"][phone] = "in-progress"
                
                # Update agent status
                agents[agent_name]["connected_phone"] = phone
                campaign["connected_phone"] = phone
                campaign["status"] = "connected"
                
                # Broadcast update
                await broadcast_to_agent(agent_name, {
                    "type": "customer_connected",
                    "phone": phone,
                    "detection_result": detection_result,
                    "campaign": campaign
                })
            else:
                print(f"Failed to dequeue call {call_sid} for agent {agent_name}")
        else:
            # Hang up the call (voicemail/answering machine)
            print(f"Hanging up {phone} - voicemail detected: {answered_by}")
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
