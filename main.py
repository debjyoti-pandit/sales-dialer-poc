import os
import json
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant
from twilio.twiml.voice_response import VoiceResponse, Dial
from twilio.rest import Client
from dotenv import load_dotenv
import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Set
from starlette.responses import FileResponse as StarletteFileResponse
import mimetypes

load_dotenv()

app = FastAPI(title="Sales Dialer POC")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Twilio credentials from environment
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_API_KEY = os.getenv("TWILIO_API_KEY")
TWILIO_API_SECRET = os.getenv("TWILIO_API_SECRET")
TWILIO_TWIML_APP_SID = os.getenv("TWILIO_TWIML_APP_SID")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

# Base URL for TwiML webhooks
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

# Twilio REST client for making outbound calls
twilio_client = None
if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# In-memory storage
campaigns: Dict[str, dict] = {}
active_websockets: Dict[str, Set[WebSocket]] = {}  # campaign_id -> set of websockets

# Thread pool for making calls
executor = ThreadPoolExecutor(max_workers=10)


class CampaignCreate(BaseModel):
    contacts: list[str]


# ============== WebSocket Management ==============

async def broadcast_to_campaign(campaign_id: str, message: dict):
    """Send message to all WebSocket clients for a campaign"""
    if campaign_id in active_websockets:
        dead_sockets = set()
        for ws in active_websockets[campaign_id]:
            try:
                await ws.send_json(message)
            except:
                dead_sockets.add(ws)
        # Clean up dead connections
        active_websockets[campaign_id] -= dead_sockets


@app.websocket("/ws/{campaign_id}")
async def websocket_endpoint(websocket: WebSocket, campaign_id: str):
    """WebSocket endpoint for real-time campaign updates"""
    await websocket.accept()
    
    # Add to active connections
    if campaign_id not in active_websockets:
        active_websockets[campaign_id] = set()
    active_websockets[campaign_id].add(websocket)
    
    print(f"WebSocket connected for campaign {campaign_id}")
    
    try:
        # Send current campaign state
        if campaign_id in campaigns:
            await websocket.send_json({
                "type": "campaign_state",
                "campaign": campaigns[campaign_id]
            })
        
        # Keep connection alive and handle incoming messages
        while True:
            data = await websocket.receive_text()
            # Handle any client messages if needed
            print(f"Received from client: {data}")
            
    except WebSocketDisconnect:
        print(f"WebSocket disconnected for campaign {campaign_id}")
        if campaign_id in active_websockets:
            active_websockets[campaign_id].discard(websocket)


# ============== Helper Functions ==============

def generate_twilio_token():
    """Generate Twilio Access Token for the browser client"""
    if not all([TWILIO_ACCOUNT_SID, TWILIO_API_KEY, TWILIO_API_SECRET, TWILIO_TWIML_APP_SID]):
        return None, None

    identity = f"agent_{uuid.uuid4().hex[:8]}"
    token = AccessToken(TWILIO_ACCOUNT_SID, TWILIO_API_KEY, TWILIO_API_SECRET, identity=identity)
    voice_grant = VoiceGrant(outgoing_application_sid=TWILIO_TWIML_APP_SID, incoming_allow=True)
    token.add_grant(voice_grant)
    return token.to_jwt(), identity


def dial_contact(phone_number: str, campaign_id: str):
    """Dial a single contact and connect to conference"""
    from urllib.parse import quote
    
    print(f"Dialing contact {phone_number} for campaign {campaign_id}")
    
    # Check if campaign is still active and no one has connected yet
    if campaign_id in campaigns:
        campaign = campaigns[campaign_id]
        if campaign.get("status") == "connected":
            print(f"Skipping {phone_number} - already connected to another contact")
            return None
        if campaign.get("status") == "ended":
            print(f"Skipping {phone_number} - campaign ended")
            return None
    
    if not twilio_client:
        print(f"Twilio client not configured, skipping {phone_number}")
        return None

    # URL-encode the phone number to handle + sign
    encoded_phone = quote(phone_number, safe='')
    
    try:
        call = twilio_client.calls.create(
            to=phone_number,
            from_=TWILIO_PHONE_NUMBER,
            url=f"{BASE_URL}/api/voice/customer-join?campaign_id={campaign_id}&phone={encoded_phone}",
            status_callback=f"{BASE_URL}/api/voice/status?campaign_id={campaign_id}&phone={encoded_phone}",
            status_callback_event=["initiated", "ringing", "answered", "completed"],
            status_callback_method="POST",
        )
        print(f"Call initiated to {phone_number}: {call.sid}")
        
        # Store call SID for later management
        if campaign_id in campaigns:
            if "call_sids" not in campaigns[campaign_id]:
                campaigns[campaign_id]["call_sids"] = {}
            campaigns[campaign_id]["call_sids"][phone_number] = call.sid
        
        return call.sid
    except Exception as e:
        print(f"Error dialing {phone_number}: {e}")
        return None


