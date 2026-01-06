"""In-memory storage for campaigns and WebSocket connections"""
from typing import Dict, Set
from fastapi import WebSocket

# Campaign storage: campaign_id -> campaign dict
campaigns: Dict[str, dict] = {}

# WebSocket connections: campaign_id -> set of websockets
active_websockets: Dict[str, Set[WebSocket]] = {}

# Call queue: campaign_id -> list of queued calls {call_sid, phone, queued_at}
call_queues: Dict[str, list] = {}

# Detection results: call_sid -> detection result
detection_results: Dict[str, dict] = {}

