import uuid
from datetime import datetime, timezone

from .extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class Driver(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    full_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(32), nullable=False)
    availability_status = db.Column(db.String(32), nullable=False, default="AVAILABLE")
    transmission_certification = db.Column(db.String(16), nullable=False)
    rating = db.Column(db.Float)
    total_trips = db.Column(db.Integer, nullable=False, default=0)
    verification_status = db.Column(db.String(32), nullable=False, default="UNVERIFIED")
    last_latitude = db.Column(db.Float)
    last_longitude = db.Column(db.Float)
    location_source = db.Column(db.String(32))


class Trip(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    customer_name = db.Column(db.String(120), nullable=False)
    customer_phone = db.Column(db.String(32), nullable=False)
    car_make_model = db.Column(db.String(120), nullable=False)
    registration_plate = db.Column(db.String(32), nullable=False)
    transmission = db.Column(db.String(16), nullable=False)
    pickup_address = db.Column(db.String(255), nullable=False)
    dropoff_address = db.Column(db.String(255), nullable=False)
    pickup_latitude = db.Column(db.Float)
    pickup_longitude = db.Column(db.Float)
    dropoff_latitude = db.Column(db.Float)
    dropoff_longitude = db.Column(db.Float)
    driver_id = db.Column(db.String(36), db.ForeignKey("driver.id"), nullable=False)
    emergency_contact_name = db.Column(db.String(120), nullable=False)
    emergency_contact_phone = db.Column(db.String(32), nullable=False)
    estimated_fare = db.Column(db.Integer)
    final_fare = db.Column(db.Integer)
    status = db.Column(db.String(32), nullable=False, default="DRIVER_EN_ROUTE")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    started_at = db.Column(db.DateTime(timezone=True))
    completed_at = db.Column(db.DateTime(timezone=True))
    driver = db.relationship("Driver")
    incidents = db.relationship("SOSIncident", backref="trip", lazy=True)
    notification_records = db.relationship("NotificationAttempt", backref="trip", lazy=True)
    rating_record = db.relationship("Rating", backref="trip", uselist=False)


class SOSIncident(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    trip_id = db.Column(db.String(36), db.ForeignKey("trip.id"), nullable=False)
    trigger_reason = db.Column(db.String(255), nullable=False)
    last_latitude = db.Column(db.Float)
    last_longitude = db.Column(db.Float)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    notification_attempts = db.Column(db.JSON, nullable=False, default=list)
    dispatch_status = db.Column(db.String(32), nullable=False, default="PENDING")
    notification_records = db.relationship("NotificationAttempt", backref="incident", lazy=True)


class NotificationAttempt(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    trip_id = db.Column(db.String(36), db.ForeignKey("trip.id"), nullable=False)
    incident_id = db.Column(db.String(36), db.ForeignKey("sos_incident.id"))
    channel = db.Column(db.String(16), nullable=False)
    attempted = db.Column(db.Boolean, nullable=False)
    status = db.Column(db.String(64), nullable=False)
    provider_status = db.Column(db.String(128))
    provider_message_id = db.Column(db.String(128))
    provider_response = db.Column(db.JSON)
    detail = db.Column(db.String(500))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class Rating(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    trip_id = db.Column(db.String(36), db.ForeignKey("trip.id"), nullable=False, unique=True)
    driver_id = db.Column(db.String(36), db.ForeignKey("driver.id"), nullable=False)
    score = db.Column(db.Integer, nullable=False)
    tags = db.Column(db.JSON, nullable=False, default=list)
    comment = db.Column(db.String(500))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
