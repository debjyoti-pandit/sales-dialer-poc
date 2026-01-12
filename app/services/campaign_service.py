"""Campaign service for managing campaigns"""
import uuid
import re
from typing import Optional
from app.storage import campaigns, agents, dialed_contacts, campaign_contact_reservations
from app.services.twilio_service import twilio_service
from app.services.contact_list_service import contact_list_service
from app.config import BATCH_DIAL_COUNT, AGENT_CONTACT_POOL_SIZE
from concurrent.futures import ThreadPoolExecutor
import asyncio

executor = ThreadPoolExecutor(max_workers=10)


class CampaignService:
    """Service for managing campaigns"""

    def start_agent_campaign(self, agent_name: str, identity: str, campaign_list_id: int = None, batch_size: int = BATCH_DIAL_COUNT) -> dict:
        """Start a campaign for an agent - connect agent to queue first, then dial contacts"""
        campaign_id = uuid.uuid4().hex[:8]
        # Agent-specific Twilio queue so only this agent can receive their dialed contacts
        safe_agent_name = re.sub(r"[^A-Za-z0-9_]", "_", agent_name or "unknown")
        queue_name = f"agent_{safe_agent_name}"

        # Create or update agent
        agent = {
            "name": agent_name,
            "campaign_id": campaign_id,
            "campaign_list_id": campaign_list_id,  # Store the selected campaign list ID
            "status": "waiting_in_queue",
            "identity": identity,
            "connected_phone": None,
            "queue_name": queue_name,
        }
        agents[agent_name] = agent

        # Reserve a fixed pool of contacts for this agent within the selected campaign list.
        # This prevents another agent selecting the same campaign from seeing these contacts.
        if campaign_list_id is None:
            campaign_list_id = 1  # fallback to first campaign if not provided

        reservations = campaign_contact_reservations.setdefault(int(campaign_list_id), {})
        excluded = set(reservations.keys()) | set(dialed_contacts.keys())

        all_contacts = contact_list_service.get_contacts(campaign_id=campaign_list_id)
        assigned_contacts = [p for p in all_contacts if p not in excluded][:AGENT_CONTACT_POOL_SIZE]

        for phone in assigned_contacts:
            reservations[phone] = agent_name

        if not assigned_contacts:
            return {
                "id": campaign_id,
                "agent_name": agent_name,
                "contacts": [],
                "contact_status": {},
                "call_sids": {},
                "dispositions": {},
                "status": "no_contacts",
                "message": "No more contacts to dial",
                "next_batch": [],
                "queue_name": queue_name
            }

        # First dial batch preview (what will be dialed when agent connects)
        next_batch_preview = assigned_contacts[:batch_size]

        # Create campaign
        campaign = {
            "id": campaign_id,
            "agent_name": agent_name,
            "campaign_list_id": campaign_list_id,  # Store the selected campaign list ID
            # Full reserved pool for this agent (typically 20)
            "contacts": assigned_contacts,
            "contact_status": {phone: "pending" for phone in assigned_contacts},
            "call_sids": {},
            "dispositions": {},
            "status": "agent_in_queue",
            "agent_identity": identity,
            "connected_phone": None,
            "next_batch": next_batch_preview,
            "queue_name": queue_name,
        }

        campaigns[campaign_id] = campaign

        # Agent will connect to queue directly via device.connect() in the frontend
        # Contacts will be dialed when agent connects via the /dial endpoint webhook

        return campaign

    def get_campaign(self, campaign_id: str) -> Optional[dict]:
        """Get campaign by ID"""
        return campaigns.get(campaign_id)

    def get_agent_campaign(self, agent_name: str) -> Optional[dict]:
        """Get campaign for an agent"""
        if agent_name not in agents:
            return None
        agent = agents[agent_name]
        campaign_id = agent.get("campaign_id")
        if campaign_id:
            return campaigns.get(campaign_id)
        return None

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

    def dial_next_batch(self, agent_name: str, batch_size: int = BATCH_DIAL_COUNT) -> dict:
        """Dial next batch of pending contacts from agent's reserved pool"""
        if agent_name not in agents:
            return {"phones": [], "next_batch": []}

        agent = agents[agent_name]
        campaign_id = agent.get("campaign_id")

        if not campaign_id or campaign_id not in campaigns:
            return {"phones": [], "next_batch": []}

        campaign = campaigns[campaign_id]
        pending = [p for p in campaign.get("contacts", []) if campaign["contact_status"].get(p) == "pending"]
        to_dial = pending[:batch_size]
        if not to_dial:
            campaign["next_batch"] = []
            return {"phones": [], "next_batch": []}

        # Mark selected as dialing
        for phone in to_dial:
            campaign["contact_status"][phone] = "dialing"

        loop = asyncio.get_event_loop()
        dialed_phones = []
        safe_agent_name = re.sub(r"[^A-Za-z0-9_]", "_", agent_name or "unknown")
        queue_name = campaign.get("queue_name") or f"agent_{safe_agent_name}"
        for phone in to_dial:
            def dial_and_store(phone_num=phone):
                call_sid = twilio_service.dial_contact_to_agent_queue(phone_num, campaign_id, queue_name, agent_name)
                if call_sid:
                    campaign["call_sids"][phone_num] = call_sid
                    dialed_phones.append(phone_num)
                    if phone_num not in dialed_contacts:
                        dialed_contacts[phone_num] = set()
                    dialed_contacts[phone_num].add(agent_name)

            loop.run_in_executor(executor, dial_and_store)

        remaining_pending = [p for p in campaign.get("contacts", []) if campaign["contact_status"].get(p) == "pending"]
        next_batch_preview = remaining_pending[:batch_size]
        campaign["next_batch"] = next_batch_preview
        return {"phones": dialed_phones, "next_batch": next_batch_preview}

    def end_campaign(self, campaign_id: str):
        """End campaign and hang up all calls"""
        if campaign_id not in campaigns:
            return False

        campaign = campaigns[campaign_id]
        campaign["status"] = "ended"

        # Reset all contact statuses to "ended"
        for phone in campaign.get("contacts", []):
            campaign["contact_status"][phone] = "ended"

        # Update agent status
        agent_name = campaign.get("agent_name")
        if agent_name and agent_name in agents:
            agents[agent_name]["status"] = "inactive"
            agents[agent_name].pop("campaign_id", None)

        # Release reserved contacts for this agent + campaign list
        campaign_list_id = campaign.get("campaign_list_id")
        if campaign_list_id is not None:
            reservations = campaign_contact_reservations.get(int(campaign_list_id), {})
            for phone in campaign.get("contacts", []):
                if reservations.get(phone) == agent_name:
                    reservations.pop(phone, None)
            if not reservations and int(campaign_list_id) in campaign_contact_reservations:
                campaign_contact_reservations.pop(int(campaign_list_id), None)

        # Hang up all calls
        call_sids = campaign.get("call_sids", {})
        for phone, call_sid in call_sids.items():
            twilio_service.hangup_call(call_sid)

        return True

    def end_agent_campaign(self, agent_name: str):
        """End campaign for an agent"""
        if agent_name not in agents:
            return False
        
        agent = agents[agent_name]
        campaign_id = agent.get("campaign_id")
        
        if campaign_id:
            return self.end_campaign(campaign_id)
        
        return False

    def update_call_status(
        self, campaign_id: str, phone: str, call_status: str, call_sid: str = None
    ):
        """Update call status for a contact"""
        if campaign_id not in campaigns:
            return

        campaign = campaigns[campaign_id]

        if phone in campaign["contact_status"]:
            # Don't overwrite a backend-forced outcome (e.g. answered but we disconnected
            # because no agent was available). Twilio will still send "completed" later.
            if campaign["contact_status"].get(phone) == "answered_disconnected_by_system":
                return

            campaign["contact_status"][phone] = call_status

            # Store call SID
            if call_sid:
                if "call_sids" not in campaign:
                    campaign["call_sids"] = {}
                campaign["call_sids"][phone] = call_sid


# Singleton instance
campaign_service = CampaignService()
