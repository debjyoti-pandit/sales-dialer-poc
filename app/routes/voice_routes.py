"""Twilio Voice webhook routes"""
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from twilio.twiml.voice_response import VoiceResponse, Dial, Enqueue
from app.config import TWILIO_PHONE_NUMBER, CONFERENCE_NAME, QUEUE_HOLD_MUSIC_URL, BASE_URL
from app.services.campaign_service import campaign_service
from app.services.call_queue_service import call_queue_service
from app.services.twilio_service import twilio_service
from app.websocket.manager import broadcast_to_campaign
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
async def voice_customer_queue(request: Request, campaign_id: str = None, phone: str = None):
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
    
    print(f"Call answered: {phone} (SID: {call_sid}) - Enqueuing in Twilio queue")
    
    # Add call to our internal queue tracking
    if campaign_id and phone and call_sid:
        call_queue_service.add_to_queue(campaign_id, call_sid, phone)
        
        # Update campaign status
        campaign_service.update_call_status(campaign_id, phone, "queued", call_sid)
        
        # Broadcast queue update
        await broadcast_to_campaign(campaign_id, {
            "type": "call_queued",
            "phone": phone,
            "call_sid": call_sid
        })
    
    # Use Twilio's <Enqueue> verb to put call in queue
    # This keeps the call alive automatically with hold music
    # We'll dequeue it via REST API when AMD completes
    queue_name = f"campaign_{campaign_id}" if campaign_id else "default_queue"

    # URL encode parameters for action URL
    encoded_phone = quote(phone, safe='') if phone else ''
    encoded_campaign = quote(campaign_id, safe='') if campaign_id else ''

    # Enqueue the call with hold music - Twilio handles the queue automatically
    enqueue = Enqueue(
        wait_url=QUEUE_HOLD_MUSIC_URL,
        wait_url_method="GET",
        action=f"{BASE_URL}/api/voice/queue-action?campaign_id={encoded_campaign}&phone={encoded_phone}",
        method="POST"
    )
    enqueue.append(queue_name)  # Queue name as text content
    response.append(enqueue)
    
    # Return TwiML with proper Content-Type header
    return create_twiml_response(response)


@router.post("/queue-wait-music")
async def queue_wait_music(_request: Request, _campaign_id: str = None, _phone: str = None):
    """TwiML endpoint for hold music while call is in queue"""
    response = VoiceResponse()
    # Play hold music continuously while in queue
    response.play(QUEUE_HOLD_MUSIC_URL, loop=0)  # Loop indefinitely
    return create_twiml_response(response)


@router.post("/queue-action")
async def queue_action(request: Request):
    """TwiML endpoint called when call leaves queue (dequeued or other action)"""
    form_data = await request.form()
    dequeue_reason = form_data.get("DequeueReason", "unknown")
    queue_time = form_data.get("QueueTime", "0")
    call_sid = form_data.get("CallSid", "")
    
    print(f"Call {call_sid} left queue. Reason: {dequeue_reason}, Queue time: {queue_time}s")
    
    # This endpoint is called when call leaves queue
    # If dequeued successfully, it will be redirected to conference
    # If hung up or other reason, we handle it here
    response = VoiceResponse()
    
    if dequeue_reason == "dequeued":
        # Call was dequeued - it should be redirected to conference already
        # But if not, redirect to conference
        response.redirect(
            f"{BASE_URL}/api/voice/customer-join-conference?conference={CONFERENCE_NAME}",
            method="POST"
        )
    else:
        # Call left queue for other reason (hung up, etc.)
        response.hangup()
    
    return create_twiml_response(response)


@router.post("/amd-status")
async def voice_amd_status(request: Request, campaign_id: str = None, phone: str = None):
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

    detection_result = {
        "call_sid": call_sid,
        "AnsweredBy": answered_by,
        "MachineDetectionStatus": machine_detection_status,
        "Timestamp": form_data.get("Timestamp", "")
    }

    print(f"AMD result for {phone} (SID: {call_sid}): {answered_by} - {machine_detection_status}")

    # Process detection result and move to conference if appropriate
    if campaign_id and phone and call_sid:
        await call_queue_service.process_detection_result(
            campaign_id, call_sid, phone, detection_result
        )

    # Return JSON response with proper Content-Type
    return JSONResponse(content={"status": "ok"})


@router.post("/queue-action")
async def voice_queue_action(request: Request, campaign_id: str = None, phone: str = None):
    """Webhook called when call leaves queue (via dequeue or other action)"""
    form_data = await request.form()
    call_sid = form_data.get("CallSid", "")
    dequeue_reason = form_data.get("QueueResult", "unknown")

    print(f"Queue action for {phone} (SID: {call_sid}): {dequeue_reason}")

    if campaign_id and phone and call_sid:
        # Update campaign status
        campaign_service.update_call_status(campaign_id, phone, "dequeued", call_sid)

        # Remove from our internal queue
        call_queue_service.remove_from_queue(campaign_id, call_sid)

        # Broadcast dequeue event
        await broadcast_to_campaign(campaign_id, {
            "type": "call_dequeued",
            "phone": phone,
            "call_sid": call_sid,
            "reason": dequeue_reason
        })

    # Return empty TwiML response
    response = VoiceResponse()
    return create_twiml_response(response)


