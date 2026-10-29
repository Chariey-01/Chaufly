"""M-Pesa Daraja callback and payment simulation endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PaymentStatus, SmsLog, Trip
from app.services import notifications
from app.services.africastalking import sms_client

logger = logging.getLogger("ifinder.mpesa.callback")

router = APIRouter(tags=["payments"])


@router.post("/mpesa/callback", status_code=status.HTTP_200_OK)
def mpesa_callback(payload: dict, db: Session = Depends(get_db)) -> dict:
    """Daraja posts here after the customer completes (or fails) the STK prompt.

    Daraja always expects a 200 with ResultCode/ResultDesc, otherwise it retries.
    """
    body = payload.get("Body", {}) or {}
    stk = body.get("stkCallback", {}) or {}

    checkout_id = stk.get("CheckoutRequestID")
    result_code = stk.get("ResultCode")
    result_desc = stk.get("ResultDesc", "")

    if not checkout_id:
        logger.warning("M-Pesa callback missing CheckoutRequestID: %s", payload)
        return {"ResultCode": 0, "ResultDesc": "Accepted"}

    trip = db.scalar(select(Trip).where(Trip.mpesa_checkout_request_id == checkout_id))
    if trip is None:
        logger.warning("M-Pesa callback for unknown checkout id %s", checkout_id)
        return {"ResultCode": 0, "ResultDesc": "Accepted"}

    items = {item.get("Name"): item.get("Value") for item in (stk.get("CallbackMetadata") or {}).get("Item", [])}
    receipt = items.get("MpesaReceiptNumber")
    paid_amount = items.get("Amount")

    if str(result_code) == "0":
        trip.payment_status = PaymentStatus.PAID
        trip.mpesa_receipt = receipt
        message = notifications.payment_receipt_sms(
            fare=float(paid_amount or trip.final_fare or 0),
            currency=trip.currency,
            receipt=str(receipt or "N/A"),
            trip_id=trip.id,
        )
    else:
        trip.payment_status = PaymentStatus.FAILED
        message = f"{notifications.settings.app_name}: Payment for {trip.id} failed ({result_desc}). Please retry."

    from app.models import utcnow
    from app.services.trips import record_event

    record_event(
        db,
        trip,
        "PAYMENT_CALLBACK",
        detail={"result_code": result_code, "result_desc": result_desc, "receipt": receipt, "amount": paid_amount},
    )

    results = sms_client.send(message, [trip.user_phone])
    result = results[0] if results else None
    db.add(
        SmsLog(
            trip_id=trip.id,
            recipient=trip.user_phone,
            message=message,
            kind="PAYMENT_RESULT",
            sent=bool(result and result.sent),
            provider=result.provider if result else "africastalking",
            provider_message_id=result.message_id if result else None,
            provider_status=result.status if result else None,
            cost=result.cost if result else None,
            error=result.error if result else None,
            dedupe_key=f"PAYMENT_RESULT:{trip.id}",
        )
    )

    db.commit()
    return {"ResultCode": 0, "ResultDesc": "Accepted"}


@router.post("/trips/{trip_id}/pay/cash", status_code=status.HTTP_200_OK)
def mark_cash_paid(trip_id: str, db: Session = Depends(get_db)) -> dict:
    """Ops confirms the driver collected cash."""
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Trip {trip_id} not found")
    trip.payment_status = PaymentStatus.CASH
    db.commit()
    return {"trip_id": trip.id, "payment_status": trip.payment_status.value}
