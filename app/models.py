"""ORM models for the iFinder dial-a-driver MVP."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """Coerce a datetime to timezone-aware UTC.

    SQLite drops tzinfo on round-trip, so values read back from the database can
    be naive even though they were written as aware. Normalise on use.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _id(prefix: str, length: int = 6) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:length].upper()}"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class Transmission(str, enum.Enum):
    MANUAL = "MANUAL"
    AUTOMATIC = "AUTOMATIC"


class TransmissionCertification(str, enum.Enum):
    MANUAL_AND_AUTO = "MANUAL_AND_AUTO"
    AUTO_ONLY = "AUTO_ONLY"

    def can_drive(self, transmission: Transmission | str) -> bool:
        """Manual-certified drivers handle both; auto-only drivers handle automatic only."""
        needed = Transmission(transmission)
        if self is TransmissionCertification.MANUAL_AND_AUTO:
            return True
        return needed is Transmission.AUTOMATIC


class DriverStatus(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    ON_TRIP = "ON_TRIP"
    OFFLINE = "OFFLINE"
    SUSPENDED = "SUSPENDED"


class TripStatus(str, enum.Enum):
    DRIVER_EN_ROUTE = "DRIVER_EN_ROUTE"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    SOS = "SOS"


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    REQUESTED = "REQUESTED"
    PAID = "PAID"
    FAILED = "FAILED"
    CASH = "CASH"


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=lambda: _id("drv", 4))
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(String(120))

    rating: Mapped[float] = mapped_column(Float, default=5.0, nullable=False)
    total_trips: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rating_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rating_sum: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    photo_url: Mapped[str | None] = mapped_column(String(255))
    transmission_certified: Mapped[TransmissionCertification] = mapped_column(
        Enum(TransmissionCertification, native_enum=False, length=20),
        default=TransmissionCertification.MANUAL_AND_AUTO,
        nullable=False,
    )

    dci_good_conduct_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    dci_certificate_ref: Mapped[str | None] = mapped_column(String(64))
    ntsa_license_no: Mapped[str | None] = mapped_column(String(64))

    status: Mapped[DriverStatus] = mapped_column(
        Enum(DriverStatus, native_enum=False, length=20), default=DriverStatus.AVAILABLE, nullable=False
    )
    # Last known position, updated by the driver app / ops console.
    current_lat: Mapped[float | None] = mapped_column(Float)
    current_lng: Mapped[float | None] = mapped_column(Float)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    trips: Mapped[list[Trip]] = relationship(back_populates="driver")


# ---------------------------------------------------------------------------
# Trip
# ---------------------------------------------------------------------------
class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=lambda: _id("TRP"))

    user_name: Mapped[str] = mapped_column(String(120), nullable=False)
    user_phone: Mapped[str] = mapped_column(String(20), nullable=False)

    car_make_model: Mapped[str] = mapped_column(String(120), nullable=False)
    car_registration_plate: Mapped[str] = mapped_column(String(20), nullable=False)
    car_transmission: Mapped[Transmission] = mapped_column(
        Enum(Transmission, native_enum=False, length=20), nullable=False
    )

    driver_id: Mapped[str | None] = mapped_column(ForeignKey("drivers.id"), index=True)

    pickup_address: Mapped[str] = mapped_column(String(255), nullable=False)
    pickup_lat: Mapped[float | None] = mapped_column(Float)
    pickup_lng: Mapped[float | None] = mapped_column(Float)
    dropoff_address: Mapped[str] = mapped_column(String(255), nullable=False)
    dropoff_lat: Mapped[float | None] = mapped_column(Float)
    dropoff_lng: Mapped[float | None] = mapped_column(Float)

    distance_km: Mapped[float | None] = mapped_column(Float)
    estimated_fare: Mapped[float | None] = mapped_column(Float)
    final_fare: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="KES", nullable=False)

    emergency_contact_name: Mapped[str | None] = mapped_column(String(120))
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(20))

    status: Mapped[TripStatus] = mapped_column(
        Enum(TripStatus, native_enum=False, length=20),
        default=TripStatus.DRIVER_EN_ROUTE,
        nullable=False,
        index=True,
    )

    payment_status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, native_enum=False, length=20), default=PaymentStatus.PENDING, nullable=False
    )
    mpesa_checkout_request_id: Mapped[str | None] = mapped_column(String(64))
    mpesa_receipt: Mapped[str | None] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_minutes: Mapped[int | None] = mapped_column(Integer)

    driver: Mapped[Driver | None] = relationship(back_populates="trips")
    events: Mapped[list[TripEvent]] = relationship(
        back_populates="trip", cascade="all, delete-orphan", order_by="TripEvent.id"
    )
    ratings: Mapped[list[Rating]] = relationship(back_populates="trip", cascade="all, delete-orphan")
    sos_incidents: Mapped[list[SosIncident]] = relationship(back_populates="trip", cascade="all, delete-orphan")


class TripEvent(Base):
    """Append-only audit trail of every trip state change."""

    __tablename__ = "trip_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id"), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str | None] = mapped_column(String(32))
    detail: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    trip: Mapped[Trip] = relationship(back_populates="events")


# ---------------------------------------------------------------------------
# SMS / Voice logs
# ---------------------------------------------------------------------------
class SmsLog(Base):
    __tablename__ = "sms_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_id: Mapped[str | None] = mapped_column(ForeignKey("trips.id"), index=True)
    recipient: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), default="africastalking", nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(128))
    provider_status: Mapped[str | None] = mapped_column(String(32))
    cost: Mapped[str | None] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str | None] = mapped_column(String(128), unique=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class VoiceLog(Base):
    __tablename__ = "voice_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_id: Mapped[str | None] = mapped_column(ForeignKey("trips.id"), index=True)
    recipient: Mapped[str] = mapped_column(String(20), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    queued: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    provider_call_id: Mapped[str | None] = mapped_column(String(128))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


# ---------------------------------------------------------------------------
# SOS
# ---------------------------------------------------------------------------
class SosIncident(Base):
    __tablename__ = "sos_incidents"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=lambda: _id("SOS", 5))
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id"), index=True, nullable=False)
    trigger_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    current_lat: Mapped[float | None] = mapped_column(Float)
    current_lng: Mapped[float | None] = mapped_column(Float)
    sms_dispatched_to: Mapped[list | None] = mapped_column(JSON)
    voice_alert_queued: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    trip: Mapped[Trip] = relationship(back_populates="sos_incidents")


# ---------------------------------------------------------------------------
# Rating
# ---------------------------------------------------------------------------
class Rating(Base):
    __tablename__ = "ratings"
    __table_args__ = (UniqueConstraint("trip_id", name="uq_rating_trip"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id"), index=True, nullable=False)
    driver_id: Mapped[str] = mapped_column(ForeignKey("drivers.id"), index=True, nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    tags: Mapped[list | None] = mapped_column(JSON)
    feedback_comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    trip: Mapped[Trip] = relationship(back_populates="ratings")
    driver: Mapped[Driver] = relationship()
