"""Campaign service for managing campaigns"""

import uuid
from typing import Optional
from app.storage import campaigns
from app.services.twilio_service import twilio_service
from app.services.call_queue_service import call_queue_service
from concurrent.futures import ThreadPoolExecutor
import asyncio

executor = ThreadPoolExecutor(max_workers=10)


class CampaignService:
    """Service for managing campaigns"""

    def create_campaign(self, contacts: list[str], identity: str) -> dict:
        """Create a new campaign"""
        campaign_id = uuid.uuid4().hex[:8]

        campaign = {
            "id": campaign_id,
            "contacts": contacts,
            "contact_status": {phone: "pending" for phone in contacts},
            "call_sids": {},
            "dispositions": {},
            "call_order": [],
            "status": "dialing",
            "agent_identity": identity,
            "connected_phone": None,
        }

        campaigns[campaign_id] = campaign

        # Start dialing the first contact
        if contacts:
            first_phone = contacts[0]
            campaign["contact_status"][first_phone] = "dialing"
            loop = asyncio.get_event_loop()

            def dial_and_store():
                call_sid = twilio_service.dial_contact(first_phone, campaign_id)
                if call_sid:
                    campaign["call_sids"][first_phone] = call_sid

            loop.run_in_executor(executor, dial_and_store)

        return campaign

    def get_campaign(self, campaign_id: str) -> Optional[dict]:
        """Get campaign by ID"""
        return campaigns.get(campaign_id)

    def save_disposition(
        self, campaign_id: str, phone: str, disposition: str, notes: str = ""
    ):
        """Save disposition for a call"""
        if campaign_id not in campaigns:
            return None

        campaign = campaigns[campaign_id]
        from datetime import datetime

        campaign["dispositions"][phone] = {
            "disposition": disposition,
            "notes": notes,
            "timestamp": datetime.now().isoformat(),
        }

        return campaign["dispositions"][phone]

    def dial_next_contact(self, campaign_id: str) -> Optional[str]:
        """Dial the next uncalled contact"""
        if campaign_id not in campaigns:
            return None

        campaign = campaigns[campaign_id]

        # Reset status for next round
        campaign["status"] = "dialing"
        campaign["connected_phone"] = None

        # Find contacts that haven't been called recently or are pending
        called_phones = set(campaign.get("call_order", []))

        next_phone = None

        # First, try pending contacts (never called)
        for phone in campaign["contacts"]:
            if phone not in called_phones:
                next_phone = phone
                break

        # If all have been called, pick the least recently called
        if not next_phone and campaign.get("call_order"):
            for phone in campaign["call_order"]:
                status = campaign["contact_status"].get(phone, "pending")
                if status not in [
                    "in-progress",
                    "ringing",
                    "dialing",
                    "initiated",
                    "queued",
                ]:
                    next_phone = phone
                    break

        if next_phone:
            campaign["contact_status"][next_phone] = "dialing"
            loop = asyncio.get_event_loop()

            def dial_and_store():
                call_sid = twilio_service.dial_contact(next_phone, campaign_id)
                if call_sid:
                    campaign["call_sids"][next_phone] = call_sid

            loop.run_in_executor(executor, dial_and_store)
            return next_phone

        return None

    def end_campaign(self, campaign_id: str):
        """End campaign and hang up all calls"""
        if campaign_id not in campaigns:
            return False

        campaign = campaigns[campaign_id]
        campaign["status"] = "ended"

        # Hang up all calls
        call_sids = campaign.get("call_sids", {})
        for phone, call_sid in call_sids.items():
            twilio_service.hangup_call(call_sid)

        return True

    def update_call_status(
        self, campaign_id: str, phone: str, call_status: str, call_sid: str = None
    ):
        """Update call status for a contact"""
        if campaign_id not in campaigns:
            return

        campaign = campaigns[campaign_id]

        if phone in campaign["contact_status"]:
            previous_status = campaign["contact_status"].get(phone)
            campaign["contact_status"][phone] = call_status

            # Track call order when initiated
            if call_status == "initiated":
                if phone not in campaign.get("call_order", []):
                    if "call_order" not in campaign:
                        campaign["call_order"] = []
                    campaign["call_order"].append(phone)

            # Store call SID
            if call_sid:
                if "call_sids" not in campaign:
                    campaign["call_sids"] = {}
                campaign["call_sids"][phone] = call_sid


# Singleton instance
campaign_service = CampaignService()
