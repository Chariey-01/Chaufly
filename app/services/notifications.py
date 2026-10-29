"""SMS copy. Kept in one place so the hackathon demo can be tuned fast."""

from __future__ import annotations

from app.config import settings


def tracking_url(trip_id: str) -> str:
    return f"{settings.public_tracking_base}/{trip_id}"


def safety_dispatch_sms(
    *,
    user_name: str,
    car_make_model: str,
    plate: str,
    driver_name: str,
    driver_license: str | None,
    dropoff_address: str,
    trip_id: str,
) -> str:
    """Spec 3.1 — sent to the emergency contact when a trip starts."""
    licence = f" (DL: {driver_license})" if driver_license else ""
    return (
        f"{settings.app_name} Safety Alert: {user_name} has started a trip in her {car_make_model} ({plate}) "
        f"with certified driver {driver_name}{licence}. "
        f"Destination: {dropoff_address}. "
        f"Live tracking: {tracking_url(trip_id)}"
    )


def sos_sms(
    *,
    user_name: str,
    plate: str,
    lat: float,
    lng: float,
    area: str,
    driver_name: str,
    driver_phone: str,
    trip_id: str,
) -> str:
    """Spec 3.2 — high-priority SOS broadcast."""
    return (
        f"URGENT {settings.app_name} SOS: {user_name} triggered emergency assistance in car {plate}. "
        f"Last Coordinates: {lat}, {lng} (near {area}). "
        f"Driver: {driver_name} ({driver_phone}). Please call immediately. "
        f"Case: {tracking_url(trip_id)}"
    )


def trip_completed_sms(*, user_name: str, fare: float, currency: str, trip_id: str) -> str:
    return (
        f"{settings.app_name}: Trip {trip_id} complete. Final fare {currency} {fare:,.2f}. "
        "Thank you for driving safely with us."
    )


def payment_receipt_sms(*, fare: float, currency: str, receipt: str, trip_id: str) -> str:
    return (
        f"{settings.app_name}: Payment received {currency} {fare:,.2f} for {trip_id}. "
        f"M-Pesa receipt {receipt}. Asante!"
    )
