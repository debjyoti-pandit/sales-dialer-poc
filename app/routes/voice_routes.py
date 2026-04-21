"""Twilio Voice webhook routes"""
# pylint: disable=import-error
import time
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from twilio.twiml.voice_response import VoiceResponse, Dial, Enqueue, Start
from typing import Any, cast
from app.config import TWILIO_PHONE_NUMBER, QUEUE_HOLD_MUSIC_URL, BASE_URL, TRANSCRIPTION_STREAM_WSS_URL
from app.services.campaign_service import campaign_service
from app.services.call_queue_service import call_queue_service
from app.services.twilio_service import twilio_service
from app.websocket.manager import broadcast_to_agent
from app.storage import agents
from app.logger import logger
from urllib.parse import quote
import re

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
    safe_agent_name = re.sub(r"[^A-Za-z0-9_]", "_", agent_name or "")
    queue_name = f"agent_{safe_agent_name}" if safe_agent_name else "default_queue"

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

    # Broadcast AMD result to frontend for visibility.
    if campaign_id and agent_name:
        await broadcast_to_agent(agent_name, {
            "type": "amd_result",
            "phone": phone,
            "call_sid": call_sid,
            "answered_by": answered_by,
            "machine_detection_status": machine_detection_status,
            "detection_result": detection_result
        })

    # Just log Twilio AMD results - we ignore them and let the transcription service handle AMD
    logger.call(phone, f"Twilio AMD result (ignored): {answered_by} - {machine_detection_status}")

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
        campaign = campaign_service.get_campaign(campaign_id)
        if campaign:
            previous_status = campaign.get("contact_status", {}).get(phone, "pending")

            # If backend already marked this as "answered but dropped", do not overwrite
            # it with Twilio's later terminal statuses like "completed".
            if previous_status in ("answered_disconnected_by_system", "voicemail", "dropped_by_system"):
                return JSONResponse(content={"status": "ok"})

        campaign_service.update_call_status(campaign_id, phone, call_status, call_sid)

        campaign = campaign_service.get_campaign(campaign_id)
        if campaign:
            previous_status = campaign.get("contact_status", {}).get(phone, "pending")

            # Note: Call is already put in queue by the initial /contact-to-queue endpoint when answered

            # Check if this was the connected call and it ended
            was_connected = previous_status in ["in-progress", "queued", "connected"] or campaign.get("connected_phone") == phone
            call_ended = call_status in ["completed", "busy", "no-answer", "failed", "canceled"]
            # Best-effort agent busy tracking (in case frontend call-state isn't sent)
            agent = agents.get(agent_name)
            if agent:
                if call_status == "in-progress":
                    agent["in_call"] = True
                    agent["connected_phone"] = phone
                if call_ended:
                    if agent.get("connected_phone") == phone:
                        agent.pop("connected_phone", None)
                        agent["in_call"] = False
                    # Clear reservation if this was the reserved phone
                    if agent.get("reserved_phone") == phone:
                        agent.pop("reserved_phone", None)
                        agent.pop("call_slot_reserved", None)

            if was_connected and call_ended:
                # The customer's call ended - show disposition modal
                campaign["connected_phone"] = None
                campaign.pop("call_slot_reserved", None)
                campaign.pop("reserved_phone", None)
                campaign["status"] = "waiting"

                # Mark the call as completed in contact status
                campaign["contact_status"][phone] = call_status

                await broadcast_to_agent(agent_name, {
                    "type": "call_ended",
                    "phone": phone,
                    "status": call_status,
                    "contact_status": campaign["contact_status"]
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
    """TwiML endpoint for contact to join agent queue after answering"""
    response = VoiceResponse()

    # Normalize phone number
    if phone:
        phone = phone.strip()
        if not phone.startswith('+'):
            phone = '+' + phone

    # Get call SID from request
    form_data = await request.form()
    call_sid = form_data.get("CallSid", "")

    logger.call(phone, f"Contact joining agent queue {queue_name}")

    # Resolve agent_name from campaign if not provided
    campaign = campaign_service.get_campaign(campaign_id) if campaign_id else None
    if not agent_name and campaign:
        agent_name = campaign.get("agent_name")

    # AMD gating:
    # - customer stays on a HOLD queue first (transcription runs)
    # - backend connects to agent queue only after AMD says HUMAN, or manual connect, or 10s timeout
    if campaign and agent_name and phone and call_sid:
        assert isinstance(campaign, dict)
        contact_status = campaign.setdefault("contact_status", {})
        call_sids = campaign.setdefault("call_sids", {})
        contact_status[phone] = "amd_listening"
        call_sids[phone] = call_sid

        # Start timers (3s -> amd_unknown, 10s -> auto connect topmost)
        await call_queue_service.start_amd_gate(
            campaign_id=campaign_id,
            agent_name=agent_name,
            phone=phone,
            call_sid=call_sid,
            answered_at_ms=int(time.time() * 1000),
        )

    # Start transcription stream immediately (so AMD can run before connecting agent)
    if TRANSCRIPTION_STREAM_WSS_URL:
        start = Start()
        stream = start.stream(url=TRANSCRIPTION_STREAM_WSS_URL, track="both_tracks")
        stream.parameter(name="agent_name", value=agent_name or "")
        stream.parameter(name="phone", value=phone or "")
        stream.parameter(name="enableJcIqMirror", value=True)
        response.append(start)
        logger.info(f"Starting media stream to {TRANSCRIPTION_STREAM_WSS_URL}")

    # IMPORTANT: Do NOT play hold music while AMD runs.
    # Keep the customer in silence while we run AMD.
    #
    # Fail-safe: after 10s, Twilio will hit our /amd-timeout endpoint via <Redirect>.
    # If AMD decides earlier (human) or agent manually connects, backend will update the
    # live call's URL and this pause path will be abandoned.
    response.pause(length=10)
    encoded_phone = quote(phone, safe='') if phone else ''
    encoded_campaign = quote(campaign_id, safe='') if campaign_id else ''
    encoded_agent = quote(agent_name, safe='') if agent_name else ''
    encoded_queue = quote(queue_name or "", safe='')
    timeout_url = f"{BASE_URL}/api/voice/amd-timeout?campaign_id={encoded_campaign}&phone={encoded_phone}&agent_name={encoded_agent}&queue_name={encoded_queue}"
    response.redirect(timeout_url, method="POST")

    return create_twiml_response(response)


@router.post("/amd-bridge")
async def amd_bridge(request: Request, campaign_id: str = None, phone: str = None, queue_name: str = None, agent_name: str = None, reason: str = None):
    """
    TwiML endpoint used when we DEQUEUE a customer from the AMD hold queue
    into the agent queue.
    """
    _ = request
    response = VoiceResponse()

    # Normalize phone number
    if phone:
        phone = phone.strip()
        if not phone.startswith('+'):
            phone = '+' + phone

    campaign = campaign_service.get_campaign(campaign_id) if campaign_id else None
    if isinstance(campaign, dict) and agent_name and phone:
        # Help static analyzers: we've guarded it's a mutable dict.
        campaign_dict = cast(dict[str, Any], campaign)

        # Check if already connected to prevent duplicate processing
        if campaign_dict.get("connected_phone") == phone:
            logger.warning(f"Call {phone} already connected in amd_bridge, skipping duplicate processing (reason: {reason})")
            # Still return valid TwiML to connect to queue
            if queue_name:
                dial = Dial()
                dial.queue(queue_name)
                response.append(dial)
            return create_twiml_response(response)

        # Mark as connected now
        # pylint: disable=unsupported-assignment-operation
        campaign_dict.setdefault("contact_status", {})[phone] = "in-progress"
        campaign_dict["connected_phone"] = phone
        campaign_dict["status"] = "connected"
        # pylint: enable=unsupported-assignment-operation

        await broadcast_to_agent(agent_name, {
            "type": "customer_connected",
            "phone": phone,
            "call_sid": (campaign_dict.get("call_sids", {}) or {}).get(phone, ""),
            "queue_name": queue_name,
            "reason": reason or "",
            "campaign": {"contact_status": campaign_dict.get("contact_status", {})},
        })

    # IMPORTANT: Redirecting the call can stop an existing Media Stream.
    # Restart transcription streaming here so transcript continues after connect.
    if TRANSCRIPTION_STREAM_WSS_URL:
        start = Start()
        stream = start.stream(url=TRANSCRIPTION_STREAM_WSS_URL, track="both_tracks")
        stream.parameter(name="agent_name", value=agent_name or "")
        stream.parameter(name="phone", value=phone or "")
        # Best-effort: include call_sid as a parameter (transcription service may ignore it).
        if campaign and isinstance(campaign, dict):
            stream.parameter(name="call_sid", value=(campaign.get("call_sids", {}) or {}).get(phone, "") or "")
        response.append(start)

    if queue_name:
        dial = Dial()
        dial.queue(queue_name)
        response.append(dial)
    else:
        response.say("Queue not specified")
    return create_twiml_response(response)


@router.post("/amd-timeout")
async def amd_timeout(
    request: Request,
    campaign_id: str = None,
    phone: str = None,
    queue_name: str = None,
    agent_name: str = None,
):
    """
    TwiML endpoint hit after 10 seconds (Pause+Redirect) while AMD is running.

    - If a call is already connected, hang up this call.
    - Otherwise, connect the topmost (earliest-answered) pending call and hang up the rest.
    """
    response = VoiceResponse()
    form_data = await request.form()
    call_sid = form_data.get("CallSid", "")

    # Normalize phone number
    if phone:
        phone = phone.strip()
        if not phone.startswith('+'):
            phone = '+' + phone

    campaign = campaign_service.get_campaign(campaign_id) if campaign_id else None
    if not isinstance(campaign, dict):
        response.hangup()
        return create_twiml_response(response)
    # Help static analyzers: we've guarded it's a mutable dict.
    campaign_dict = cast(dict[str, Any], campaign)

    # Resolve agent_name/queue_name if missing
    if not agent_name:
        agent_name = campaign_dict.get("agent_name")
    if not queue_name:
        queue_name = campaign_dict.get("queue_name")

    if not agent_name or not phone or not queue_name:
        response.hangup()
        return create_twiml_response(response)

    # If already connected, this call is not needed.
    if campaign_dict.get("connected_phone"):
        if campaign_dict.get("connected_phone") != phone:
            campaign_dict.setdefault("contact_status", {})[phone] = "dropped_by_system"
        response.hangup()
        return create_twiml_response(response)

    cs = campaign_dict.get("contact_status", {}) or {}
    answered_at = campaign_dict.get("amd_answered_at_ms", {}) or {}
    call_sids = campaign_dict.get("call_sids", {}) or {}

    pending = [p for p, st in cs.items() if st in ("amd_unknown", "amd_listening")]
    if not pending:
        response.hangup()
        return create_twiml_response(response)

    pending.sort(key=lambda p: int(answered_at.get(p, 0) or 0))
    selected_phone = pending[0]

    # If this callback is for a non-selected phone, drop it.
    if selected_phone != phone:
        cs[phone] = "dropped_by_system"
        response.hangup()
        return create_twiml_response(response)

    # Selected: drop all other pending calls
    for p, sid in list(call_sids.items()):
        if p == selected_phone:
            continue
        st = (campaign_dict.get("contact_status", {}) or {}).get(p)
        if st in ("dialing", "ringing", "amd_listening", "amd_unknown", "queued"):
            twilio_service.hangup_call(sid)
            campaign_dict.setdefault("contact_status", {})[p] = "dropped_by_system"

    # Mark connected and notify UI
    # pylint: disable=unsupported-assignment-operation
    campaign_dict.setdefault("contact_status", {})[selected_phone] = "in-progress"
    campaign_dict["connected_phone"] = selected_phone
    campaign_dict["status"] = "connected"
    # pylint: enable=unsupported-assignment-operation

    await broadcast_to_agent(agent_name, {
        "type": "customer_connected",
        "phone": selected_phone,
        "call_sid": call_sids.get(selected_phone, "") or call_sid,
        "queue_name": queue_name,
        "reason": "twiml_10s_timeout",
        "campaign": {"contact_status": campaign_dict.get("contact_status", {})},
    })

    # Restart transcription streaming (redirect can stop previous stream)
    if TRANSCRIPTION_STREAM_WSS_URL:
        start = Start()
        stream = start.stream(url=TRANSCRIPTION_STREAM_WSS_URL, track="both_tracks")
        stream.parameter(name="agent_name", value=agent_name or "")
        stream.parameter(name="phone", value=selected_phone or "")
        stream.parameter(name="call_sid", value=call_sids.get(selected_phone, "") or call_sid or "")
        response.append(start)

    dial = Dial()
    dial.queue(queue_name)
    response.append(dial)
    return create_twiml_response(response)


@router.post("/trigger-dialing")
async def trigger_dialing(campaign_id: str = None, queue_name: str = None, agent_name: str = None):
    """Webhook called when agent connects to queue - triggers contact dialing"""
    import asyncio
    from app.config import BATCH_DIAL_COUNT

    if not campaign_id and agent_name and agent_name in agents:
        campaign_id = agents[agent_name].get("campaign_id")

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
            contacts_to_dial = [
                phone for phone in campaign.get("contacts", [])
                if campaign["contact_status"].get(phone) == "pending"
            ][:BATCH_DIAL_COUNT]

            logger.info(f"Dialing {len(contacts_to_dial)} pending contacts for campaign {campaign_id}")

            for phone in contacts_to_dial:
                campaign["contact_status"][phone] = "dialing"
                call_sid = twilio_service.dial_contact_to_agent_queue(phone, campaign_id, queue_name, campaign.get("agent_name"))
                if call_sid:
                    campaign["call_sids"][phone] = call_sid
                    logger.call(phone, f"Dialing contact for campaign {campaign_id}")

            remaining_pending = [
                phone for phone in campaign.get("contacts", [])
                if campaign["contact_status"].get(phone) == "pending"
            ]
            campaign["next_batch"] = remaining_pending[:BATCH_DIAL_COUNT]

        loop.run_in_executor(None, dial_contacts)
    else:
        logger.info(f"Agent reconnected to queue {queue_name} - waiting for manual dial command")

    # Return hold music TwiML
    response = VoiceResponse()
    response.play(QUEUE_HOLD_MUSIC_URL, loop=0)
    return create_twiml_response(response)


@router.post("/connect-agent")
async def connect_agent(_request: Request, agent_identity: str = None, customer_call_sid: str = None):
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
    campaign_id = form_data.get("campaign_id")
    agent_name = form_data.get("agent_name")

    response = VoiceResponse()

    if to.startswith("queue:"):
        # Put agent in the agent-specific queue to wait for customers
        queue_name = to.replace("queue:", "")
        # Backward compatibility: previously queue name was campaign_{campaign_id}
        if not campaign_id and queue_name.startswith("campaign_"):
            campaign_id = queue_name.replace("campaign_", "")

        # If campaign_id still not provided, try resolving via agent_name
        if not campaign_id and agent_name and agent_name in agents:
            campaign_id = agents[agent_name].get("campaign_id")

        # Trigger contact dialing when agent connects
        enqueue = Enqueue(
            wait_url=f"{BASE_URL}/api/voice/trigger-dialing?campaign_id={campaign_id}&queue_name={queue_name}&agent_name={quote(agent_name or '', safe='')}",
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
