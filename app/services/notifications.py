"""Africa's Talking integration boundary; outcomes always reflect the provider result."""
from dataclasses import asdict, dataclass
from flask import current_app


@dataclass
class Attempt:
    channel: str
    attempted: bool
    status: str
    provider_response: dict | None = None
    detail: str | None = None

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
        return None, f"Africa's Talking client could not be initialized: {type(exc).__name__}."


def send_sms(recipients, message):
    client, error = _client()
    if error:
        return Attempt("sms", False, "NOT_CONFIGURED", detail=error)
    try:
        response = client.SMS.send(message, recipients)
        # The SDK response is passed through; it is not interpreted as delivery confirmation.
        return Attempt("sms", True, "PROVIDER_RESPONSE", provider_response=response)
    except Exception as exc:
        return Attempt("sms", True, "FAILED", detail=f"Provider request failed: {type(exc).__name__}.")


def queue_voice_alert(recipient, message):
    client, error = _client()
    voice_from = current_app.config.get("AT_VOICE_FROM")
    if error:
        return Attempt("voice", False, "NOT_CONFIGURED", detail=error)
    if not voice_from:
        return Attempt("voice", False, "NOT_CONFIGURED", detail="AT_VOICE_FROM is required for a Voice API request.")
    try:
        response = client.Voice.call(voice_from, [recipient])
        return Attempt("voice", True, "PROVIDER_RESPONSE", provider_response=response,
                       detail="Call request submitted; completion is not inferred.")
    except Exception as exc:
        return Attempt("voice", True, "FAILED", detail=f"Provider request failed: {type(exc).__name__}.")
