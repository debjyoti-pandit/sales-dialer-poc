"""Campaign API routes"""
from fastapi import APIRouter, HTTPException, Query
from app.models.campaign import DispositionData
from app.services.campaign_service import campaign_service
from app.services.twilio_service import twilio_service

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
    
    print(f"Disposition saved for {data.phone}: {data.disposition}")
    
    return {"status": "saved", "phone": data.phone, "disposition": data.disposition}


@router.post("/agent/{agent_name}/dial-next-batch")
async def dial_next_batch(agent_name: str):
    """Dial the next batch of undialed contacts for an agent"""
    dialed_phones = campaign_service.dial_next_batch(agent_name)
    
    if dialed_phones:
        return {"status": "dialing", "phones": dialed_phones, "count": len(dialed_phones)}
    else:
        return {"status": "no_more_contacts", "phones": []}


@router.post("/agent/{agent_name}/end")
async def end_agent_campaign(agent_name: str):
    """End campaign for an agent and hang up all calls"""
    success = campaign_service.end_agent_campaign(agent_name)
    if not success:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    from app.websocket.manager import broadcast_to_agent
    await broadcast_to_agent(agent_name, {
        "type": "campaign_ended",
        "agent_name": agent_name
    })
    
    return {"status": "ended"}


@router.get("/agent/{agent_name}/campaign")
async def get_agent_campaign(agent_name: str):
    """Get campaign details for an agent"""
    campaign = campaign_service.get_agent_campaign(agent_name)
    if not campaign:
        raise HTTPException(status_code=404, detail="Agent campaign not found")
    return campaign
