"""WebSocket connection manager"""
from app.storage import active_websockets, campaigns


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

