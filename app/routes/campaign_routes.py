"""Campaign API routes"""
from fastapi import APIRouter, HTTPException
from app.models.campaign import CampaignCreate, DispositionData
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


@router.post("/campaign")
async def create_campaign(campaign_data: CampaignCreate):
    """Create campaign, return token, AND start dialing immediately"""
    token, identity = twilio_service.generate_token()
    if not token:
        raise HTTPException(status_code=500, detail="Twilio credentials not configured.")
    
    campaign = campaign_service.create_campaign(campaign_data.contacts, identity)
    
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


@router.post("/campaign/{campaign_id}/dial-next")
async def dial_next_contact(campaign_id: str):
    """Dial the next uncalled contact (least recently called order)"""
    next_phone = campaign_service.dial_next_contact(campaign_id)
    
    if next_phone:
        return {"status": "dialing", "phone": next_phone}
    else:
        return {"status": "no_more_contacts", "phone": None}


@router.post("/campaign/{campaign_id}/end")
async def end_campaign(campaign_id: str):
    """End campaign and hang up all calls"""
    success = campaign_service.end_campaign(campaign_id)
    if not success:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    from app.websocket.manager import broadcast_to_campaign
    await broadcast_to_campaign(campaign_id, {
        "type": "campaign_ended",
        "campaign_id": campaign_id
    })
    
    return {"status": "ended"}


@router.get("/campaign/{campaign_id}")
async def get_campaign(campaign_id: str):
    """Get campaign details"""
    campaign = campaign_service.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign

