import math
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request, send_from_directory
from sqlalchemy import select

from .extensions import db
from .models import Driver, Rating, SOSIncident, Trip
from .services import notifications, routing
from .services.trips import can_drive, transition
from .validation import ValidationError, coordinates, payload, phone, required, transmission

api = Blueprint("api", __name__)
web = Blueprint("web", __name__)


@web.get("/")
def index():
    return send_from_directory("static", "index.html")


def error(code, message, status, fields=None):
    body = {"error": {"code": code, "message": message}}
    if fields:
        body["error"]["fields"] = fields
    return jsonify(body), status


@api.errorhandler(ValidationError)
def validation_error(exc):
    return error("VALIDATION_ERROR", exc.message, 400, exc.fields)


@api.get("/health")
def health():
    return jsonify({"status": "ok"})


@api.post("/quote")
def quote():
    data = payload(request)
    required(data, ["pickup_address", "dropoff_address", "transmission"])
    transmission(data["transmission"])
    try:
        route = routing.get_route(data["pickup_address"], data["dropoff_address"])
    except routing.RoutingUnavailable as exc:
        return error("ROUTING_UNAVAILABLE", str(exc), 503)
    return jsonify({"quote": routing.quote_from_route(route)})


def _distance_km(a, b):
    radius = 6371
    lat1, lon1, lat2, lon2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    return radius * 2 * math.asin(math.sqrt(math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2))


@api.post("/drivers/match")
def match_drivers():
    data = payload(request)
    required(data, ["transmission"])
    transmission(data["transmission"])
    pickup = coordinates(data, "pickup_")
    if pickup is None:
        return error("LOCATION_REQUIRED", "A user-permitted or explicitly selected pickup coordinate is required for radius matching.", 400)
    try:
        radius_km = float(data.get("radius_km", 15))
        if radius_km <= 0:
            raise ValueError
    except (TypeError, ValueError):
        raise ValidationError("Validation failed.", {"radius_km": "Must be a positive number."})
    drivers = db.session.scalars(select(Driver).where(Driver.availability_status == "AVAILABLE")).all()
    matches = []
    for driver in drivers:
        if not can_drive(driver.transmission_certification, data["transmission"]):
            continue
        if driver.last_latitude is None or driver.last_longitude is None:
            continue
        distance = _distance_km(pickup, (driver.last_latitude, driver.last_longitude))
        if distance <= radius_km:
            matches.append({"id": driver.id, "full_name": driver.full_name,
                            "transmission_certification": driver.transmission_certification,
                            "verification_status": driver.verification_status,
                            "location_source": driver.location_source,
                            "distance_km": round(distance, 2)})
    return jsonify({"drivers": matches, "match_status": "MATCHED" if matches else "NO_MATCH"})


def _serialize_trip(trip):
    return {"id": trip.id, "status": trip.status, "customer_name": trip.customer_name,
            "car_make_model": trip.car_make_model, "registration_plate": trip.registration_plate,
            "transmission": trip.transmission, "pickup_address": trip.pickup_address,
            "dropoff_address": trip.dropoff_address, "estimated_fare": trip.estimated_fare,
            "final_fare": trip.final_fare, "currency": "KES",
            "driver": {"id": trip.driver.id, "full_name": trip.driver.full_name,
                       "transmission_certification": trip.driver.transmission_certification,
                       "verification_status": trip.driver.verification_status},
            "created_at": trip.created_at.isoformat(),
            "started_at": trip.started_at.isoformat() if trip.started_at else None,
            "completed_at": trip.completed_at.isoformat() if trip.completed_at else None}


def _actual_duration_minutes(trip):
    if not trip.started_at or not trip.completed_at:
        return None
    seconds = (trip.completed_at - trip.started_at).total_seconds()
    return max(0, math.ceil(seconds / 60))


@api.post("/trips/start")
def start_trip():
    data = payload(request)
    fields = ["customer_name", "customer_phone", "pickup_address", "dropoff_address", "car_make_model",
              "registration_plate", "transmission", "emergency_contact_name", "emergency_contact_phone", "driver_id"]
    required(data, fields)
    phone(data["customer_phone"], "customer_phone")
    phone(data["emergency_contact_phone"], "emergency_contact_phone")
    transmission(data["transmission"])
    driver = db.session.get(Driver, data["driver_id"])
    if not driver or driver.availability_status != "AVAILABLE" or not can_drive(driver.transmission_certification, data["transmission"]):
        return error("DRIVER_UNAVAILABLE", "The selected driver is unavailable or incompatible.", 409)
    # A fare can only be attached by a future persisted quote from a routing provider.
    # Client-supplied numbers are intentionally not treated as a quote.
    trip = Trip(**{key: data[key] for key in fields if key != "driver_id"}, driver_id=driver.id,
                status="DRIVER_EN_ROUTE")
    db.session.add(trip)
    db.session.commit()  # Persist before notification attempts.
    message = f"Chaufly trip {trip.id}: {trip.customer_name} is travelling in {trip.car_make_model} ({trip.registration_plate}) with {driver.full_name} to {trip.dropoff_address}."
    sms = notifications.send_sms([trip.emergency_contact_phone], message)
    return jsonify({"trip": _serialize_trip(trip), "notifications": [sms.serialize()]}), 201


