"""In-memory storage for campaigns and WebSocket connections"""
from typing import Dict, Set
from fastapi import WebSocket

# Campaign storage: campaign_id -> campaign dict
campaigns: Dict[str, dict] = {}

# Agent storage: agent_name -> agent dict {name, campaign_id, status, etc}
agents: Dict[str, dict] = {}

# WebSocket connections: agent_name -> websocket (one per agent)
active_websockets: Dict[str, WebSocket] = {}

# Call queue: agent_name -> list of queued calls {call_sid, phone, queued_at}
call_queues: Dict[str, list] = {}

# Detection results: call_sid -> detection result
detection_results: Dict[str, dict] = {}

# Global dialed contacts tracking: phone -> set of agent_names who dialed it
dialed_contacts: Dict[str, Set[str]] = {}

