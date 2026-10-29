"""Africa's Talking SDK integration; no outcome is treated as delivery/call completion."""
import logging
from dataclasses import asdict, dataclass
from flask import current_app

logger = logging.getLogger(__name__)


@dataclass
class Attempt:
    channel: str
    attempted: bool
    status: str
    provider_response: dict | None = None
    detail: str | None = None
    provider_status: str | None = None
    provider_message_id: str | None = None

    def serialize(self):
        return asdict(self)


def _client():
    api_key = current_app.config.get("AT_API_KEY")
    username = current_app.config.get("AT_USERNAME")
    if not api_key or not username:
        return None, "Africa's Talking credentials are not configured."
    try:
        import africastalking
        africastalking.initialize(username, api_key)
        return africastalking, None
    except Exception as exc:  # imports/configuration errors must remain safe
        logger.warning("Africa's Talking client initialization failed: %s", type(exc).__name__)
        return None, f"Africa's Talking client could not be initialized: {type(exc).__name__}."


def _safe_response(value):
    """Keep the provider response for audit without serializing objects or secrets."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _safe_response(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_response(item) for item in value]
    return str(value)


def _sms_metadata(response):
    recipients = response.get("SMSMessageData", {}).get("Recipients", []) if isinstance(response, dict) else []
    first = recipients[0] if recipients and isinstance(recipients[0], dict) else {}
    return first.get("status"), first.get("messageId")


def _voice_metadata(response):
    entries = response.get("entries", []) if isinstance(response, dict) else []
    first = entries[0] if entries and isinstance(entries[0], dict) else {}
    return first.get("status"), first.get("sessionId")


def send_sms(recipients, message):
    client, error = _client()
    if error:
        return Attempt("sms", False, "NOT_CONFIGURED", detail=error)
    try:
        response = _safe_response(client.SMS.send(message, recipients, sender_id=current_app.config.get("AT_SMS_SENDER_ID")))
        provider_status, message_id = _sms_metadata(response)
        return Attempt("sms", True, "PROVIDER_RESPONSE", provider_response=response,
                       provider_status=provider_status, provider_message_id=message_id)
    except Exception as exc:
        logger.warning("Africa's Talking SMS request failed: %s", type(exc).__name__)
        return Attempt("sms", True, "FAILED", detail=f"Provider request failed: {type(exc).__name__}.")


def queue_voice_alert(recipient, message):
    client, error = _client()
    voice_from = current_app.config.get("AT_VOICE_FROM")
    if error:
        return Attempt("voice", False, "NOT_CONFIGURED", detail=error)
    if not voice_from:
        return Attempt("voice", False, "NOT_CONFIGURED", detail="AT_VOICE_FROM is required for a Voice API request.")
    try:
        response = _safe_response(client.Voice.call(voice_from, [recipient]))
        provider_status, session_id = _voice_metadata(response)
        return Attempt("voice", True, "PROVIDER_RESPONSE", provider_response=response,
                       provider_status=provider_status, provider_message_id=session_id,
                       detail="Call request submitted; completion is not inferred.")
    except Exception as exc:
        logger.warning("Africa's Talking Voice request failed: %s", type(exc).__name__)
        return Attempt("voice", True, "FAILED", detail=f"Provider request failed: {type(exc).__name__}.")
