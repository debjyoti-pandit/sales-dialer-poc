"""WebSocket routes"""
from fastapi import WebSocket, WebSocketDisconnect
from app.storage import active_websockets, agents, campaigns
from app.logger import logger
from app.websocket.manager import broadcast_to_agent


async def websocket_endpoint(websocket: WebSocket, agent_name: str):
    """WebSocket endpoint for real-time agent updates"""
    await websocket.accept()
    
    # Store websocket for this agent
    active_websockets[agent_name] = websocket
    
    logger.agent(agent_name, "WebSocket connected")
    
    try:
        # Send current agent state if exists
        if agent_name in agents:
            agent = agents[agent_name]
            campaign_id = agent.get("campaign_id")
            if campaign_id and campaign_id in campaigns:
                await websocket.send_json({
                    "type": "agent_state",
                    "agent": agent,
                    "campaign": campaigns[campaign_id]
                })
            else:
                await websocket.send_json({
                    "type": "agent_state",
                    "agent": agent
                })
        
        # Keep connection alive and handle incoming messages
        while True:
            data = await websocket.receive_text()
            # Handle any client messages if needed
            logger.agent(agent_name, f"Received: {data}")
            
    except WebSocketDisconnect:
        logger.agent(agent_name, "WebSocket disconnected")
        if agent_name in active_websockets:
            del active_websockets[agent_name]


async def transcript_ingest_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for transcription service to push live transcripts.

    This is intentionally separate from /ws/{agent_name} so we don't overwrite the
    browser websocket stored in active_websockets[agent_name].
    """
    await websocket.accept()
    logger.info("Transcript ingest WebSocket connected")

    try:
        while True:
            data = await websocket.receive_json()
            agent_name = (data.get("agent_name") or "").strip()
            phone = (data.get("phone") or "").strip()
            call_sid = (data.get("call_sid") or "").strip()
            transcript = (data.get("transcript") or "").strip()

            if not agent_name or not transcript:
                continue

            logger.info(
                "Transcript ingest: agent=%s phone=%s call_sid=%s len=%s",
                agent_name,
                phone,
                call_sid,
                len(transcript),
            )

            await broadcast_to_agent(
                agent_name,
                {
                    "type": "live_transcript",
                    "phone": phone,
                    "call_sid": call_sid,
                    "transcript": transcript,
                    "is_final": bool(data.get("is_final")),
                    "updated_at": data.get("updated_at"),
                },
            )
    except WebSocketDisconnect:
        logger.info("Transcript ingest WebSocket disconnected")
