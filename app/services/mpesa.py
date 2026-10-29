"""M-Pesa Daraja STK Push integration (optional for the MVP).

When ``MPESA_ENABLED`` is false the service returns a simulated checkout id so
the demo flow and tests work without Daraja credentials.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from app.config import settings

logger = logging.getLogger("ifinder.mpesa")

SANDBOX_BASE = "https://sandbox.safaricom.co.ke"
PRODUCTION_BASE = "https://api.safaricom.co.ke"


@dataclass
class StkPushResult:
    requested: bool
    checkout_request_id: str | None = None
    merchant_request_id: str | None = None
    customer_message: str | None = None
    error: str | None = None


class MpesaClient:
    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self._client = http_client or httpx.Client(timeout=settings.at_http_timeout)
        self._token: str | None = None
        self._token_expiry: datetime | None = None

    @property
    def enabled(self) -> bool:
        return bool(settings.mpesa_enabled and settings.mpesa_consumer_key and settings.mpesa_consumer_secret)

    @property
    def base_url(self) -> str:
        return SANDBOX_BASE if settings.mpesa_env == "sandbox" else PRODUCTION_BASE

    # -- OAuth ---------------------------------------------------------------
    def _access_token(self) -> str:
        now = datetime.now(timezone.utc)
        if self._token and self._token_expiry and now < self._token_expiry:
            return self._token

        credentials = f"{settings.mpesa_consumer_key}:{settings.mpesa_consumer_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()
        response = self._client.get(
            f"{self.base_url}/oauth/v1/generate?grant_type=client_credentials",
            headers={"Authorization": f"Basic {encoded}"},
        )
        response.raise_for_status()
        body = response.json()
        self._token = body["access_token"]
        # Refresh a minute early to avoid edge-of-expiry failures.
        self._token_expiry = now + timedelta(seconds=int(body.get("expires_in", 3599)) - 60)
        return self._token

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().strftime("%Y%m%d%H%M%S")

    def _password(self, timestamp: str) -> str:
        raw = f"{settings.mpesa_shortcode}{settings.mpesa_passkey}{timestamp}"
        return base64.b64encode(raw.encode()).decode()

    # -- STK Push ------------------------------------------------------------
    def stk_push(self, *, phone: str, amount: float, account_ref: str, description: str) -> StkPushResult:
        if not self.enabled:
            simulated = f"ws_CO_SIMULATED_{account_ref}"
            logger.info("[M-Pesa disabled] simulated STK push %s for %s KES %s", simulated, phone, amount)
            return StkPushResult(requested=True, checkout_request_id=simulated, customer_message="Simulated")

        timestamp = self._timestamp()
        payload = {
            "BusinessShortCode": settings.mpesa_shortcode,
            "Password": self._password(timestamp),
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": int(round(amount)),
            "PartyA": phone,
            "PartyB": settings.mpesa_shortcode,
            "PhoneNumber": phone,
            "CallBackURL": settings.mpesa_callback_url,
            "AccountReference": account_ref[:12],
            "TransactionDesc": description[:100],
        }
        try:
            token = self._access_token()
            response = self._client.post(
                f"{self.base_url}/mpesa/stkpush/v1/processrequest",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            logger.exception("M-Pesa STK push failed")
            return StkPushResult(requested=False, error=str(exc))

        ok = str(body.get("ResponseCode")) == "0"
        return StkPushResult(
            requested=ok,
            checkout_request_id=body.get("CheckoutRequestID"),
            merchant_request_id=body.get("MerchantRequestID"),
            customer_message=body.get("CustomerMessage"),
            error=None if ok else body.get("errorMessage") or body.get("ResponseDescription"),
        )


mpesa_client = MpesaClient()