@router.post("/customer-join-conference")
async def voice_customer_join_conference(conference: str = None):
    """TwiML endpoint for customer joining the conference after detection"""
    response = VoiceResponse()
    
    conference_name = conference or CONFERENCE_NAME
    
    dial = Dial()
    dial.conference(
        conference_name,
        start_conference_on_enter=True,
        end_conference_on_exit=False,
        beep="onEnter",
    )
    response.append(dial)
    
    # Return TwiML with proper Content-Type header
    return create_twiml_response(response)


@router.post("/status")
async def voice_status(request: Request, campaign_id: str = None, phone: str = None):
    """Webhook to receive call status updates"""
    form_data = await request.form()
    call_status = form_data.get("CallStatus", "unknown")
    call_sid = form_data.get("CallSid", "")
    
    # Normalize phone number
    if phone:
        phone = phone.strip()
        if not phone.startswith('+'):
            phone = '+' + phone
    
    print(f"Call status for {phone}: {call_status} (SID: {call_sid})")
    
    if campaign_id and phone:
        campaign_service.update_call_status(campaign_id, phone, call_status, call_sid)
        
        campaign = campaign_service.get_campaign(campaign_id)
        if campaign:
            previous_status = campaign["contact_status"].get(phone, "pending")
            
            # Check if this was the connected call and it ended
            was_connected = previous_status == "in-progress" or campaign.get("connected_phone") == phone
            call_ended = call_status in ["completed", "busy", "no-answer", "failed", "canceled"]
            call_failed_without_connecting = call_status in ["busy", "no-answer", "failed", "canceled"] and previous_status not in ["in-progress", "queued"]
            
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
    
    # Return JSON response with proper Content-Type
    return JSONResponse(content={"status": "ok"})


@router.post("/dequeue-next/{campaign_id}")
async def dequeue_next_call(campaign_id: str):
    """Dequeue the next call from the campaign queue and return TwiML to connect it"""
    # Check if there are calls ready to connect
    campaign = campaign_service.get_campaign(campaign_id)
    if not campaign:
        response = VoiceResponse()
        response.say("Campaign not found")
        return create_twiml_response(response)

    pending_phone = campaign.get("pending_connection")
    if not pending_phone:
        response = VoiceResponse()
        response.say("No calls ready to connect")
        return create_twiml_response(response)

    # Get the call SID for the pending connection
    call_sid = campaign.get("call_sids", {}).get(pending_phone)
    if not call_sid:
        response = VoiceResponse()
        response.say("Call not found")
        return create_twiml_response(response)

    # Dequeue and connect to conference
    queue_name = f"campaign_{campaign_id}"
    encoded_conf = quote(CONFERENCE_NAME, safe="")
    dequeue_url = f"{BASE_URL}/api/voice/customer-join-conference?conference={encoded_conf}"

    success = twilio_service.dequeue_call(queue_name, call_sid, dequeue_url)
    if success:
        # Update campaign state
        campaign["connected_phone"] = pending_phone
        campaign["status"] = "connected"
        campaign["contact_status"][pending_phone] = "in-progress"
        campaign.pop("pending_connection", None)  # Clear pending

        # Remove from queue
        call_queue_service.remove_from_queue(campaign_id, call_sid)

        # Broadcast update
        await broadcast_to_campaign(campaign_id, {
            "type": "customer_connected",
            "phone": pending_phone,
            "campaign": campaign
        })

        # Return TwiML to connect the agent to the conference
        response = VoiceResponse()
        dial = Dial()
        dial.conference(
            CONFERENCE_NAME,
            start_conference_on_enter=True,
            end_conference_on_exit=False,
            beep="onEnter",
        )
        response.append(dial)
        return create_twiml_response(response)
    else:
        response = VoiceResponse()
        response.say("Failed to connect call")
        return create_twiml_response(response)


@router.post("/dial")
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
            wait_url=QUEUE_HOLD_MUSIC_URL,
        )
        response.append(dial)
    elif to.startswith("queue:"):
        # Dequeue from queue - this connects the next call in queue to the conference
        queue_name = to.replace("queue:", "")
        dial = Dial()
        dial.queue(queue_name)  # Dequeue and connect to current call
        response.append(dial)
    elif to:
        dial = Dial(caller_id=TWILIO_PHONE_NUMBER)
        dial.number(to)
        response.append(dial)
    else:
        response.say("No destination specified")

    # Return TwiML with proper Content-Type header
    return create_twiml_response(response)

