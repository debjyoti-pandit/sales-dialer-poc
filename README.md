# Sales Dialer POC

A proof-of-concept sales dialer application using Twilio Voice SDK and FastAPI.

## Features

- Browser-based softphone using Twilio Client JS SDK
- Campaign creation with contact list
- Conference-based dialing (agent joins conference, then customers are dialed in)

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
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_API_KEY=SKxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_API_SECRET=your_api_secret
TWILIO_TWIML_APP_SID=APxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_PHONE_NUMBER=+1234567890
```

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

1. **Initialize Dialer** - Click to get Twilio token and set up the browser phone
2. **Enter Contacts** - Add phone numbers (one per line) in the right panel
3. **Create Campaign** - Creates a campaign with your contact list
4. **Join Conference** - Agent joins the conference room and waits
5. (Next step: dial customers into the same conference)

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Browser       │────▶│   FastAPI       │────▶│   Twilio        │
│   (Twilio SDK)  │◀────│   Backend       │◀────│   Voice API     │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

## API Endpoints

- `GET /` - Serve frontend
- `POST /api/token` - Get Twilio access token
- `POST /api/campaign` - Create campaign with contacts
- `GET /api/campaign/{id}` - Get campaign details
- `POST /api/voice/conference` - TwiML for conference
- `POST /api/voice/dial` - TwiML for outbound dialing
