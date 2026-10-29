"""Trip lifecycle: creation, state transitions, audit trail and SMS dispatch."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Driver,
    DriverStatus,
    PaymentStatus,
    SmsLog,
    Transmission,
    Trip,
    TripEvent,
    TripStatus,
    as_utc,
)
from app.schemas import TripStartRequest
from app.services import notifications
from app.services.africastalking import sms_client
from app.services.fare import calculate_fare
from app.services.geo import minutes_for_distance, resolve_distance_km
from app.services.geo import haversine_km
from app.services.matching import ensure_driver_can_drive, get_driver

logger = logging.getLogger("ifinder.trips")

# Legal forward transitions. Anything else is a 409.
ALLOWED_TRANSITIONS: dict[TripStatus, set[TripStatus]] = {
    # COMPLETED is allowed from EN_ROUTE so ops can close out a trip the driver
    # never explicitly started (e.g. short hops or manual reconciliation).
    TripStatus.DRIVER_EN_ROUTE: {
        TripStatus.IN_PROGRESS,
        TripStatus.COMPLETED,
        TripStatus.CANCELLED,
        TripStatus.SOS,
    },
    TripStatus.IN_PROGRESS: {TripStatus.COMPLETED, TripStatus.CANCELLED, TripStatus.SOS},
    TripStatus.SOS: {TripStatus.IN_PROGRESS, TripStatus.COMPLETED, TripStatus.CANCELLED},
    TripStatus.COMPLETED: set(),
    TripStatus.CANCELLED: set(),
}


class TripNotFound(Exception):
    pass


class InvalidTransition(Exception):
    pass


def record_event(
    db: Session,
    trip: Trip,
    event_type: str,
    *,
    from_status: TripStatus | None = None,
    to_status: TripStatus | None = None,
    detail: dict | None = None,
) -> TripEvent:
    event = TripEvent(
        trip_id=trip.id,
        event_type=event_type,
        from_status=from_status.value if from_status else None,
        to_status=to_status.value if to_status else None,
        detail=detail,
    )
    db.add(event)
    return event


def transition(db: Session, trip: Trip, new_status: TripStatus, *, event_type: str, detail: dict | None = None) -> Trip:
    if new_status not in ALLOWED_TRANSITIONS.get(trip.status, set()):
        raise InvalidTransition(f"Cannot move trip {trip.id} from {trip.status.value} to {new_status.value}")
    previous = trip.status
    trip.status = new_status
    record_event(db, trip, event_type, from_status=previous, to_status=new_status, detail=detail)
    return trip


def _send_and_log_sms(
    db: Session,
    *,
    trip: Trip,
    recipient: str,
    message: str,
    kind: str,
    dedupe_key: str | None = None,
) -> SmsLog:
    """Send one SMS and persist the outcome. Never raises on provider failure."""
    existing = None
    if dedupe_key:
        existing = db.scalar(select(SmsLog).where(SmsLog.dedupe_key == dedupe_key))
        if existing is not None:
            return existing

    results = sms_client.send(message, [recipient])
    result = results[0] if results else None

    log = SmsLog(
        trip_id=trip.id,
        recipient=recipient,
        message=message,
        kind=kind,
        sent=bool(result and result.sent),
        provider=result.provider if result else "africastalking",
        provider_message_id=result.message_id if result else None,
        provider_status=result.status if result else None,
        cost=result.cost if result else None,
        error=result.error if result else "No result returned",
        dedupe_key=dedupe_key,
    )
    db.add(log)
    return log


def start_trip(db: Session, payload: TripStartRequest) -> tuple[Trip, SmsLog | None]:
    """Create the trip, mark the driver busy and alert the emergency contact."""
    driver: Driver = get_driver(db, payload.driver_id)
    ensure_driver_can_drive(driver, payload.car_details.transmission)

    distance = resolve_distance_km(
        declared_km=payload.distance_km,
        pickup=(payload.pickup_lat, payload.pickup_lng),
        dropoff=(payload.dropoff_lat, payload.dropoff_lng),
    )
    estimated_fare = calculate_fare(distance).estimated_fare if distance else None

    trip = Trip(
        user_name=payload.user_name,
        user_phone=payload.user_phone,
        car_make_model=payload.car_details.make_model,
        car_registration_plate=payload.car_details.registration_plate,
        car_transmission=payload.car_details.transmission,
        driver_id=driver.id,
        pickup_address=payload.pickup_address,
        pickup_lat=payload.pickup_lat,
        pickup_lng=payload.pickup_lng,
        dropoff_address=payload.dropoff_address,
        dropoff_lat=payload.dropoff_lat,
        dropoff_lng=payload.dropoff_lng,
        distance_km=distance,
        estimated_fare=estimated_fare,
        emergency_contact_name=payload.emergency_contact.name if payload.emergency_contact else None,
        emergency_contact_phone=payload.emergency_contact.phone if payload.emergency_contact else None,
        status=TripStatus.DRIVER_EN_ROUTE,
        payment_status=PaymentStatus.PENDING,
    )
    db.add(trip)
    db.flush()  # assign trip.id before writing events/logs

    record_event(
        db,
        trip,
        "TRIP_CREATED",
        to_status=TripStatus.DRIVER_EN_ROUTE,
        detail={"driver_id": driver.id, "estimated_fare": estimated_fare, "distance_km": distance},
    )

    driver.status = DriverStatus.ON_TRIP

    # Pickup ETA: real distance from the driver to the pickup point.
    if driver.current_lat is not None and driver.current_lng is not None and payload.pickup_lat is not None:
        approach_km = haversine_km(
            driver.current_lat, driver.current_lng, payload.pickup_lat, payload.pickup_lng
        )
        eta_minutes = minutes_for_distance(approach_km, settings.approach_speed_kmh)
    else:
        eta_minutes = 6

    sms_log: SmsLog | None = None
    if payload.emergency_contact:
        message = notifications.safety_dispatch_sms(
            user_name=payload.user_name,
            car_make_model=payload.car_details.make_model,
            plate=payload.car_details.registration_plate,
            driver_name=driver.full_name,
            driver_license=driver.ntsa_license_no,
            dropoff_address=payload.dropoff_address,
            trip_id=trip.id,
        )
        sms_log = _send_and_log_sms(
            db,
            trip=trip,
            recipient=payload.emergency_contact.phone,
            message=message,
            kind="SAFETY_DISPATCH",
            dedupe_key=f"SAFETY_DISPATCH:{trip.id}",
        )
        record_event(
            db,
            trip,
            "SAFETY_SMS_DISPATCHED",
            detail={
                "recipient": payload.emergency_contact.phone,
                "sent": sms_log.sent,
                "message_id": sms_log.provider_message_id,
            },
        )

    db.commit()
    db.refresh(trip)
    return trip, sms_log, eta_minutes


def get_trip(db: Session, trip_id: str) -> Trip:
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise TripNotFound(trip_id)
    return trip


def mark_in_progress(db: Session, trip: Trip) -> Trip:
    transition(db, trip, TripStatus.IN_PROGRESS, event_type="TRIP_STARTED")
    from app.models import utcnow

    trip.started_at = trip.started_at or utcnow()
    db.commit()
    db.refresh(trip)
    return trip


def complete_trip(
    db: Session, trip: Trip, *, actual_distance_km: float | None = None, payment_method: str = "MPESA_STK_PUSH"
) -> Trip:
    """Finalise the fare, close the trip and free the driver."""
    from app.models import utcnow

    distance = actual_distance_km or trip.distance_km
    if distance is None:
        raise ValueError("Cannot complete a trip without a distance; pass distance_km")

    final_fare = calculate_fare(distance).estimated_fare
    now = utcnow()

    trip.final_fare = final_fare
    trip.distance_km = round(distance, 3)
    trip.completed_at = now
    started_at = as_utc(trip.started_at)
    if started_at:
        trip.duration_minutes = max(1, round((now - started_at).total_seconds() / 60))
    else:
        trip.duration_minutes = calculate_fare(distance).estimated_duration_min

    trip.payment_status = PaymentStatus.CASH if payment_method == "CASH" else PaymentStatus.PENDING

    transition(
        db,
        trip,
        TripStatus.COMPLETED,
        event_type="TRIP_COMPLETED",
        detail={"final_fare": final_fare, "distance_km": trip.distance_km, "payment_method": payment_method},
    )

    if trip.driver:
        trip.driver.status = DriverStatus.AVAILABLE
        trip.driver.total_trips += 1

    db.commit()
    db.refresh(trip)
    return trip


def most_recent_trip_for_driver(db: Session, driver_id: str) -> Trip | None:
    return db.scalar(
        select(Trip).where(Trip.driver_id == driver_id).order_by(Trip.created_at.desc()).limit(1)
    )


def resolve_manual_assignment(db: Session, driver: Driver, transmission: Transmission) -> None:
    """Guard used by the ops API when a human assigns a driver."""
    ensure_driver_can_drive(driver, transmission)


__all__ = [
    "ALLOWED_TRANSITIONS",
    "InvalidTransition",
    "TripNotFound",
    "complete_trip",
    "get_trip",
    "mark_in_progress",
    "most_recent_trip_for_driver",
    "record_event",
    "resolve_manual_assignment",
    "start_trip",
    "transition",
    "settings",
]
