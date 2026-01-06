"""Call queue service for managing queued calls"""
import asyncio
from datetime import datetime
from typing import Optional
from app.storage import call_queues, campaigns, detection_results
from app.services.twilio_service import twilio_service
from app.websocket.manager import broadcast_to_campaign


class CallQueueService:
    """Service for managing call queues"""
    
    def add_to_queue(self, campaign_id: str, call_sid: str, phone: str):
        """Add a call to the queue"""
        if campaign_id not in call_queues:
            call_queues[campaign_id] = []
        
        call_queues[campaign_id].append({
            "call_sid": call_sid,
            "phone": phone,
            "queued_at": datetime.now().isoformat(),
            "status": "queued"
        })
        
        print(f"Added call {call_sid} ({phone}) to queue for campaign {campaign_id}")
    
    def remove_from_queue(self, campaign_id: str, call_sid: str):
        """Remove a call from the queue"""
        if campaign_id in call_queues:
            call_queues[campaign_id] = [
                call for call in call_queues[campaign_id]
                if call["call_sid"] != call_sid
            ]
    
    def get_queue(self, campaign_id: str) -> list:
        """Get all queued calls for a campaign"""
        return call_queues.get(campaign_id, [])
    
    async def process_detection_result(self, campaign_id: str, call_sid: str, phone: str, detection_result: dict):
        """Process detection result and move call to conference if appropriate"""
        if campaign_id not in campaigns:
            print(f"Campaign {campaign_id} not found")
            return
        
        campaign = campaigns[campaign_id]
        
        # Store detection result
        detection_results[call_sid] = detection_result
        
        # Check if this call is still in queue
        queue_item = None
        if campaign_id in call_queues:
            for item in call_queues[campaign_id]:
                if item["call_sid"] == call_sid:
                    queue_item = item
                    break
        
        if not queue_item:
            print(f"Call {call_sid} not found in queue")
            return
        
        # Get detection result
        answered_by = detection_result.get("AnsweredBy", "unknown")
        machine_detection_status = detection_result.get("MachineDetectionStatus", "unknown")
        
        print(f"Detection result for {phone} (SID: {call_sid}): AnsweredBy={answered_by}, Status={machine_detection_status}")
        
        # Decision logic: connect unless it's clearly voicemail
        # Only hang up for machine/voicemail, connect for human and unknown
        should_connect = True  # Default to connect

        if answered_by == "machine":
            # Hang up voicemail/answering machine
            should_connect = False
        # answered_by == "human" or "unknown" -> connect
        
        if should_connect:
            # Check if someone already connected
            if campaign.get("status") == "connected" and campaign.get("connected_phone") != phone:
                print(f"Agent already connected to another call, hanging up {phone}")
                twilio_service.hangup_call(call_sid)
                self.remove_from_queue(campaign_id, call_sid)
                return
            
            # Dequeue call from Twilio queue and redirect to conference
            queue_name = f"campaign_{campaign_id}"
            from app.config import BASE_URL, CONFERENCE_NAME
            from urllib.parse import quote
            encoded_conf = quote(CONFERENCE_NAME, safe="")
            dequeue_url = f"{BASE_URL}/api/voice/customer-join-conference?conference={encoded_conf}"
            
            success = twilio_service.dequeue_call(queue_name, call_sid, dequeue_url)
            if success:
                # Update campaign state
                campaign["connected_phone"] = phone
                campaign["status"] = "connected"
                campaign["contact_status"][phone] = "in-progress"
                
                # Remove from queue
                self.remove_from_queue(campaign_id, call_sid)
                
                # Hang up other calls
                await self._hangup_other_calls(campaign_id, phone)
                
                # Broadcast update
                await broadcast_to_campaign(campaign_id, {
                    "type": "customer_connected",
                    "phone": phone,
                    "detection_result": detection_result,
                    "campaign": campaign
                })
            else:
                print(f"Failed to redirect call {call_sid} to conference")
        else:
            # Hang up the call (only for machine/voicemail)
            print(f"Hanging up {phone} - voicemail detected: {answered_by}")
            twilio_service.hangup_call(call_sid)
            self.remove_from_queue(campaign_id, call_sid)

            # Update status for voicemail
            campaign["contact_status"][phone] = "voicemail"

            # Broadcast update
            await broadcast_to_campaign(campaign_id, {
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