def hangup_call(call_sid: str):
    """Hang up a specific call"""
    if not twilio_client:
        return False
    try:
        twilio_client.calls(call_sid).update(status="completed")
        print(f"Hung up call {call_sid}")
        return True
    except Exception as e:
        print(f"Error hanging up call {call_sid}: {e}")
        return False


def hangup_all_calls(campaign_id: str):
    """Hang up all active calls for a campaign"""
    if campaign_id not in campaigns:
        return
    
    campaign = campaigns[campaign_id]
    call_sids = campaign.get("call_sids", {})
    
    for phone, call_sid in call_sids.items():
        # Don't hang up the connected call
        if campaign.get("connected_phone") != phone:
            hangup_call(call_sid)


# ============== API Endpoints ==============

@app.get("/")
async def serve_frontend():
    """Serve the main HTML page"""
    return FileResponse("static/index.html")


@app.post("/api/token")
async def get_twilio_token():
    """Generate Twilio Access Token (for token refresh)"""
    token, identity = generate_twilio_token()
    if not token:
        raise HTTPException(status_code=500, detail="Twilio credentials not configured.")
    return {"token": token, "identity": identity}


@app.post("/api/campaign")
async def create_campaign(campaign_data: CampaignCreate):
    """Create campaign, return token, AND start dialing immediately"""
    campaign_id = uuid.uuid4().hex[:8]

    token, identity = generate_twilio_token()
    if not token:
        raise HTTPException(status_code=500, detail="Twilio credentials not configured.")

    campaign = {
        "id": campaign_id,
        "contacts": campaign_data.contacts,
        "contact_status": {phone: "pending" for phone in campaign_data.contacts},
        "call_sids": {},
        "dispositions": {},  # phone -> {disposition, notes, timestamp}
        "call_order": [],  # Track order of calls for "least recently called"
        "status": "dialing",
        "agent_identity": identity,
        "connected_phone": None,
    }

    campaigns[campaign_id] = campaign

    # Start dialing only the FIRST contact (batch of 1)
    if campaign["contacts"]:
        first_phone = campaign["contacts"][0]
        campaign["contact_status"][first_phone] = "dialing"
        loop = asyncio.get_event_loop()
        loop.run_in_executor(executor, dial_contact, first_phone, campaign_id)

    return {
        "campaign": campaign,
        "token": token,
        "identity": identity
    }


class DispositionData(BaseModel):
    phone: str
    disposition: str
    notes: str = ""


@app.post("/api/campaign/{campaign_id}/disposition")
async def save_disposition(campaign_id: str, data: DispositionData):
    """Save disposition for a call"""
    if campaign_id not in campaigns:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    campaign = campaigns[campaign_id]
    
    from datetime import datetime
    campaign["dispositions"][data.phone] = {
        "disposition": data.disposition,
        "notes": data.notes,
        "timestamp": datetime.now().isoformat()
    }
    
    print(f"Disposition saved for {data.phone}: {data.disposition}")
    
    return {"status": "saved", "phone": data.phone, "disposition": data.disposition}


@app.post("/api/campaign/{campaign_id}/dial-next")
async def dial_next_contact(campaign_id: str):
    """Dial the next uncalled contact (least recently called order)"""
    if campaign_id not in campaigns:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    campaign = campaigns[campaign_id]
    
    # Reset status for next round
    campaign["status"] = "dialing"
    campaign["connected_phone"] = None
    
    # Find contacts that haven't been called recently or are pending
    # Priority: pending contacts first, then by call order
    called_phones = set(campaign.get("call_order", []))
    
    next_phone = None
    
    # First, try pending contacts (never called)
    for phone in campaign["contacts"]:
        if phone not in called_phones:
            next_phone = phone
            break
    
    # If all have been called, pick the least recently called
    if not next_phone and campaign.get("call_order"):
        # Get the oldest called one that's not currently in-progress
        for phone in campaign["call_order"]:
            status = campaign["contact_status"].get(phone, "pending")
            if status not in ["in-progress", "ringing", "dialing", "initiated"]:
                next_phone = phone
                break
    
    if next_phone:
        # Dial this contact
        campaign["contact_status"][next_phone] = "dialing"
        loop = asyncio.get_event_loop()
        loop.run_in_executor(executor, dial_contact, next_phone, campaign_id)
        
        return {"status": "dialing", "phone": next_phone}
    else:
        return {"status": "no_more_contacts", "phone": None}


@app.post("/api/campaign/{campaign_id}/end")
async def end_campaign(campaign_id: str):
    """End campaign and hang up all calls"""
    if campaign_id not in campaigns:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    campaign = campaigns[campaign_id]
    campaign["status"] = "ended"
    
    # Hang up all calls in a thread
    loop = asyncio.get_event_loop()
    loop.run_in_executor(executor, hangup_all_calls, campaign_id)
    
    # Broadcast to WebSocket clients
    await broadcast_to_campaign(campaign_id, {
        "type": "campaign_ended",
        "campaign_id": campaign_id
    })
    
    return {"status": "ended"}


@app.get("/api/campaign/{campaign_id}")
async def get_campaign(campaign_id: str):
    """Get campaign details"""
    if campaign_id not in campaigns:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaigns[campaign_id]


