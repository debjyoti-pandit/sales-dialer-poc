# Ngrok Setup Guide

This guide explains how to use ngrok to expose your local Sales Dialer POC server to the internet for Twilio webhooks.

## Static Domain

This project uses a **static ngrok domain**: `https://sales-dialer-poc.jp.ngrok.io`

This means the URL will always be the same, so you don't need to update Twilio webhooks every time you restart ngrok.

## Why Ngrok?

Twilio webhooks need a publicly accessible URL to send call status updates and detection results. Ngrok creates a secure tunnel from the internet to your local server.

## Installation

### Option 1: Homebrew (macOS)
```bash
brew install ngrok
```

### Option 2: Direct Download
1. Visit https://ngrok.com/download
2. Download for your platform
3. Extract and add to your PATH

### Option 3: Python Package (Alternative)
```bash
pip install pyngrok
```

## Setup

1. **Get your ngrok auth token** (REQUIRED for static domains):
   - Sign up at https://dashboard.ngrok.com
   - Get your authtoken from https://dashboard.ngrok.com/get-started/your-authtoken
   - Set it as an environment variable:
     ```bash
     export NGROK_AUTH_TOKEN=your_token_here
     ```
   - Or add to your `.env` file:
     ```env
     NGROK_AUTH_TOKEN=your_token_here
     ```

2. **Configure ngrok**:
   ```bash
   ngrok config add-authtoken $NGROK_AUTH_TOKEN
   ```

3. **Verify static domain access**:
   - Make sure you have access to the static domain `sales-dialer-poc.jp.ngrok.io`
   - This requires an ngrok account with static domain feature
   - The domain is already configured in the scripts

## Usage

### Option 1: Bash Script (Simple)
```bash
# Start ngrok on default port 8000
./start_ngrok.sh

# Or specify a different port
./start_ngrok.sh 8000
```

### Option 2: Python Script (Advanced)
```bash
# Start ngrok and show URL
python start_ngrok.py

# Start on specific port
python start_ngrok.py 8000

# Auto-update .env file with the ngrok URL
python start_ngrok.py 8000 --update-env
```

### Option 3: Manual ngrok (with static domain)
```bash
# Start ngrok tunnel with static domain
ngrok http 8000 --domain=sales-dialer-poc.jp.ngrok.io

# The URL will always be: https://sales-dialer-poc.jp.ngrok.io
# BASE_URL is already configured in app/config.py
```

## Updating Twilio Configuration

The static domain `https://sales-dialer-poc.jp.ngrok.io` is already configured. Update your Twilio webhook URLs:

1. **TwiML App Configuration** (in Twilio Console):
   - Voice URL: `https://sales-dialer-poc.jp.ngrok.io/api/voice/dial`
   - Method: POST

2. **BASE_URL is already configured**:
   - Default: `https://sales-dialer-poc.jp.ngrok.io` (in `app/config.py`)
   - You can override with `.env` file if needed:
     ```env
     BASE_URL=https://sales-dialer-poc.jp.ngrok.io
     ```

## Webhook Endpoints

All endpoints are accessible via the static domain:
- `POST https://sales-dialer-poc.jp.ngrok.io/api/voice/customer-queue` - Call answered → queue
- `POST https://sales-dialer-poc.jp.ngrok.io/api/voice/amd-status` - AMD detection results
- `POST https://sales-dialer-poc.jp.ngrok.io/api/voice/status` - Call status updates
- `POST https://sales-dialer-poc.jp.ngrok.io/api/voice/customer-join-conference` - Join conference
- `POST https://sales-dialer-poc.jp.ngrok.io/api/voice/dial` - TwiML App dial endpoint

## Testing

1. Start your FastAPI server:
   ```bash
   python main.py
   ```

2. In another terminal, start ngrok:
   ```bash
   ./start_ngrok.sh
   ```

3. Verify the tunnel is working:
   - Visit http://localhost:4040 (ngrok web interface)
   - Check that requests are being forwarded

4. Test webhook endpoints:
   ```bash
   curl https://your-ngrok-url.ngrok.io/
   ```

## Troubleshooting

### Ngrok URL changes every time
- **Solution**: This project uses a static domain `sales-dialer-poc.jp.ngrok.io`
- The URL will always be the same
- Make sure you have access to this static domain in your ngrok account

### Webhooks not reaching your server
- Check that your FastAPI server is running on the correct port (default: 8000)
- Verify BASE_URL is set to `https://sales-dialer-poc.jp.ngrok.io` (already configured in `app/config.py`)
- Check ngrok web interface at http://localhost:4040 for request logs
- Ensure ngrok is running with the static domain: `ngrok http 8000 --domain=sales-dialer-poc.jp.ngrok.io`

### Port already in use
- Make sure no other ngrok instance is running
- Or use a different port: `ngrok http 8001`

## Production Alternative

For production, use a proper hosting service instead of ngrok:
- Deploy to Heroku, AWS, Google Cloud, etc.
- Use a real domain name
- Set up SSL certificates
- Update BASE_URL to your production URL

