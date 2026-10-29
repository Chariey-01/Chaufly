"""Trip lifecycle: start, begin, complete, rate, cancel."""

from __future__ import annotations


def test_start_trip_creates_record_and_alerts_contact(client, drivers, trip_payload):
    response = client.post("/api/trips/start", json=trip_payload)
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["trip_id"].startswith("TRP-")
    assert body["status"] == "DRIVER_EN_ROUTE"
    assert body["driver"]["name"] == drivers["manual"].full_name
    assert body["at_sms_dispatch"]["sent"] is True
    assert body["at_sms_dispatch"]["recipient"] == "+254711223344"


def test_start_trip_marks_driver_on_trip(client, drivers, trip_payload, db_session):
    client.post("/api/trips/start", json=trip_payload)
    db_session.expire_all()
    refreshed = db_session.get(type(drivers["manual"]), drivers["manual"].id)
    assert refreshed.status.value == "ON_TRIP"


def test_start_trip_rejects_manual_car_with_auto_only_driver(client, drivers, trip_payload):
    payload = dict(trip_payload, driver_id=drivers["auto_only"].id)
    response = client.post("/api/trips/start", json=payload)
    assert response.status_code == 409
    assert "certified" in response.json()["detail"].lower()


def test_start_trip_rejects_unverified_driver(client, drivers, trip_payload):
    payload = dict(trip_payload, driver_id=drivers["unverified"].id)
    response = client.post("/api/trips/start", json=payload)
    assert response.status_code == 409
    assert "dci" in response.json()["detail"].lower()


def test_start_trip_unknown_driver_404(client, trip_payload):
    payload = dict(trip_payload, driver_id="drv-NOPE")
    response = client.post("/api/trips/start", json=payload)
    assert response.status_code == 404


def test_start_trip_without_emergency_contact(client, drivers, trip_payload):
    payload = dict(trip_payload, emergency_contact=None)
    response = client.post("/api/trips/start", json=payload)
    assert response.status_code == 201
    assert response.json()["at_sms_dispatch"]["sent"] is False


def test_phone_normalisation_on_start(client, drivers, trip_payload):
    payload = dict(trip_payload, user_phone="0700000001")
    payload["emergency_contact"] = {"name": "Grace", "phone": "0711223344"}
    response = client.post("/api/trips/start", json=payload)
    assert response.status_code == 201
    assert response.json()["at_sms_dispatch"]["recipient"] == "+254711223344"


def test_safety_sms_content(client, drivers, trip_payload):
    trip_id = client.post("/api/trips/start", json=trip_payload).json()["trip_id"]
    detail = client.get(f"/api/trips/{trip_id}").json()
    safety = [s for s in detail["sms_logs"] if s["kind"] == "SAFETY_DISPATCH"]
    assert len(safety) == 1
    assert safety[0]["sent"] is True


def test_begin_ride_transition(client, drivers, trip_payload):
    trip_id = client.post("/api/trips/start", json=trip_payload).json()["trip_id"]
    response = client.post(f"/api/trips/{trip_id}/start")
    assert response.status_code == 200
    assert response.json()["status"] == "IN_PROGRESS"


def test_cannot_begin_ride_twice(client, drivers, trip_payload):
    trip_id = client.post("/api/trips/start", json=trip_payload).json()["trip_id"]
    assert client.post(f"/api/trips/{trip_id}/start").status_code == 200
    assert client.post(f"/api/trips/{trip_id}/start").status_code == 409


def test_complete_trip_cash(client, drivers, trip_payload):
    trip_id = client.post("/api/trips/start", json=trip_payload).json()["trip_id"]
    client.post(f"/api/trips/{trip_id}/start")
    response = client.post(f"/api/trips/{trip_id}/complete", json={"payment_method": "CASH"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["final_fare"] == 852.5
    assert body["currency"] == "KES"
    assert body["payment_status"] == "CASH"
    assert body["payment_options"] == ["MPESA_STK_PUSH", "CASH"]


def test_complete_trip_mpesa_simulated(client, drivers, trip_payload):
    trip_id = client.post("/api/trips/start", json=trip_payload).json()["trip_id"]
    response = client.post(f"/api/trips/{trip_id}/complete", json={"payment_method": "MPESA_STK_PUSH"})
    assert response.status_code == 200
    body = response.json()
    assert body["final_fare"] == 852.5
    assert body["mpesa_checkout_request_id"]  # simulated id when Daraja is off


def test_complete_frees_driver(client, drivers, trip_payload, db_session):
    trip_id = client.post("/api/trips/start", json=trip_payload).json()["trip_id"]
    client.post(f"/api/trips/{trip_id}/complete", json={"payment_method": "CASH"})
    db_session.expire_all()
    refreshed = db_session.get(type(drivers["manual"]), drivers["manual"].id)
    assert refreshed.status == "AVAILABLE" or refreshed.status.value == "AVAILABLE"
    assert refreshed.total_trips == 185


def test_complete_with_actual_distance_overrides(client, drivers, trip_payload):
    trip_id = client.post("/api/trips/start", json=trip_payload).json()["trip_id"]
    response = client.post(f"/api/trips/{trip_id}/complete", json={"distance_km": 10, "payment_method": "CASH"})
    assert response.json()["final_fare"] == 950.0


def test_complete_already_completed_is_409(client, drivers, trip_payload):
    trip_id = client.post("/api/trips/start", json=trip_payload).json()["trip_id"]
    assert client.post(f"/api/trips/{trip_id}/complete", json={"payment_method": "CASH"}).status_code == 200
    assert client.post(f"/api/trips/{trip_id}/complete", json={"payment_method": "CASH"}).status_code == 409


def test_cancel_trip(client, drivers, trip_payload):
    trip_id = client.post("/api/trips/start", json=trip_payload).json()["trip_id"]
    response = client.post(f"/api/trips/{trip_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"


def test_unknown_trip_404(client):
    assert client.get("/api/trips/TRP-NOPE").status_code == 404
    assert client.post("/api/trips/TRP-NOPE/start").status_code == 404
    assert client.post("/api/trips/TRP-NOPE/complete", json={}).status_code == 404


def test_trip_events_audit_trail(client, drivers, trip_payload):
    trip_id = client.post("/api/trips/start", json=trip_payload).json()["trip_id"]
    client.post(f"/api/trips/{trip_id}/start")
    client.post(f"/api/trips/{trip_id}/complete", json={"payment_method": "CASH"})
    detail = client.get(f"/api/trips/{trip_id}").json()
    event_types = [e["event_type"] for e in detail["events"]]
    assert event_types == ["TRIP_CREATED", "SAFETY_SMS_DISPATCHED", "TRIP_STARTED", "TRIP_COMPLETED"]


def test_timestamps_are_utc_marked(client, drivers, trip_payload):
    """Spec shows ISO-8601 with an explicit Z suffix, e.g. 2026-10-29T12:05:00Z."""
    body = client.post("/api/trips/start", json=trip_payload).json()
    assert body["created_at"].endswith("Z"), body["created_at"]

    trip_id = body["trip_id"]
    completed = client.post(f"/api/trips/{trip_id}/complete", json={"payment_method": "CASH"}).json()
    assert completed["completed_at"].endswith("Z"), completed["completed_at"]


def test_eta_is_derived_from_driver_distance(client, drivers, trip_payload):
    """The manual driver is ~290 m away, so ETA must be small, not a hardcoded 6."""
    body = client.post("/api/trips/start", json=trip_payload).json()
    assert 1 <= body["driver"]["eta_minutes"] <= 3, body["driver"]
