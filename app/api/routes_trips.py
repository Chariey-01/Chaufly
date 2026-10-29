"""Trip lifecycle endpoints: start, start-ride, complete, SOS, rate."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Trip, TripStatus, as_utc, utcnow
from app.schemas import (
    AtSmsDispatch,
    RatingRequest,
    RatingResponse,
    SosRequest,
    SosResponse,
    TripCompleteRequest,
    TripCompleteResponse,
    TripDriverSummary,
    TripRideStartedResponse,
    TripStartRequest,
    TripStartResponse,
)
from app.services import notifications
from app.services.africastalking import sms_client
from app.services.matching import DriverNotFound, DriverUnavailable
from app.services.mpesa import mpesa_client
from app.services.ratings import AlreadyRated, RatingNotAllowed, rate_trip
from app.services.sos import SosNotAllowed, trigger_sos
from app.services.trips import (
    InvalidTransition,
    TripNotFound,
    complete_trip,
    mark_in_progress,
    start_trip,
)

router = APIRouter(tags=["trips"])


def _load_trip_or_404(db: Session, trip_id: str) -> Trip:
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Trip {trip_id} not found")
    return trip


@router.post("/trips/start", response_model=TripStartResponse, status_code=status.HTTP_201_CREATED)
def create_trip(payload: TripStartRequest, db: Session = Depends(get_db)) -> TripStartResponse:
    try:
        trip, sms_log, eta_minutes = start_trip(db, payload)
    except DriverNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Driver {payload.driver_id} not found"
        ) from None
    except DriverUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None

    driver = trip.driver
    return TripStartResponse(
        trip_id=trip.id,
        status=trip.status,
        driver=TripDriverSummary(
            name=driver.full_name if driver else "Unknown",
            phone=driver.phone if driver else "",
            eta_minutes=eta_minutes,
        ),
        at_sms_dispatch=AtSmsDispatch(
            sent=bool(sms_log and sms_log.sent),
            recipient=sms_log.recipient if sms_log else None,
            message_id=sms_log.provider_message_id if sms_log else None,
            cost=sms_log.cost if sms_log else None,
            error=sms_log.error if sms_log else None,
        ),
        created_at=trip.created_at,
    )


@router.post("/trips/{trip_id}/start", response_model=TripRideStartedResponse)
def begin_ride(trip_id: str, db: Session = Depends(get_db)) -> TripRideStartedResponse:
    """Driver has arrived and the ride is underway (DRIVER_EN_ROUTE -> IN_PROGRESS)."""
    trip = _load_trip_or_404(db, trip_id)
    try:
        mark_in_progress(db, trip)
    except InvalidTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    return TripRideStartedResponse(
        trip_id=trip.id, status=trip.status, started_at=as_utc(trip.started_at) or utcnow()
    )


@router.post("/trips/{trip_id}/sos", response_model=SosResponse, status_code=status.HTTP_200_OK)
def sos(trip_id: str, payload: SosRequest, db: Session = Depends(get_db)) -> SosResponse:
    trip = _load_trip_or_404(db, trip_id)
    try:
        incident, sms_logs, voice_log = trigger_sos(
            db,
            trip,
            lat=payload.current_lat,
            lng=payload.current_lng,
            trigger_reason=payload.trigger_reason,
        )
    except SosNotAllowed as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None

    dispatched = [log.recipient for log in sms_logs if log.sent]
    return SosResponse(
        status="EMERGENCY_BROADCAST_SENT" if dispatched else "EMERGENCY_BROADCAST_FAILED",
        timestamp=incident.created_at,
        sms_dispatched_to=dispatched,
        at_voice_alert_queued=bool(voice_log and voice_log.queued),
        incident_ticket_id=incident.id,
    )


@router.post("/trips/{trip_id}/complete", response_model=TripCompleteResponse, status_code=status.HTTP_200_OK)
def finish_trip(
    trip_id: str, payload: TripCompleteRequest | None = None, db: Session = Depends(get_db)
) -> TripCompleteResponse:
    trip = _load_trip_or_404(db, trip_id)
    body = payload or TripCompleteRequest()

    try:
        complete_trip(
            db, trip, actual_distance_km=body.distance_km, payment_method=body.payment_method
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    except InvalidTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None

    checkout_id: str | None = None
    mpesa_error: str | None = None

    if body.payment_method == "MPESA_STK_PUSH":
        result = mpesa_client.stk_push(
            phone=trip.user_phone,
            amount=trip.final_fare or 0.0,
            account_ref=trip.id.replace("-", ""),
            description=f"{notifications.settings.app_name} chauffeur trip",
        )
        if result.requested:
            checkout_id = result.checkout_request_id
            trip.mpesa_checkout_request_id = checkout_id
            db.commit()
        else:
            mpesa_error = result.error

    return TripCompleteResponse(
        trip_id=trip.id,
        status=trip.status,
        final_fare=trip.final_fare or 0.0,
        currency=trip.currency,
        duration_minutes=trip.duration_minutes or 0,
        payment_options=["MPESA_STK_PUSH", "CASH"],
        payment_status=trip.payment_status,
        mpesa_checkout_request_id=checkout_id,
        mpesa_error=mpesa_error,
        completed_at=trip.completed_at or utcnow(),
    )


@router.post("/trips/{trip_id}/rate", response_model=RatingResponse, status_code=status.HTTP_200_OK)
def rate(trip_id: str, payload: RatingRequest, db: Session = Depends(get_db)) -> RatingResponse:
    trip = _load_trip_or_404(db, trip_id)
    try:
        _record, new_average = rate_trip(
            db,
            trip,
            rating=payload.rating,
            tags=payload.tags,
            feedback_comment=payload.feedback_comment,
        )
    except RatingNotAllowed as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except AlreadyRated as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None

    return RatingResponse(
        success=True,
        trip_id=trip.id,
        driver_id=trip.driver_id,
        new_driver_average_rating=new_authoritative(new_average),
    )


def new_authoritative(value: float) -> float:
    return round(float(value), 2)


@router.post("/trips/{trip_id}/cancel", status_code=status.HTTP_200_OK, tags=["trips"])
def cancel_trip(trip_id: str, db: Session = Depends(get_db)) -> dict:
    from app.models import DriverStatus
    from app.services.trips import transition

    trip = _load_trip_or_404(db, trip_id)
    try:
        transition(db, trip, TripStatus.CANCELLED, event_type="TRIP_CANCELLED")
    except InvalidTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None

    if trip.driver:
        trip.driver.status = DriverStatus.AVAILABLE
    db.commit()
    return {"trip_id": trip.id, "status": trip.status.value}


# Re-exported so tests can import without touching services.
__all__ = ["router", "TripNotFound"]
