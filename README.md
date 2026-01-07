# Sales Dialer POC

A proof-of-concept sales dialer application using Twilio Voice SDK and FastAPI.

## Features

- Browser-based softphone using Twilio Client JS SDK
- Campaign-based queue system (one queue per campaign)
- Shared contact list from text file with automatic recycling
- Batch dialing with duplicate prevention across agents
- Agents hear hold music while waiting in campaign queue
- Automatic agent-customer connection via Twilio queues
- Answering machine detection and voicemail filtering
- Real-time status updates via WebSocket

## Setup

### 1. Twilio Configuration

You need to set up the following in your Twilio Console:

1. **Get Account Credentials**
   - Account SID (from Dashboard)
   - Auth Token (from Dashboard)

2. **Create API Key**
   - Go to Account → API Keys → Create new API Key
   - Save the API Key SID and Secret

3. **Create TwiML App**
   - Go to Voice → TwiML Apps → Create new TwiML App
   - Set Voice Request URL to: `http://your-server:8000/api/voice/dial`
   - Save the TwiML App SID

4. **Get a Twilio Phone Number**
   - Purchase or use existing Twilio phone number for Caller ID

### 2. Environment Variables

Create a `.env` file in the project root:

```bash
# Twilio Configuration
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_API_KEY=SKxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_API_SECRET=your_api_secret
TWILIO_TWIML_APP_SID=APxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_PHONE_NUMBER=+1234567890

# Base URL for webhooks (update with your ngrok URL or server address)
BASE_URL=https://your-server.ngrok.io

# Campaign Configuration
BATCH_DIAL_COUNT=5
```

#### Environment Variables

- `TWILIO_*`: Twilio API credentials (see setup section)
- `BASE_URL`: Webhook URL for Twilio callbacks
- `BATCH_DIAL_COUNT`: Number of contacts to dial in each batch (default: 5)

### 3. Install Dependencies

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Run the Server

```bash
python main.py
```

Or with uvicorn directly:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 5. Access the Application

Open http://localhost:8000 in your browser.

## Usage

1. **Enter Agent Name** - Enter your name when prompted to identify yourself in the system
2. **Start Campaign** - Your device connects directly to the campaign queue where you'll hear hold music
3. **Receive Calls** - Customers who answer are automatically connected to you through the queue
4. **Handle Calls** - Bridge established automatically - just talk to the connected customer
5. **Call Next Batch** - Request additional contacts to be dialed from the shared list
6. **End Campaign** - Disconnect from queue and terminate all calls

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Agent Browser │────▶│   FastAPI       │────▶│   Twilio        │
│   (Twilio SDK)  │◀────│   Backend       │◀────│   Voice API     │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                      │                        │
                      ▼                        ▼
               ┌─────────────────┐     ┌─────────────────┐
               │  Contact List   │     │  Campaign      │
               │  (contacts.txt) │     │  Queue         │
               └─────────────────┘     └─────────────────┘
```

- **Contact List**: Shared text file with phone numbers (auto-recycles when exhausted)
- **Global Wait Queue**: Single Twilio queue for all agents and customers
- **Agent Flow**: Agent connects to waiting state → hears hold music → gets connected when customers join queue
- **Customer Flow**: Contacts dialed → answer → AMD check → join global wait queue → connect to available agent
- **Simple Architecture**: One queue handles all call distribution automatically
- **Batch Dialing**: Configurable batch sizes with duplicate prevention
- **Real-time Updates**: WebSocket connections provide live status updates

## API Endpoints

- `GET /` - Serve frontend
- `POST /api/token` - Get Twilio access token
- `POST /api/campaign/start` - Start agent campaign (batch dial contacts)
- `POST /api/agent/{name}/dial-next-batch` - Dial next batch of contacts
- `POST /api/agent/{name}/end` - End agent's campaign
- `GET /api/agent/{name}/campaign` - Get agent's campaign details
- `POST /api/voice/customer-queue` - TwiML for customer queue (when they answer)
- `POST /api/voice/connect-agent` - TwiML to connect call to agent's device
- `POST /api/voice/status` - Call status webhooks
- `POST /api/voice/amd-status` - Answering machine detection results

## Files

- `contacts.txt` - Shared contact list (one phone number per line)
- `.env` - Environment variables (see setup section)
