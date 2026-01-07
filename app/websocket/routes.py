"""WebSocket routes"""
from fastapi import WebSocket, WebSocketDisconnect
from app.storage import active_websockets, agents, campaigns


async def websocket_endpoint(websocket: WebSocket, agent_name: str):
    """WebSocket endpoint for real-time agent updates"""
    await websocket.accept()
    
    # Store websocket for this agent
    active_websockets[agent_name] = websocket
    
    print(f"WebSocket connected for agent {agent_name}")
    
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
            print(f"Received from agent {agent_name}: {data}")
            
    except WebSocketDisconnect:
        print(f"WebSocket disconnected for agent {agent_name}")
        if agent_name in active_websockets:
            del active_websockets[agent_name]

