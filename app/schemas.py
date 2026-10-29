"""Pydantic request/response contracts, matching the API specification."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

from app.models import DriverStatus, PaymentStatus, Transmission, TransmissionCertification, TripStatus


def _serialise_utc(value: datetime) -> str:
    """Always emit an explicit UTC marker, e.g. 2026-10-29T12:05:00Z."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


# Use for every datetime we expose over the wire.
UtcDatetime = Annotated[datetime, PlainSerializer(_serialise_utc, return_type=str)]

# Kenyan MSISDN: +2547XXXXXXXX / +2541XXXXXXXX, or 07XXXXXXXX / 01XXXXXXXX
KE_PHONE_PATTERN = r"^(\+254|0)[17]\d{8}$"


def normalise_phone(value: str) -> str:
    """Normalise Kenyan numbers to E.164 (+2547XXXXXXXX)."""
    digits = "".join(ch for ch in value if ch.isdigit() or ch == "+")
    if digits.startswith("+"):
        return digits
    if digits.startswith("254"):
        return f"+{digits}"
    if digits.startswith("0"):
        return f"+254{digits[1:]}"
    return f"+254{digits}"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------------
# Quote
# ---------------------------------------------------------------------------
class Location(StrictModel):
    address: str = Field(min_length=1, max_length=255)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)


class QuoteRequest(StrictModel):
    pickup: Location
    dropoff: Location
    distance_km: float = Field(gt=0, le=2000)
    car_transmission: Transmission


class QuoteResponse(BaseModel):
    currency: str
    distance_km: float
    base_fare: float
    per_km_rate: float
    estimated_fare: float
    estimated_duration_min: int
    quote_expires_in_sec: int


# ---------------------------------------------------------------------------
# Driver matching
# ---------------------------------------------------------------------------
class MatchRequest(StrictModel):
    car_transmission: Transmission
    pickup_lat: float = Field(ge=-90, le=90)
    pickup_lng: float = Field(ge=-180, le=180)
    radius_km: float = Field(default=5.0, gt=0, le=50)


class Qualifications(BaseModel):
    dci_good_conduct_verified: bool
    dci_certificate_ref: str | None = None
    ntsa_license_no: str | None = None


class MatchedDriver(BaseModel):
    driver_id: str
    full_name: str
    phone: str
    rating: float
    total_trips: int
    photo_url: str | None = None
    transmission_certified: TransmissionCertification
    qualifications: Qualifications
    eta_minutes: int
    current_distance_km: float


class MatchResponse(BaseModel):
    matched_driver: MatchedDriver


# ---------------------------------------------------------------------------
# Trip start
# ---------------------------------------------------------------------------
class CarDetails(StrictModel):
    make_model: str = Field(min_length=1, max_length=120)
    registration_plate: str = Field(min_length=1, max_length=20)
    transmission: Transmission