def _trip_or_error(trip_id):
    trip = db.session.get(Trip, trip_id)
    return trip


@api.get("/trips/<trip_id>")
def get_trip(trip_id):
    trip = _trip_or_error(trip_id)
    if not trip:
        return error("NOT_FOUND", "Trip not found.", 404)
    return jsonify({"trip": _serialize_trip(trip)})


@api.patch("/trips/<trip_id>/status")
def update_status(trip_id):
    trip = _trip_or_error(trip_id)
    if not trip:
        return error("NOT_FOUND", "Trip not found.", 404)
    data = payload(request)
    required(data, ["status"])
    try:
        transition(trip, data["status"])
    except ValueError as exc:
        return error("INVALID_STATUS_TRANSITION", str(exc), 409)
    db.session.commit()
    return jsonify({"trip": _serialize_trip(trip)})


@api.post("/trips/<trip_id>/sos")
def sos(trip_id):
    trip = _trip_or_error(trip_id)
    if not trip:
        return error("NOT_FOUND", "Trip not found.", 404)
    data = payload(request)
    required(data, ["trigger_reason"])
    location = coordinates(data, "last_")
    try:
        transition(trip, "SOS_TRIGGERED")
    except ValueError as exc:
        return error("INVALID_STATUS_TRANSITION", str(exc), 409)
    incident = SOSIncident(trip=trip, trigger_reason=data["trigger_reason"],
                           last_latitude=location[0] if location else None,
                           last_longitude=location[1] if location else None)
    db.session.add(incident)
    db.session.commit()
    recipients = [trip.emergency_contact_phone] + [p.strip() for p in current_app.config.get("OPERATIONS_ALERT_RECIPIENTS", "").split(",") if p.strip()]
    message = f"Chaufly SOS {incident.id} for trip {trip.id}. Reason: {incident.trigger_reason}."
    attempts = [notifications.send_sms(recipients, message).serialize(), notifications.queue_voice_alert(trip.emergency_contact_phone, message).serialize()]
    incident.notification_attempts = attempts
    incident.dispatch_status = "ALERTS_ATTEMPTED"
    db.session.commit()
    return jsonify({"incident": {"id": incident.id, "trip_id": trip.id, "created_at": incident.created_at.isoformat(),
                                  "dispatch_status": incident.dispatch_status, "notification_attempts": attempts}}), 201


@api.post("/trips/<trip_id>/complete")
def complete_trip(trip_id):
    trip = _trip_or_error(trip_id)
    if not trip:
        return error("NOT_FOUND", "Trip not found.", 404)
    try:
        transition(trip, "COMPLETED")
    except ValueError as exc:
        return error("INVALID_STATUS_TRANSITION", str(exc), 409)
    trip.final_fare = trip.estimated_fare
    db.session.commit()
    return jsonify({"trip": _serialize_trip(trip), "duration_minutes": _actual_duration_minutes(trip),
                    "payment_options": ["Pay on completion (not processed by Chaufly MVP)"],
                    "payment_status": "NOT_PROCESSED"})


@api.post("/trips/<trip_id>/rate")
def rate_trip(trip_id):
    trip = _trip_or_error(trip_id)
    if not trip:
        return error("NOT_FOUND", "Trip not found.", 404)
    data = payload(request)
    try:
        score = int(data.get("score"))
    except (TypeError, ValueError):
        score = 0
    if trip.status != "COMPLETED":
        return error("RATING_NOT_ALLOWED", "Ratings are only accepted for completed trips.", 409)
    if score not in range(1, 6):
        raise ValidationError("Validation failed.", {"score": "Must be an integer from 1 to 5."})
    if trip.rating_record:
        return error("RATING_EXISTS", "A rating already exists for this trip.", 409)
    rating = Rating(trip_id=trip.id, driver_id=trip.driver_id, score=score, tags=data.get("tags", []), comment=data.get("comment"))
    db.session.add(rating)
    db.session.commit()
    return jsonify({"rating": {"id": rating.id, "score": rating.score}}), 201
