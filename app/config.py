"""Application configuration"""

import os
from dotenv import load_dotenv

load_dotenv()

# Twilio credentials
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_API_KEY = os.getenv("TWILIO_API_KEY")
TWILIO_API_SECRET = os.getenv("TWILIO_API_SECRET")
TWILIO_TWIML_APP_SID = os.getenv("TWILIO_TWIML_APP_SID")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

# Base URL for TwiML webhooks
BASE_URL = os.getenv("BASE_URL", "https://sales-dialer-poc.jp.ngrok.io")

# Optional: Twilio Media Streams websocket target for live transcription
# Example: wss://sales-dialer-transcription-service.jp.ngrok.io/twilio/media
TRANSCRIPTION_STREAM_WSS_URL = os.getenv("TRANSCRIPTION_STREAM_WSS_URL", "")

# Optional: Where transcription service should push transcript events (server -> server).
# Example: wss://sales-dialer-poc.jp.ngrok.io/ws/transcripts?token=...
TRANSCRIPTION_INGEST_WS_URL = os.getenv("TRANSCRIPTION_INGEST_WS_URL", "")

# Conference settings
CONFERENCE_NAME = "SalesDialerConference"

# Detection settings
DETECTION_TIMEOUT = 5  # seconds to wait for detection result
QUEUE_HOLD_MUSIC_URL = "http://com.twilio.sounds.music.s3.amazonaws.com/ClockworkWaltz.mp3"
# Campaign settings
BATCH_DIAL_COUNT = int(os.getenv("BATCH_DIAL_COUNT", "5"))
# How many contacts to assign (reserve) per agent per campaign selection
AGENT_CONTACT_POOL_SIZE = int(os.getenv("AGENT_CONTACT_POOL_SIZE", "20"))
