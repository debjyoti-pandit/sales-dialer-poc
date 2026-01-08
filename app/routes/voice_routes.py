"""Twilio Voice webhook routes"""
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from twilio.twiml.voice_response import VoiceResponse, Dial, Enqueue
from app.config import TWILIO_PHONE_NUMBER, QUEUE_HOLD_MUSIC_URL, BASE_URL
from app.services.campaign_service import campaign_service
from app.services.call_queue_service import call_queue_service
from app.services.twilio_service import twilio_service
from app.websocket.manager import broadcast_to_agent
from app.storage import agents
from app.logger import logger
from urllib.parse import quote

router = APIRouter(prefix="/api/voice", tags=["voice"])


@router.get("/test")
async def test_twiml():
    """Test endpoint to verify TwiML response format"""
    response = VoiceResponse()
    response.say("This is a test TwiML response")
    return create_twiml_response(response)


def create_twiml_response(voice_response: VoiceResponse) -> Response:
    """Helper function to create properly formatted TwiML Response"""
    twiml_content = str(voice_response)
    # Ensure XML declaration is present
    if not twiml_content.startswith('<?xml'):
        twiml_content = '<?xml version="1.0" encoding="UTF-8"?>' + twiml_content
    # Encode as bytes
    twiml_bytes = twiml_content.encode('utf-8')
    return Response(
        content=twiml_bytes,
        status_code=200,
        media_type="application/xml",
        headers={
            "Content-Type": "application/xml; charset=utf-8",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )


@router.post("/customer-queue")
async def voice_customer_queue(request: Request, campaign_id: str = None, phone: str = None, agent_name: str = None):
    """TwiML endpoint for customer joining the Twilio queue when they pick up"""
    response = VoiceResponse()
    
    # Normalize phone number
    if phone:
        phone = phone.strip()
        if not phone.startswith('+'):
            phone = '+' + phone
    
    # Get call SID from request
    form_data = await request.form()
    call_sid = form_data.get("CallSid", "")
    
    # Get agent_name from campaign if not provided
    if not agent_name and campaign_id:
        campaign = campaign_service.get_campaign(campaign_id)
        if campaign:
            agent_name = campaign.get("agent_name")
    
    logger.call(phone, f"Call answered - enqueuing for agent {agent_name}")
    
    # Add call to our internal queue tracking
    if agent_name and phone and call_sid:
        call_queue_service.add_to_queue(agent_name, call_sid, phone)
        
        # Update campaign status
        if campaign_id:
            campaign_service.update_call_status(campaign_id, phone, "queued", call_sid)
        
        # Broadcast queue update
        await broadcast_to_agent(agent_name, {
            "type": "call_queued",
            "phone": phone,
            "call_sid": call_sid
        })
    
    # Use Twilio's <Enqueue> verb to put call in agent's queue
    # Queue name is based on agent_name
    queue_name = f"agent_{agent_name}" if agent_name else "default_queue"

    # URL encode parameters for action URL
    encoded_phone = quote(phone, safe='') if phone else ''
    encoded_campaign = quote(campaign_id, safe='') if campaign_id else ''
    encoded_agent = quote(agent_name, safe='') if agent_name else ''

    # Enqueue the call with hold music - Twilio handles the queue automatically
    enqueue = Enqueue(
        wait_url=QUEUE_HOLD_MUSIC_URL,
        wait_url_method="GET",
        action=f"{BASE_URL}/api/voice/queue-action?campaign_id={encoded_campaign}&phone={encoded_phone}&agent_name={encoded_agent}",
        method="POST"
    )
    enqueue.append(queue_name)  # Queue name as text content
    response.append(enqueue)
    
    # Return TwiML with proper Content-Type header
    return create_twiml_response(response)


@router.post("/queue-wait-music")
async def queue_wait_music(_request: Request, _campaign_id: str = None, _phone: str = None, _agent_name: str = None):
    """TwiML endpoint for hold music while call is in queue"""
    response = VoiceResponse()
    # Play hold music continuously while in queue
    response.play(QUEUE_HOLD_MUSIC_URL, loop=0)  # Loop indefinitely
    return create_twiml_response(response)


@router.post("/queue-action")
async def queue_action(request: Request, campaign_id: str = None, phone: str = None, agent_name: str = None):
    """TwiML endpoint called when call leaves queue (dequeued or other action)"""
    form_data = await request.form()
    dequeue_reason = form_data.get("DequeueReason", "unknown")
    queue_time = form_data.get("QueueTime", "0")
    call_sid = form_data.get("CallSid", "")
    
    logger.info(f"Call {call_sid} left queue. Reason: {dequeue_reason}, Queue time: {queue_time}s")
    
    # Get agent_name from campaign if not provided
    if not agent_name and campaign_id:
        campaign = campaign_service.get_campaign(campaign_id)
        if campaign:
            agent_name = campaign.get("agent_name")
    
    if agent_name and phone and call_sid:
        # Update campaign status
        if campaign_id:
            campaign_service.update_call_status(campaign_id, phone, "dequeued", call_sid)

        # Remove from our internal queue
        call_queue_service.remove_from_queue(agent_name, call_sid)

        # Broadcast dequeue event
        await broadcast_to_agent(agent_name, {
            "type": "call_dequeued",
            "phone": phone,
            "call_sid": call_sid,
            "reason": dequeue_reason
        })
    
    # Return empty TwiML response
    response = VoiceResponse()
    return create_twiml_response(response)


@router.post("/amd-status")
async def voice_amd_status(request: Request, campaign_id: str = None, phone: str = None, agent_name: str = None):
    """Webhook to receive async AMD (Answering Machine Detection) results"""
    form_data = await request.form()
    call_sid = form_data.get("CallSid", "")
    answered_by = form_data.get("AnsweredBy", "unknown")
    machine_detection_status = form_data.get("MachineDetectionStatus", "unknown")

    # Normalize phone number
    if phone:
        phone = phone.strip()
        if not phone.startswith('+'):
            phone = '+' + phone

    # Get agent_name from campaign if not provided
    if not agent_name and campaign_id:
        campaign = campaign_service.get_campaign(campaign_id)
        if campaign:
            agent_name = campaign.get("agent_name")

    detection_result = {
        "call_sid": call_sid,
        "AnsweredBy": answered_by,
        "MachineDetectionStatus": machine_detection_status,
        "Timestamp": form_data.get("Timestamp", "")
    }

    logger.call(phone, f"AMD result: {answered_by} - {machine_detection_status}")

    # Broadcast AMD result to frontend for logging only
    if campaign_id and agent_name:
        await broadcast_to_agent(agent_name, {
            "type": "amd_result",
            "phone": phone,
            "call_sid": call_sid,
            "answered_by": answered_by,
            "machine_detection_status": machine_detection_status,
            "detection_result": detection_result
        })

    # Return JSON response with proper Content-Type
    return JSONResponse(content={"status": "ok"})


@router.post("/status")
async def voice_status(request: Request, campaign_id: str = None, phone: str = None, agent_name: str = None):
    """Webhook to receive call status updates"""
    form_data = await request.form()
    call_status = form_data.get("CallStatus", "unknown")
    call_sid = form_data.get("CallSid", "")
    
    # Normalize phone number
    if phone:
        phone = phone.strip()
        if not phone.startswith('+'):
            phone = '+' + phone
    
    # Get agent_name from campaign if not provided
    if not agent_name and campaign_id:
        campaign = campaign_service.get_campaign(campaign_id)
        if campaign:
            agent_name = campaign.get("agent_name")
    
    logger.call(phone, f"Status: {call_status}")
    
    if campaign_id and phone and agent_name:
        campaign_service.update_call_status(campaign_id, phone, call_status, call_sid)
        
        campaign = campaign_service.get_campaign(campaign_id)
        if campaign:
            previous_status = campaign["contact_status"].get(phone, "pending")

            # Note: Call is already put in queue by the initial /contact-to-queue endpoint when answered

            # Check if this was the connected call and it ended
            was_connected = previous_status in ["in-progress", "queued", "connected"] or campaign.get("connected_phone") == phone
            call_ended = call_status in ["completed", "busy", "no-answer", "failed", "canceled"]
            call_failed_without_connecting = call_status in ["busy", "no-answer", "failed", "canceled"] and previous_status not in ["in-progress", "queued"]

            if was_connected and call_ended:
                # The customer's call ended - show disposition modal
                campaign["connected_phone"] = None
                campaign["status"] = "waiting"

                # Mark the call as completed in contact status
                campaign["contact_status"][phone] = call_status

                await broadcast_to_agent(agent_name, {
                    "type": "call_ended",
                    "phone": phone,
                    "status": call_status,
                    "contact_status": campaign["contact_status"]
                })
            elif call_failed_without_connecting:
                # Call failed without connecting - update status and auto-dial next batch
                campaign["contact_status"][phone] = call_status
                await broadcast_to_agent(agent_name, {
                    "type": "status_update",
                    "phone": phone,
                    "status": call_status,
                    "contact_status": campaign["contact_status"]
                })

                # Auto-dial next batch after a short delay
                await broadcast_to_agent(agent_name, {
                    "type": "auto_dial_next",
                    "reason": f"{phone} - {call_status}"
                })
            else:
                # Regular status update - update contact status
                campaign["contact_status"][phone] = call_status
                await broadcast_to_agent(agent_name, {
                    "type": "status_update",
                    "phone": phone,
                    "status": call_status,
                    "contact_status": campaign["contact_status"]
                })
    
    # Return JSON response with proper Content-Type
    return JSONResponse(content={"status": "ok"})


@router.post("/contact-to-queue")
async def contact_to_queue(request: Request, campaign_id: str = None, phone: str = None, queue_name: str = None, agent_name: str = None):
    """TwiML endpoint for contact to join campaign queue after answering"""
    response = VoiceResponse()

    # Normalize phone number
    if phone:
        phone = phone.strip()
        if not phone.startswith('+'):
            phone = '+' + phone

    # Get call SID from request
    form_data = await request.form()
    call_sid = form_data.get("CallSid", "")

    logger.call(phone, f"Contact joining campaign queue {queue_name}")

    # Update campaign status
    if campaign_id and phone and call_sid:
        campaign_service.update_call_status(campaign_id, phone, "connected", call_sid)  # Set to connected since bridging happens immediately

        # Set as connected phone since customer will immediately connect to waiting agent
        campaign = campaign_service.get_campaign(campaign_id)
        if campaign:
            campaign["connected_phone"] = phone

        # Broadcast connection update to agent
        campaign = campaign_service.get_campaign(campaign_id)
        await broadcast_to_agent(agent_name or "unknown", {
            "type": "customer_connected",
            "phone": phone,
            "call_sid": call_sid,
            "queue_name": queue_name,
            "campaign": {
                "contact_status": campaign.get("contact_status", {}) if campaign else {}
            }
        })

    # Connect customer to the campaign queue where agents are waiting
    if queue_name:
        dial = Dial()
        dial.queue(queue_name)  # Connect to queue to be answered by waiting agents
        response.append(dial)
    else:
        response.say("Queue not specified")

    return create_twiml_response(response)


@router.post("/trigger-dialing")
async def trigger_dialing(campaign_id: str = None, queue_name: str = None):
    """Webhook called when agent connects to queue - triggers contact dialing"""
    import asyncio

    if not campaign_id:
        return {"status": "error", "message": "No campaign_id provided"}

    # Get campaign
    campaign = campaign_service.get_campaign(campaign_id)
    if not campaign:
        return {"status": "error", "message": "Campaign not found"}

    logger.info(f"Agent connected to queue {queue_name} - campaign {campaign_id}, status: {campaign.get('status')}")

    # Only dial contacts if this is the initial agent connection (not a reconnection after disposition)
    if campaign.get("status") == "agent_in_queue":
        # Start dialing contacts asynchronously
        loop = asyncio.get_event_loop()
        def dial_contacts():
            contacts_to_dial = []
            for phone in campaign.get("contacts", []):
                if campaign["contact_status"].get(phone) == "pending":
                    contacts_to_dial.append(phone)

            logger.info(f"Dialing {len(contacts_to_dial)} pending contacts for campaign {campaign_id}")

            for phone in contacts_to_dial:
                campaign["contact_status"][phone] = "dialing"
                call_sid = twilio_service.dial_contact_to_queue(phone, campaign_id, queue_name, campaign.get("agent_name"))
                if call_sid:
                    campaign["call_sids"][phone] = call_sid
                    logger.call(phone, f"Dialing contact for campaign {campaign_id}")

        loop.run_in_executor(None, dial_contacts)
    else:
        logger.info(f"Agent reconnected to queue {queue_name} - waiting for manual dial command")

    # Return hold music TwiML
    response = VoiceResponse()
    response.play(QUEUE_HOLD_MUSIC_URL, loop=0)
    return create_twiml_response(response)


@router.post("/connect-agent")
async def connect_agent(request: Request, agent_identity: str = None, customer_call_sid: str = None):
    """TwiML endpoint to connect a customer call to an agent's device"""
    response = VoiceResponse()
    
    if not agent_identity:
        response.say("Agent identity not provided")
        return create_twiml_response(response)
    
    # Dial the agent's client (device)
    dial = Dial()
    dial.client(agent_identity)  # Dial the agent's Twilio client
    response.append(dial)
    
    logger.agent(agent_identity, f"Connecting call {customer_call_sid} to agent")
    
    return create_twiml_response(response)


@router.post("/dial")
async def voice_dial(request: Request):
    """TwiML endpoint for outbound dialing (used by TwiML App)"""
    form_data = await request.form()
    to = form_data.get("To", "")

    response = VoiceResponse()

    if to.startswith("queue:"):
        # Put agent in the campaign queue to wait for customers
        queue_name = to.replace("queue:", "")
        campaign_id = queue_name.replace("campaign_", "")

        # Trigger contact dialing when agent connects
        enqueue = Enqueue(
            wait_url=f"{BASE_URL}/api/voice/trigger-dialing?campaign_id={campaign_id}&queue_name={queue_name}",
            wait_url_method="POST"
        )
        enqueue.append(queue_name)  # Campaign-specific queue
        response.append(enqueue)
    elif to:
        dial = Dial(caller_id=TWILIO_PHONE_NUMBER)
        dial.number(to)
        response.append(dial)
    else:
        response.say("No destination specified")

    # Return TwiML with proper Content-Type header
    return create_twiml_response(response)
