"""Campaign service for managing campaigns"""
import uuid
from typing import Optional
from app.storage import campaigns, agents, dialed_contacts
from app.services.twilio_service import twilio_service
from app.services.call_queue_service import call_queue_service
from app.services.contact_list_service import contact_list_service
from app.config import BATCH_DIAL_COUNT
from concurrent.futures import ThreadPoolExecutor
import asyncio

executor = ThreadPoolExecutor(max_workers=10)


class CampaignService:
    """Service for managing campaigns"""

    def start_agent_campaign(self, agent_name: str, identity: str, batch_size: int = BATCH_DIAL_COUNT) -> dict:
        """Start a campaign for an agent - add to queue and dial batch of contacts"""
        campaign_id = uuid.uuid4().hex[:8]

        # Create or update agent
        agent = {
            "name": agent_name,
            "campaign_id": campaign_id,
            "status": "active",
            "identity": identity,
            "connected_phone": None,
        }
        agents[agent_name] = agent

        # Get all dialed contacts across all agents
        all_dialed = set()
        for phone, agent_set in dialed_contacts.items():
            all_dialed.add(phone)

        # Get undialed contacts from shared list
        undialed_contacts = contact_list_service.get_undialed_contacts(all_dialed, batch_size)

        if not undialed_contacts:
            return {
                "id": campaign_id,
                "agent_name": agent_name,
                "contacts": [],
                "contact_status": {},
                "call_sids": {},
                "dispositions": {},
                "status": "no_contacts",
                "message": "No more contacts to dial"
            }

        # Create campaign
        campaign = {
            "id": campaign_id,
            "agent_name": agent_name,
            "contacts": undialed_contacts,
            "contact_status": {phone: "pending" for phone in undialed_contacts},
            "call_sids": {},
            "dispositions": {},
            "status": "dialing",
            "agent_identity": identity,
            "connected_phone": None,
        }

        campaigns[campaign_id] = campaign

        # Mark contacts as being dialed by this agent
        for phone in undialed_contacts:
            if phone not in dialed_contacts:
                dialed_contacts[phone] = set()
            dialed_contacts[phone].add(agent_name)

        # Batch dial contacts
        loop = asyncio.get_event_loop()
        for phone in undialed_contacts:
            campaign["contact_status"][phone] = "dialing"
            def dial_and_store(phone_num=phone):
                call_sid = twilio_service.dial_contact(phone_num, campaign_id, agent_name)
                if call_sid:
                    campaign["call_sids"][phone_num] = call_sid

            loop.run_in_executor(executor, dial_and_store)

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

    def dial_next_batch(self, agent_name: str, batch_size: int = BATCH_DIAL_COUNT) -> list[str]:
        """Dial next batch of undialed contacts for an agent"""
        if agent_name not in agents:
            return []

        agent = agents[agent_name]
        campaign_id = agent.get("campaign_id")
        
        if not campaign_id or campaign_id not in campaigns:
            return []

        campaign = campaigns[campaign_id]

        # Get all dialed contacts across all agents
        all_dialed = set()
        for phone, agent_set in dialed_contacts.items():
            all_dialed.add(phone)

        # Get undialed contacts
        undialed_contacts = contact_list_service.get_undialed_contacts(all_dialed, batch_size)

        if not undialed_contacts:
            return []

        # Add new contacts to campaign
        for phone in undialed_contacts:
            if phone not in campaign["contacts"]:
                campaign["contacts"].append(phone)
            campaign["contact_status"][phone] = "dialing"
            
            # Mark as dialed by this agent
            if phone not in dialed_contacts:
                dialed_contacts[phone] = set()
            dialed_contacts[phone].add(agent_name)

        # Batch dial contacts
        loop = asyncio.get_event_loop()
        dialed_phones = []
        for phone in undialed_contacts:
            def dial_and_store(phone_num=phone):
                call_sid = twilio_service.dial_contact(phone_num, campaign_id, agent_name)
                if call_sid:
                    campaign["call_sids"][phone_num] = call_sid
                    dialed_phones.append(phone_num)

            loop.run_in_executor(executor, dial_and_store)

        return dialed_phones

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
