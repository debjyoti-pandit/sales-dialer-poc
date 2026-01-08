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

# Conference settings
CONFERENCE_NAME = "SalesDialerConference"

# Detection settings
DETECTION_TIMEOUT = 5  # seconds to wait for detection result
QUEUE_HOLD_MUSIC_URL = "https://twimlets.com/holdmusic?Bucket=com.twilio.music.classical"
# Campaign settings
BATCH_DIAL_COUNT = int(os.getenv("BATCH_DIAL_COUNT", "5"))
