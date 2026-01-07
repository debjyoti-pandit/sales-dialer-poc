"""WebSocket connection manager"""
from app.storage import active_websockets, agents


async def broadcast_to_agent(agent_name: str, message: dict):
    """Send message to agent's WebSocket"""
    if agent_name in active_websockets:
        try:
            await active_websockets[agent_name].send_json(message)
        except:
            # Connection is dead, remove it
            if agent_name in active_websockets:
                del active_websockets[agent_name]

