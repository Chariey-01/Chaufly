"""Tests for the unauthenticated tracking endpoint.

This endpoint is the one place in the API with no auth at all, so the tests here
are mostly about what must NOT come back. Plate masking and the absence of phone
numbers are treated as security requirements, not cosmetic ones.
"""

from __future__ import annotations

import pytest

from app.api.routes_public import mask_plate


# ---------------------------------------------------------------------------
# Plate masking
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "plate,expected",
    [
        ("KDA 829X", "KDA ***X"),
        ("KDA829X", "KDA ***X"),
        ("kda 829x", "KDA ***X"),
        ("KCX 001A", "KCX ***A"),
    ],
)
def test_mask_plate_keeps_prefix_and_suffix(plate, expected):
    assert mask_plate(plate) == expected


@pytest.mark.parametrize("plate", ["KA", "KDAB", "1234"])
def test_mask_plate_hides_short_plates_entirely(plate):
    assert set(mask_plate(plate)) == {"*"}


def test_mask_plate_never_reveals_the_middle_digits():
    masked = mask_plate("KDA 829X")
    assert "829" not in masked
    assert "8" not in masked


# ---------------------------------------------------------------------------
# Endpoint behaviour
# ---------------------------------------------------------------------------
@pytest.fixture
def started_trip(client, trip_payload):
    res = client.post("/api/trips/start", json=trip_payload)
    assert res.status_code == 201, res.text
    return res.json()


def test_public_status_returns_trip_core_facts(client, started_trip):
    res = client.get(f"/api/trips/{started_trip['trip_id']}/public")
    assert res.status_code == 200

    body = res.json()
    assert body["trip_id"] == started_trip["trip_id"]
    assert body["status"] == "DRIVER_EN_ROUTE"
    assert body["customer_first_name"] == "Caroline"
    assert body["driver_first_name"] == "David"
    assert body["destination"] == "Kilimani, Nairobi"
    assert body["is_emergency"] is False
    assert body["vehicle"] == "KDA ***X"


def test_public_status_leaks_no_phone_numbers(client, started_trip):
    """The link travels by SMS and can be forwarded. No numbers may slip out."""
    res = client.get(f"/api/trips/{started_trip['trip_id']}/public")
    raw = res.text

    for leaked in (
        "+254700000001",  # customer
        "254700000001",
        "+254712345678",  # driver
        "254712345678",
        "+254711223344",  # emergency contact
    ):
        assert leaked not in raw, f"{leaked} leaked into the public payload"


def test_public_events_drop_internal_detail(client, started_trip):
    """Event detail blobs are an internal audit trail and can carry phone numbers.

    Regression: SAFETY_SMS_DISPATCHED.detail originally included the emergency
    contact's number, which leaked straight through the public endpoint.
    """
    body = client.get(f"/api/trips/{started_trip['trip_id']}/public").json()

    assert body["events"], "expected at least one event"
    for event in body["events"]:
        assert set(event.keys()) == {"event_type", "created_at"}
        assert "detail" not in event


def test_public_status_leaks_no_coordinates(client, started_trip):
    body = client.get(f"/api/trips/{started_trip['trip_id']}/public").json()

    for key in ("pickup_lat", "pickup_lng", "dropoff_lat", "dropoff_lng"):
        assert key not in body

    raw = client.get(f"/api/trips/{started_trip['trip_id']}/public").text
    assert "-1.2642" not in raw
    assert "36.8045" not in raw


def test_public_status_leaks_no_fare(client, started_trip):
    """A relative shouldn't learn what the trip cost."""
    body = client.get(f"/api/trips/{started_trip['trip_id']}/public").json()
    assert "estimated_fare" not in body
    assert "final_fare" not in body


def test_public_status_includes_event_trail(client, started_trip):
    body = client.get(f"/api/trips/{started_trip['trip_id']}/public").json()

    events = [e["event_type"] for e in body["events"]]
    assert "TRIP_CREATED" in events
    assert "SAFETY_SMS_DISPATCHED" in events
    assert body["last_event"] in events


def test_public_status_unknown_trip_is_404(client):
    res = client.get("/api/trips/TRP-NOPE00/public")
    assert res.status_code == 404


def test_public_status_flags_emergency(client, started_trip):
    sos = client.post(
        f"/api/trips/{started_trip['trip_id']}/sos",
        json={
            "current_lat": -1.2642,
            "current_lng": 36.8045,
            "trigger_reason": "PASSENGER_TRIGGERED_SOS",
        },
    )
    assert sos.status_code == 200

    body = client.get(f"/api/trips/{started_trip['trip_id']}/public").json()
    assert body["status"] == "SOS"
    assert body["is_emergency"] is True
    assert "SOS_TRIGGERED" in [e["event_type"] for e in body["events"]]


def test_public_status_shows_eta_while_driver_en_route(client, started_trip):
    body = client.get(f"/api/trips/{started_trip['trip_id']}/public").json()
    # Driver is ~290 m from a Westlands pickup at 15 km/h -> ~2 min.
    assert body["driver_eta_minutes"] is not None
    assert 1 <= body["driver_eta_minutes"] <= 5


def test_public_status_clears_eta_once_ride_starts(client, started_trip):
    trip_id = started_trip["trip_id"]
    client.post(f"/api/trips/{trip_id}/start")

    body = client.get(f"/api/trips/{trip_id}/public").json()
    assert body["status"] == "IN_PROGRESS"
    assert body["driver_eta_minutes"] is None


def test_public_status_reports_completion(client, started_trip):
    trip_id = started_trip["trip_id"]
    client.post(f"/api/trips/{trip_id}/complete", json={"payment_method": "CASH"})

    body = client.get(f"/api/trips/{trip_id}/public").json()
    assert body["status"] == "COMPLETED"
    assert body["completed_at"] is not None


# ---------------------------------------------------------------------------
# Frontend shell
# ---------------------------------------------------------------------------
def test_root_serves_booking_app(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "iFinder" in res.text


def test_track_page_serves_for_any_trip_id(client):
    """The page must render even for a bad id so the reader gets an explanation."""
    res = client.get("/track/TRP-884210")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]


def test_static_assets_are_served(client):
    for path in ("/static/app.css", "/static/app.js", "/static/track.js"):
        res = client.get(path)
        assert res.status_code == 200, path