# ============== Twilio Voice Webhooks ==============

@app.post("/api/voice/customer-join")
async def voice_customer_join(campaign_id: str = None, phone: str = None):
    """TwiML endpoint for customer joining the conference when they pick up"""
    response = VoiceResponse()
    
    # Normalize phone number
    if phone:
        phone = phone.strip()
        if not phone.startswith('+'):
            phone = '+' + phone

    # Check if someone already connected - if so, hang up this call
    if campaign_id and campaign_id in campaigns:
        campaign = campaigns[campaign_id]
        if campaign.get("connected_phone") and campaign.get("connected_phone") != phone:
            response.say("Sorry, the agent is already on another call. Goodbye.", voice="alice")
            response.hangup()
            return Response(content=str(response), media_type="application/xml")
        
        # Mark this phone as the connected one
        campaign["connected_phone"] = phone
        campaign["status"] = "connected"
        campaign["contact_status"][phone] = "in-progress"
        
        # Hang up other calls
        loop = asyncio.get_event_loop()
        loop.run_in_executor(executor, hangup_all_calls, campaign_id)
        
        # Broadcast via WebSocket
        asyncio.create_task(broadcast_to_campaign(campaign_id, {
            "type": "customer_connected",
            "phone": phone,
            "campaign": campaign
        }))

    dial = Dial()
    dial.conference(
        "SalesDialerConference",
        start_conference_on_enter=True,
        end_conference_on_exit=False,
        beep="onEnter",
    )
    response.append(dial)

    return Response(content=str(response), media_type="application/xml")


@app.post("/api/voice/status")
async def voice_status(request: Request, campaign_id: str = None, phone: str = None):
    """Webhook to receive call status updates"""
    form_data = await request.form()
    call_status = form_data.get("CallStatus", "unknown")
    call_sid = form_data.get("CallSid", "")
    
    # Normalize phone number (handle URL encoding issues with +)
    if phone:
        phone = phone.strip()
        if not phone.startswith('+'):
            phone = '+' + phone

    print(f"Call status for {phone}: {call_status} (SID: {call_sid})")

    if campaign_id and campaign_id in campaigns and phone:
        campaign = campaigns[campaign_id]
        
        # Update status if phone exists in campaign
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
            if call_sid and "call_sids" in campaign:
                campaign["call_sids"][phone] = call_sid
            
            # Check if this was the connected call and it ended
            was_connected = previous_status == "in-progress" or campaign.get("connected_phone") == phone
            call_ended = call_status in ["completed", "busy", "no-answer", "failed", "canceled"]
            call_failed_without_connecting = call_status in ["busy", "no-answer", "failed", "canceled"] and previous_status != "in-progress"
            
            if was_connected and call_ended and previous_status == "in-progress":
                # The connected customer's call ended - show disposition modal
                campaign["connected_phone"] = None
                campaign["status"] = "waiting"
                
                await broadcast_to_campaign(campaign_id, {
                    "type": "call_ended",
                    "phone": phone,
                    "status": call_status,
                    "contact_status": campaign["contact_status"]
                })
            elif call_failed_without_connecting:
                # Call failed without connecting - auto-dial next contact
                await broadcast_to_campaign(campaign_id, {
                    "type": "status_update",
                    "phone": phone,
                    "status": call_status,
                    "contact_status": campaign["contact_status"]
                })
                
                # Auto-dial next contact after a short delay
                await broadcast_to_campaign(campaign_id, {
                    "type": "auto_dial_next",
                    "reason": f"{phone} - {call_status}"
                })
            else:
                # Regular status update
                await broadcast_to_campaign(campaign_id, {
                    "type": "status_update",
                    "phone": phone,
                    "status": call_status,
                    "contact_status": campaign["contact_status"]
                })
        else:
            print(f"Phone {phone} not found in campaign contacts: {list(campaign['contact_status'].keys())}")

    return {"status": "ok"}


@app.post("/api/voice/dial")
async def voice_dial(request: Request):
    """TwiML endpoint for outbound dialing (used by TwiML App)"""
    form_data = await request.form()
    to = form_data.get("To", "")

    response = VoiceResponse()

    if to.startswith("conference:"):
        conference_name = to.replace("conference:", "")
        dial = Dial()
        dial.conference(
            conference_name,
            start_conference_on_enter=True,
            end_conference_on_exit=True,
            beep="onEnter",
            wait_url="http://twimlets.com/holdmusic?Bucket=com.twilio.music.soft-rock",
        )
        response.append(dial)
    elif to:
        dial = Dial(caller_id=TWILIO_PHONE_NUMBER)
        dial.number(to)
        response.append(dial)
    else:
        response.say("No destination specified")

    return Response(content=str(response), media_type="application/xml")


# ============== Static Files ==============

@app.get("/static/{file_path:path}")
async def serve_static(file_path: str):
    """Serve static files with no-cache headers"""
    full_path = f"static/{file_path}"
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="File not found")

    mime_type, _ = mimetypes.guess_type(full_path)
    return StarletteFileResponse(
        full_path,
        media_type=mime_type,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
