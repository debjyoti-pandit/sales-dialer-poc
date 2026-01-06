#!/bin/bash

# Ngrok tunnel script for Sales Dialer POC
# This script starts an ngrok tunnel with static domain: sales-dialer-poc.jp.ngrok.io

PORT=${1:-8000}
NGROK_DOMAIN="sales-dialer-poc.jp.ngrok.io"
NGROK_AUTH_TOKEN=${NGROK_AUTH_TOKEN:-""}

echo "🚀 Starting ngrok tunnel on port $PORT..."
echo "🌐 Using static domain: $NGROK_DOMAIN"

# Check if ngrok is installed
if ! command -v ngrok &> /dev/null; then
    echo "❌ Error: ngrok is not installed."
    echo "📥 Install it from: https://ngrok.com/download"
    echo "   Or via homebrew: brew install ngrok"
    exit 1
fi

# Set auth token if provided
if [ -n "$NGROK_AUTH_TOKEN" ]; then
    ngrok config add-authtoken "$NGROK_AUTH_TOKEN" 2>/dev/null
    echo "✅ Ngrok auth token configured"
else
    echo "⚠️  NGROK_AUTH_TOKEN not set (required for static domains)"
    echo "   Get your token from: https://dashboard.ngrok.com/get-started/your-authtoken"
fi

# Start ngrok tunnel with static domain
echo "🌐 Starting tunnel with static domain..."
echo "📋 Static URL: https://$NGROK_DOMAIN"
echo "   BASE_URL is already configured in app/config.py"
echo ""
echo "Press Ctrl+C to stop the tunnel"
echo ""

# Start ngrok with static domain
ngrok http $PORT --domain=$NGROK_DOMAIN

