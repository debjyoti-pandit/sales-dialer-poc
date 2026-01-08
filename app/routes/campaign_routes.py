"""Campaign API routes"""
from fastapi import APIRouter, HTTPException, Query
from app.models.campaign import DispositionData
from app.services.campaign_service import campaign_service
from app.services.contact_list_service import contact_list_service
from app.services.twilio_service import twilio_service
from app.storage import agents, campaigns
from app.logger import logger

router = APIRouter(prefix="/api", tags=["campaign"])


@router.post("/token")
async def get_twilio_token():
    """Generate Twilio Access Token (for token refresh)"""
    token, identity = twilio_service.generate_token()
    if not token:
        raise HTTPException(status_code=500, detail="Twilio credentials not configured.")
    return {"token": token, "identity": identity}


@router.post("/campaign/start")
async def start_campaign(agent_name: str = Query(..., description="Agent name")):
    """Start campaign for an agent - add to queue and dial batch of contacts"""
    
    token, identity = twilio_service.generate_token()
    if not token:
        raise HTTPException(status_code=500, detail="Twilio credentials not configured.")
    
    campaign = campaign_service.start_agent_campaign(agent_name, identity)
    
    return {
        "campaign": campaign,
        "token": token,
        "identity": identity
    }


@router.post("/campaign/{campaign_id}/disposition")
async def save_disposition(campaign_id: str, data: DispositionData):
    """Save disposition for a call"""
    result = campaign_service.save_disposition(
        campaign_id, data.phone, data.disposition, data.notes
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    logger.success(f"Disposition saved for {data.phone}: {data.disposition}")
    
    return {"status": "saved", "phone": data.phone, "disposition": data.disposition}


@router.post("/agent/{agent_name}/dial-next-batch")
async def dial_next_batch(agent_name: str):
    """Dial the next batch of undialed contacts for an agent"""
    result = campaign_service.dial_next_batch(agent_name)

    # Debug: Log what we got back from dial_next_batch
    logger.info(f"Dial next batch result: phones={result['phones']}, next_batch={result['next_batch']}")

    # Get updated campaign data to broadcast to frontend
    agent = agents.get(agent_name)
    if agent:
        campaign_id = agent.get("campaign_id")
        if campaign_id and campaign_id in campaigns:
            campaign = campaigns[campaign_id]

            # Check if we're recycling (next batch contains previously dialed contacts)
            from app.storage import dialed_contacts
            next_batch_contacts = campaign.get("next_batch", [])
            is_recycling = next_batch_contacts and any(contact in dialed_contacts for contact in next_batch_contacts)

            # Debug logging
            logger.info(f"Campaign update - Agent: {agent_name}, Contacts: {campaign['contacts']}, Next: {campaign.get('next_batch', [])}, Recycling: {is_recycling}")

            # Broadcast updated campaign data including new contacts
            campaign_data = {
                "id": campaign["id"],
                "contacts": campaign["contacts"],
                "contact_status": campaign["contact_status"],
                "next_batch": campaign.get("next_batch", []),
                "is_recycling": is_recycling
            }

            from app.websocket.manager import broadcast_to_agent
            await broadcast_to_agent(agent_name, {
                "type": "campaign_updated",
                "campaign": campaign_data
            })

    if result["phones"]:
        return {
            "status": "dialing",
            "phones": result["phones"],
            "count": len(result["phones"]),
            "next_batch": result["next_batch"]
        }
    else:
        return {"status": "no_more_contacts", "phones": [], "next_batch": []}


@router.post("/agent/{agent_name}/end")
async def end_agent_campaign(agent_name: str):
    """End campaign for an agent and hang up all calls"""
    success = campaign_service.end_agent_campaign(agent_name)
    if not success:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Get the campaign to broadcast final status
    agent = agents.get(agent_name)
    campaign_id = agent.get("campaign_id") if agent else None
    campaign = campaigns.get(campaign_id) if campaign_id else None

    from app.websocket.manager import broadcast_to_agent
    await broadcast_to_agent(agent_name, {
        "type": "campaign_ended",
        "agent_name": agent_name,
        "contact_status": campaign.get("contact_status", {}) if campaign else {}
    })

    return {"status": "ended"}


@router.get("/agent/{agent_name}/campaign")
async def get_agent_campaign(agent_name: str):
    """Get campaign details for an agent"""
    campaign = campaign_service.get_agent_campaign(agent_name)
    if not campaign:
        raise HTTPException(status_code=404, detail="Agent campaign not found")
    return campaign