class EmergencyContact(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str

    @field_validator("phone")
    @classmethod
    def _normalise(cls, v: str) -> str:
        return normalise_phone(v)


class TripStartRequest(StrictModel):
    user_name: str = Field(min_length=1, max_length=120)
    user_phone: str
    car_details: CarDetails
    driver_id: str
    pickup_address: str = Field(min_length=1, max_length=255)
    dropoff_address: str = Field(min_length=1, max_length=255)
    pickup_lat: float | None = Field(default=None, ge=-90, le=90)
    pickup_lng: float | None = Field(default=None, ge=-180, le=180)
    dropoff_lat: float | None = Field(default=None, ge=-90, le=90)
    dropoff_lng: float | None = Field(default=None, ge=-180, le=180)
    distance_km: float | None = Field(default=None, gt=0, le=2000)
    emergency_contact: EmergencyContact | None = None

    @field_validator("user_phone")
    @classmethod
    def _normalise(cls, v: str) -> str:
        return normalise_phone(v)


class TripDriverSummary(BaseModel):
    name: str
    phone: str
    eta_minutes: int


class AtSmsDispatch(BaseModel):
    sent: bool
    recipient: str | None = None
    message_id: str | None = None
    cost: str | None = None
    error: str | None = None


class TripStartResponse(BaseModel):
    trip_id: str
    status: TripStatus
    driver: TripDriverSummary
    at_sms_dispatch: AtSmsDispatch
    created_at: UtcDatetime


class TripRideStartedResponse(BaseModel):
    """Driver arrived; the ride is now underway."""

    trip_id: str
    status: TripStatus
    started_at: UtcDatetime


# ---------------------------------------------------------------------------
# SOS
# ---------------------------------------------------------------------------
class SosRequest(StrictModel):
    current_lat: float = Field(ge=-90, le=90)
    current_lng: float = Field(ge=-180, le=180)
    trigger_reason: str = Field(default="PASSENGER_TRIGGERED_SOS", max_length=64)


class SosResponse(BaseModel):
    status: str
    timestamp: UtcDatetime
    sms_dispatched_to: list[str]
    at_voice_alert_queued: bool
    incident_ticket_id: str


# ---------------------------------------------------------------------------
# Completion & payment
# ---------------------------------------------------------------------------
class TripCompleteRequest(StrictModel):
    """Optional body: override the distance actually driven."""

    distance_km: float | None = Field(default=None, gt=0, le=2000)
    payment_method: Literal["MPESA_STK_PUSH", "CASH"] = "MPESA_STK_PUSH"


class TripCompleteResponse(BaseModel):
    trip_id: str
    status: TripStatus
    final_fare: float
    currency: str
    duration_minutes: int
    payment_options: list[str]
    payment_status: PaymentStatus
    mpesa_checkout_request_id: str | None = None
    mpesa_error: str | None = None
    completed_at: UtcDatetime


class MpesaCallbackAck(BaseModel):
    ResultCode: int
    ResultDesc: str

    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Rating
# ---------------------------------------------------------------------------
class RatingRequest(StrictModel):
    rating: int = Field(ge=1, le=5)
    tags: list[str] = Field(default_factory=list, max_length=10)
    feedback_comment: str | None = Field(default=None, max_length=1000)


class RatingResponse(BaseModel):
    success: bool
    trip_id: str
    driver_id: str
    new_driver_average_rating: float


# ---------------------------------------------------------------------------
# Ops / admin read models
# ---------------------------------------------------------------------------
class TripEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_type: str
    from_status: str | None = None
    to_status: str | None = None
    detail: dict | None = None
    created_at: UtcDatetime


class SmsLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    recipient: str
    kind: str
    sent: bool
    provider_message_id: str | None = None
    provider_status: str | None = None
    cost: str | None = None
    error: str | None = None
    created_at: UtcDatetime


class TripDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: TripStatus
    user_name: str
    user_phone: str
    car_make_model: str
    car_registration_plate: str
    car_transmission: Transmission
    pickup_address: str
    dropoff_address: str
    distance_km: float | None = None
    estimated_fare: float | None = None
    final_fare: float | None = None
    currency: str
    payment_status: PaymentStatus
    driver_id: str | None = None
    created_at: UtcDatetime
    started_at: UtcDatetime | None = None
    completed_at: UtcDatetime | None = None
    duration_minutes: int | None = None
    events: list[TripEventOut] = Field(default_factory=list)
    sms_logs: list[SmsLogOut] = Field(default_factory=list)


class TripListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: TripStatus
    user_name: str
    driver_id: str | None = None
    payment_status: PaymentStatus
    estimated_fare: float | None = None
    final_fare: float | None = None
    created_at: UtcDatetime


class DriverOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    full_name: str
    phone: str
    rating: float
    total_trips: int
    transmission_certified: TransmissionCertification
    status: DriverStatus
    dci_good_conduct_verified: bool
    ntsa_license_no: str | None = None
    current_lat: float | None = None
    current_lng: float | None = None


class DriverCreate(StrictModel):
    full_name: str = Field(min_length=1, max_length=120)
    phone: str
    email: str | None = None
    photo_url: str | None = None
    transmission_certified: TransmissionCertification = TransmissionCertification.MANUAL_AND_AUTO
    dci_good_conduct_verified: bool = False
    dci_certificate_ref: str | None = None
    ntsa_license_no: str | None = None
    current_lat: float | None = Field(default=None, ge=-90, le=90)
    current_lng: float | None = Field(default=None, ge=-180, le=180)

    @field_validator("phone")
    @classmethod
    def _normalise(cls, v: str) -> str:
        return normalise_phone(v)


class HealthResponse(BaseModel):
    status: str
    app: str
    environment: str
    database: str
    at_enabled: bool


# ---------------------------------------------------------------------------
# Public tracking (unauthenticated — linked from the safety SMS)
# ---------------------------------------------------------------------------
class PublicTripEvent(BaseModel):
    """Event shape for the public page.

    Deliberately drops ``detail``. Event details are an internal audit blob and
    can carry phone numbers (e.g. the SAFETY_SMS_DISPATCHED recipient), which
    must never reach an unauthenticated caller.
    """

    model_config = ConfigDict(from_attributes=True)

    event_type: str
    created_at: UtcDatetime


class PublicTripStatus(BaseModel):
    """Deliberately narrow.

    This payload is served to anyone holding the tracking URL, which travels by
    plain SMS and can be forwarded. So: no customer phone, no driver phone, no
    exact coordinates, no fare breakdown. Enough for a worried relative to see
    that the trip exists and is progressing — nothing more.
    """

    trip_id: str
    status: TripStatus
    customer_first_name: str
    driver_first_name: str | None = None
    driver_rating: float | None = None
    driver_total_trips: int | None = None
    driver_certified_manual: bool | None = None
    vehicle: str
    destination: str
    is_emergency: bool
    payment_status: PaymentStatus
    created_at: UtcDatetime
    started_at: UtcDatetime | None = None
    completed_at: UtcDatetime | None = None
    driver_eta_minutes: int | None = None
    last_event: str | None = None
    last_event_at: UtcDatetime | None = None
    events: list[PublicTripEvent] = Field(default_factory=list)
