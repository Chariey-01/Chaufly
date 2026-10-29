"""Africa's Talking SMS + Voice integration.

Uses a plain httpx transport so it can be mocked in tests, and falls back to a
console sender when ``AT_ENABLED`` is false so the demo runs with no credentials.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger("ifinder.at")


@dataclass
class SmsResult:
    sent: bool
    recipient: str
    message_id: str | None = None
    cost: str | None = None
    status: str | None = None
    error: str | None = None
    provider: str = "africastalking"


@dataclass
class VoiceResult:
    queued: bool
    recipient: str
    call_id: str | None = None
    error: str | None = None


class AtSmsClient:
    """Thin wrapper over Africa's Talking messaging endpoint."""

    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self._client = http_client or httpx.Client(timeout=settings.at_http_timeout)

    @property
    def enabled(self) -> bool:
        return bool(settings.at_enabled and settings.at_api_key)

    def send(self, message: str, recipients: list[str], sender_id: str | None = None) -> list[SmsResult]:
        if not recipients:
            return []

        if not self.enabled:
            for recipient in recipients:
                logger.info("[AT disabled] SMS to %s: %s", recipient, message)
            return [
                SmsResult(sent=True, recipient=r, message_id=f"console-{i}", status="Console", provider="console")
                for i, r in enumerate(recipients, start=1)
            ]

        payload = {
            "username": settings.at_username,
            "to": ",".join(recipients),
            "message": message,
            "from": sender_id or settings.at_sender_id,
        }
        headers = {
            "apiKey": settings.at_api_key,
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        try:
            response = self._client.post(settings.at_sms_url, data=payload, headers=headers)
            response.raise_for_status()
            body = response.json()
        except Exception as exc:  # network, HTTP error, malformed JSON
            logger.exception("Africa's Talking SMS failure")
            return [SmsResult(sent=False, recipient=r, error=str(exc)) for r in recipients]

        return self._parse_sms_response(body, recipients)

    @staticmethod
    def _parse_sms_response(body: dict, requested: list[str]) -> list[SmsResult]:
        data = body.get("SMSMessageData", {}) or {}
        entries = data.get("Recipients") or []
        if not entries:
            # No per-recipient detail: surface the top-level message.
            err = data.get("Message") or "No recipients in Africa's Talking response"
            return [SmsResult(sent=False, recipient=r, error=err) for r in requested]

        results: list[SmsResult] = []
        for entry in entries:
            status_code = entry.get("statusCode")
            ok = status_code == 101 or str(entry.get("status", "")).lower() == "success"
            results.append(
                SmsResult(
                    sent=ok,
                    recipient=entry.get("number") or "",
                    message_id=entry.get("messageId"),
                    cost=entry.get("cost"),
                    status=entry.get("status"),
                    error=None if ok else entry.get("status"),
                )
            )
        return results


class AtVoiceClient:
    """Thin wrapper over Africa's Talking voice call endpoint (used for SOS alerting)."""

    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self._client = http_client or httpx.Client(timeout=settings.at_http_timeout)

    @property
    def enabled(self) -> bool:
        return bool(settings.at_enabled and settings.at_api_key)

    def call(self, recipients: list[str], sender_id: str | None = None) -> list[VoiceResult]:
        if not recipients:
            return []

        if not self.enabled:
            for recipient in recipients:
                logger.warning("[AT disabled] VOICE alert queued for %s", recipient)
            return [
                VoiceResult(queued=True, recipient=r, call_id=f"console-voice-{i}")
                for i, r in enumerate(recipients, start=1)
            ]

        headers = {"apiKey": settings.at_api_key, "Accept": "application/json"}
        data = {
            "username": settings.at_username,
            "to": ",".join(recipients),
            "from": sender_id or settings.at_sender_id,
        }
        try:
            response = self._client.post(settings.at_voice_url, data=data, headers=headers)
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            logger.exception("Africa's Talking Voice failure")
            return [VoiceResult(queued=False, recipient=r, error=str(exc)) for r in recipients]

        entries = body.get("entries") or []
        if not entries:
            err = body.get("errorMessage") or "No entries in Africa's Talking voice response"
            return [VoiceResult(queued=False, recipient=r, error=err) for r in recipients]

        return [
            VoiceResult(
                queued=str(e.get("status", "")).lower() in {"queued", "success"},
                recipient=e.get("phoneNumber") or "",
                call_id=e.get("sessionId"),
                error=e.get("errorMessage"),
            )
            for e in entries
        ]


# Module-level singletons, replaced in tests via dependency overrides / monkeypatch.
sms_client = AtSmsClient()
voice_client = AtVoiceClient()
