"""WebSocket routes"""
from fastapi import WebSocket, WebSocketDisconnect
from app.storage import active_websockets, campaigns


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

