"""Twilio service for making calls and managing Twilio operations"""

from urllib.parse import quote
from twilio.rest import Client
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant
import uuid
from app.config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_API_KEY,
    TWILIO_API_SECRET,
    TWILIO_TWIML_APP_SID,
    TWILIO_PHONE_NUMBER,
    BASE_URL,
    CONFERENCE_NAME,
)


class TwilioService:
    """Service for Twilio operations"""

    def __init__(self):
        self.client = None
        if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
            self.client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

    def generate_token(self):
        """Generate Twilio Access Token for the browser client"""
        if not all(
            [
                TWILIO_ACCOUNT_SID,
                TWILIO_API_KEY,
                TWILIO_API_SECRET,
                TWILIO_TWIML_APP_SID,
            ]
        ):
            return None, None

        identity = f"agent_{uuid.uuid4().hex[:8]}"
        token = AccessToken(
            TWILIO_ACCOUNT_SID, TWILIO_API_KEY, TWILIO_API_SECRET, identity=identity
        )
        voice_grant = VoiceGrant(
            outgoing_application_sid=TWILIO_TWIML_APP_SID, incoming_allow=True
        )
        token.add_grant(voice_grant)
        return token.to_jwt(), identity

    def dial_contact(self, phone_number: str, campaign_id: str, agent_name: str = None):
        """Dial a single contact"""
        print(f"Dialing contact {phone_number} for campaign {campaign_id} (agent: {agent_name})")

        if not self.client:
            print(f"Twilio client not configured, skipping {phone_number}")
            return None

        # URL-encode the phone number to handle + sign
        encoded_phone = quote(phone_number, safe="")
        encoded_agent = quote(agent_name or "", safe="")

        try:
            call = self.client.calls.create(
                to=phone_number,
                from_=TWILIO_PHONE_NUMBER,
                url=f"{BASE_URL}/api/voice/customer-queue?campaign_id={campaign_id}&phone={encoded_phone}&agent_name={encoded_agent}",
                status_callback=f"{BASE_URL}/api/voice/status?campaign_id={campaign_id}&phone={encoded_phone}&agent_name={encoded_agent}",
                status_callback_event=["initiated", "ringing", "answered", "completed"],
                status_callback_method="POST",
                machine_detection="Enable",  # Enable answering machine detection
                async_amd="true",  # Use async AMD
                async_amd_status_callback=f"{BASE_URL}/api/voice/amd-status?campaign_id={campaign_id}&phone={encoded_phone}&agent_name={encoded_agent}",
                async_amd_status_callback_method="POST",
            )
            print(f"Call initiated to {phone_number}: {call.sid}")
            return call.sid
        except Exception as e:
            print(f"Error dialing {phone_number}: {e}")
            return None

    def hangup_call(self, call_sid: str):
        """Hang up a specific call"""
        if not self.client:
            return False
        try:
            self.client.calls(call_sid).update(status="completed")
            print(f"Hung up call {call_sid}")
            return True
        except Exception as e:
            print(f"Error hanging up call {call_sid}: {e}")
            return False

    def dequeue_call(self, queue_name: str, call_sid: str, dequeue_url: str):
        """Dequeue a call from a Twilio queue and redirect it"""
        if not self.client:
            return False
        try:
            # Find the queue by friendly_name (need to iterate as list() doesn't support friendly_name filter)
            queue = None
            queues = self.client.queues.list(limit=100)  # Get all queues
            for q in queues:
                if q.friendly_name == queue_name:
                    queue = q
                    break
            
            if not queue:
                print(f"Queue {queue_name} not found")
                return False
            
            # Get the member (call) from the queue
            # Note: members.list() doesn't support call_sid filter, so we need to iterate
            members = queue.members.list()
            member = None
            for m in members:
                if m.call_sid == call_sid:
                    member = m
                    break
            
            if not member:
                print(f"Call {call_sid} not found in queue {queue_name}")
                return False
            
            # Dequeue the call and redirect to the specified URL
            member.update(url=dequeue_url, method="POST")
            print(f"Dequeued call {call_sid} from queue {queue_name} and redirected to {dequeue_url}")
            return True
        except Exception as e:
            print(f"Error dequeuing call {call_sid} from queue {queue_name}: {e}")
            return False
    
    def dial_agent_device(self, agent_identity: str, customer_call_sid: str):
        """Dial the agent's device and connect it to the customer call"""
        if not self.client:
            return False
        try:
            # Create a TwiML URL that will dial the agent's client
            encoded_identity = quote(agent_identity, safe="")
            encoded_call_sid = quote(customer_call_sid, safe="")
            dial_url = f"{BASE_URL}/api/voice/connect-agent?agent_identity={encoded_identity}&customer_call_sid={encoded_call_sid}"
            
            # Update the customer call to dial the agent
            self.client.calls(customer_call_sid).update(
                url=dial_url,
                method="POST"
            )
            print(f"Dialing agent {agent_identity} for call {customer_call_sid}")
            return True
        except Exception as e:
            print(f"Error dialing agent device: {e}")
            return False


# Singleton instance
twilio_service = TwilioService()
