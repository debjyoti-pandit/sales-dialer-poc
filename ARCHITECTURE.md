# Sales Dialer POC - Architecture Documentation

## Overview

This application has been refactored into a modular structure for better scalability and maintainability. The key feature is a **call queue system with async answering machine detection (AMD)** that routes calls to conference only after detecting a human answer.

## Architecture

### Directory Structure

```
app/
├── __init__.py
├── main.py                 # FastAPI app initialization
├── config.py               # Configuration and environment variables
├── models/                 # Pydantic models
│   ├── __init__.py
│   └── campaign.py
├── services/               # Business logic
│   ├── __init__.py
│   ├── twilio_service.py   # Twilio API operations
│   ├── campaign_service.py # Campaign management
│   └── call_queue_service.py # Call queue and detection processing
├── routes/                 # API endpoints
│   ├── __init__.py
│   ├── campaign_routes.py # Campaign CRUD operations
│   ├── voice_routes.py     # Twilio voice webhooks
│   └── static_routes.py    # Static file serving
├── websocket/              # WebSocket management
│   ├── __init__.py
│   ├── manager.py          # WebSocket broadcasting
│   └── routes.py           # WebSocket endpoint
└── storage/                # In-memory storage (can be replaced with DB)
    └── __init__.py
```

## Call Flow with Queue System

### 1. Call Initiation
- When a campaign is created or "dial next" is called, `twilio_service.dial_contact()` initiates a call
- The call is configured with:
  - **Async AMD enabled**: `machine_detection="Enable"` and `async_amd="true"`
  - **Queue endpoint**: Calls are routed to `/api/voice/customer-queue` when answered
  - **AMD callback**: Results sent to `/api/voice/amd-status`
  - **Status callback**: Call status updates sent to `/api/voice/status`

### 2. Call Answered → Queue
- When the call is answered, Twilio routes to `/api/voice/customer-queue`
- The call is:
  - Added to the call queue (`call_queue_service.add_to_queue()`)
  - Status updated to "queued"
  - Hold music starts playing (loops while waiting)
  - WebSocket broadcast sent to notify frontend

### 3. Async Detection
- Twilio runs answering machine detection in parallel
- When detection completes, Twilio sends result to `/api/voice/amd-status`
- Detection result includes:
  - `AnsweredBy`: "human", "machine", or "unknown"
  - `MachineDetectionStatus`: "completed" or "failed"

### 4. Queue Processing
- `call_queue_service.process_detection_result()` processes the detection:
  - **If human detected**: Call is redirected to conference via Twilio REST API
  - **If machine detected**: Call is hung up
  - **If unknown**: Call is connected (configurable)
- When redirecting to conference:
  - Call URL is updated using `twilio_service.redirect_call_to_conference()`
  - Call is removed from queue
  - Campaign status updated to "connected"
  - Other calls are hung up
  - WebSocket broadcast sent

### 5. Conference Join
- Redirected call goes to `/api/voice/customer-join-conference`
- TwiML response joins the call to the conference
- Agent and customer can now talk

## Key Components

### Services

#### `TwilioService`
- Handles all Twilio API interactions
- Methods:
  - `generate_token()`: Creates Twilio access tokens
  - `dial_contact()`: Initiates outbound calls with AMD
  - `hangup_call()`: Terminates calls
  - `redirect_call_to_conference()`: Redirects active calls to conference

#### `CallQueueService`
- Manages the call queue
- Processes detection results
- Methods:
  - `add_to_queue()`: Add call to queue
  - `remove_from_queue()`: Remove call from queue
  - `process_detection_result()`: Process AMD results and route calls

#### `CampaignService`
- Manages campaign lifecycle
- Methods:
  - `create_campaign()`: Create new campaign
  - `get_campaign()`: Retrieve campaign
  - `dial_next_contact()`: Dial next contact in rotation
  - `save_disposition()`: Save call disposition
  - `end_campaign()`: End campaign and hang up calls

### Storage

Currently uses in-memory dictionaries:
- `campaigns`: Campaign data
- `active_websockets`: WebSocket connections per campaign
- `call_queues`: Queued calls per campaign
- `detection_results`: AMD results by call SID

**Note**: This can be easily replaced with a database (PostgreSQL, MongoDB, etc.) for production.

## API Endpoints

### Campaign Endpoints
- `POST /api/campaign` - Create campaign
- `GET /api/campaign/{campaign_id}` - Get campaign
- `POST /api/campaign/{campaign_id}/dial-next` - Dial next contact
- `POST /api/campaign/{campaign_id}/disposition` - Save disposition
- `POST /api/campaign/{campaign_id}/end` - End campaign
- `POST /api/token` - Get Twilio token

### Voice Webhooks
- `POST /api/voice/customer-queue` - Call answered → queue
- `POST /api/voice/amd-status` - AMD result callback
- `POST /api/voice/customer-join-conference` - Join conference
- `POST /api/voice/status` - Call status updates
- `POST /api/voice/dial` - TwiML App dial endpoint

### WebSocket
- `WS /ws/{campaign_id}` - Real-time campaign updates

## Configuration

Environment variables (in `.env`):
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_API_KEY`
- `TWILIO_API_SECRET`
- `TWILIO_TWIML_APP_SID`
- `TWILIO_PHONE_NUMBER`
- `BASE_URL` (default: `http://localhost:8000`)

## Running the Application

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
# or
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Benefits of Modular Structure

1. **Separation of Concerns**: Each module has a single responsibility
2. **Testability**: Services can be tested independently
3. **Scalability**: Easy to add new features or replace components
4. **Maintainability**: Clear structure makes code easier to understand
5. **Reusability**: Services can be reused across different routes

## Future Enhancements

- Replace in-memory storage with database
- Add Redis for distributed queue management
- Implement call recording
- Add analytics and reporting
- Support multiple concurrent campaigns
- Add authentication and authorization
- Implement rate limiting

