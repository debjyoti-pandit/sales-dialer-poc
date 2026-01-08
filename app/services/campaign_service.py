"""Campaign service for managing campaigns"""
import uuid
from typing import Optional
from app.storage import campaigns, agents, dialed_contacts
from app.services.twilio_service import twilio_service
from app.services.contact_list_service import contact_list_service
from app.config import BATCH_DIAL_COUNT
from concurrent.futures import ThreadPoolExecutor
import asyncio

executor = ThreadPoolExecutor(max_workers=10)


class CampaignService:
    """Service for managing campaigns"""

    def start_agent_campaign(self, agent_name: str, identity: str, batch_size: int = BATCH_DIAL_COUNT) -> dict:
        """Start a campaign for an agent - connect agent to queue first, then dial contacts"""
        campaign_id = uuid.uuid4().hex[:8]
        queue_name = f"campaign_{campaign_id}"

        # Create or update agent
        agent = {
            "name": agent_name,
            "campaign_id": campaign_id,
            "status": "waiting_in_queue",
            "identity": identity,
            "connected_phone": None,
            "queue_name": queue_name,
        }
        agents[agent_name] = agent

        # Get all dialed contacts across all agents
        all_dialed = set()
        for phone, agent_set in dialed_contacts.items():
            all_dialed.add(phone)

        # Get first batch of contacts (start cycling from beginning)
        undialed_contacts = contact_list_service.get_next_batch_preview(set(), [], batch_size)

        if not undialed_contacts:
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

        # Get preview of next batch
        next_batch_preview = contact_list_service.get_next_batch_preview(all_dialed, undialed_contacts, batch_size)

        # Create campaign
        campaign = {
            "id": campaign_id,
            "agent_name": agent_name,
            "contacts": undialed_contacts,
            "contact_status": {phone: "pending" for phone in undialed_contacts},
            "call_sids": {},
            "dispositions": {},
            "status": "agent_in_queue",
            "agent_identity": identity,
            "connected_phone": None,
            "next_batch": next_batch_preview,
            "queue_name": queue_name,
        }

        campaigns[campaign_id] = campaign

        # Mark contacts as being dialed by this agent (but keep status as pending)
        for phone in undialed_contacts:
            if phone not in dialed_contacts:
                dialed_contacts[phone] = set()
            dialed_contacts[phone].add(agent_name)

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
        """Dial next batch of undialed contacts for an agent"""
        if agent_name not in agents:
            return {"phones": [], "next_batch": []}

        agent = agents[agent_name]
        campaign_id = agent.get("campaign_id")

        if not campaign_id or campaign_id not in campaigns:
            return {"phones": [], "next_batch": []}

        campaign = campaigns[campaign_id]

        # Get all dialed contacts across all agents
        all_dialed = set()
        for phone, agent_set in dialed_contacts.items():
            all_dialed.add(phone)

        # Get next batch in cycle based on current campaign contacts
        current_batch = campaign.get("contacts", [])
        undialed_contacts = contact_list_service.get_next_batch_preview(set(), current_batch, batch_size)

        if not undialed_contacts:
            return {"phones": [], "next_batch": []}

        # Get preview of next batch (after this one is dialed)
        next_batch_preview = contact_list_service.get_next_batch_preview(set(), undialed_contacts, batch_size)

        # Update campaign with next batch preview
        campaign["next_batch"] = next_batch_preview

        # Replace contacts with new batch (don't accumulate old contacts)
        campaign["contacts"] = undialed_contacts.copy()
        for phone in undialed_contacts:
            campaign["contact_status"][phone] = "dialing"

            # Mark as dialed by this agent
            if phone not in dialed_contacts:
                dialed_contacts[phone] = set()
            dialed_contacts[phone].add(agent_name)

        # Batch dial contacts
        loop = asyncio.get_event_loop()
        dialed_phones = []
        queue_name = campaign.get("queue_name", f"campaign_{campaign_id}")
        for phone in undialed_contacts:
            def dial_and_store(phone_num=phone):
                call_sid = twilio_service.dial_contact_to_queue(phone_num, campaign_id, queue_name, agent_name)
                if call_sid:
                    campaign["call_sids"][phone_num] = call_sid
                    dialed_phones.append(phone_num)

            loop.run_in_executor(executor, dial_and_store)

        return {"phones": dialed_phones, "next_batch": next_batch_preview}

    def end_campaign(self, campaign_id: str):
        """End campaign and hang up all calls"""
        if campaign_id not in campaigns:
            return False

        campaign = campaigns[campaign_id]
        campaign["status"] = "ended"

        # Update agent status
        agent_name = campaign.get("agent_name")
        if agent_name and agent_name in agents:
            agents[agent_name]["status"] = "inactive"
            agents[agent_name].pop("campaign_id", None)

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
            previous_status = campaign["contact_status"].get(phone)
            campaign["contact_status"][phone] = call_status

            # Store call SID
            if call_sid:
                if "call_sids" not in campaign:
                    campaign["call_sids"] = {}
                campaign["call_sids"][phone] = call_sid


# Singleton instance
campaign_service = CampaignService()
