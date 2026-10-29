"""Driver matching: transmission rules, proximity, verification."""

from __future__ import annotations


PICKUP = {"pickup_lat": -1.2642, "pickup_lng": 36.8045, "radius_km": 5.0}


def test_manual_request_returns_manual_certified_driver(client, drivers):
    response = client.post("/api/drivers/match", json={"car_transmission": "MANUAL", **PICKUP})
    assert response.status_code == 200
    driver = response.json()["matched_driver"]
    # Only the MANUAL_AND_AUTO driver is eligible for a manual car.
    assert driver["driver_id"] == drivers["manual"].id
    assert driver["transmission_certified"] == "MANUAL_AND_AUTO"


def test_automatic_request_prefers_nearest_eligible_driver(client, drivers):
    response = client.post("/api/drivers/match", json={"car_transmission": "AUTOMATIC", **PICKUP})
    assert response.status_code == 200
    driver = response.json()["matched_driver"]
    # The auto-only driver is marginally closer than the manual driver.
    assert driver["driver_id"] == drivers["auto_only"].id
    assert driver["transmission_certified"] == "AUTO_ONLY"


def test_unverified_driver_is_never_matched(client, drivers):
    """Samuel sits closest to the pickup but has no DCI clearance."""
    for transmission in ("MANUAL", "AUTOMATIC"):
        response = client.post("/api/drivers/match", json={"car_transmission": transmission, **PICKUP})
        assert response.status_code == 200
        assert response.json()["matched_driver"]["driver_id"] != drivers["unverified"].id


def test_far_away_driver_excluded_by_radius(client, drivers):
    response = client.post(
        "/api/drivers/match",
        json={"car_transmission": "MANUAL", "pickup_lat": -1.2642, "pickup_lng": 36.8045, "radius_km": 0.05},
    )
    # Nobody within 50 m.
    assert response.status_code == 404


def test_returns_404_when_no_eligible_driver(client, drivers):
    # Mombasa coordinates: 400+ km from the seeded Nairobi drivers.
    response = client.post(
        "/api/drivers/match",
        json={"car_transmission": "MANUAL", "pickup_lat": -4.0435, "pickup_lng": 39.6682, "radius_km": 5.0},
    )
    assert response.status_code == 404


def test_match_response_shape(client, drivers):
    body = client.post("/api/drivers/match", json={"car_transmission": "MANUAL", **PICKUP}).json()
    driver = body["matched_driver"]
    for key in (
        "driver_id",
        "full_name",
        "phone",
        "rating",
        "total_trips",
        "transmission_certified",
        "qualifications",
        "eta_minutes",
        "current_distance_km",
    ):
        assert key in driver, f"missing {key}"
    assert driver["qualifications"]["dci_good_conduct_verified"] is True
    assert driver["current_distance_km"] <= 5.0
    assert driver["eta_minutes"] >= 1


def test_certification_rule_unit():
    from app.models import Transmission, TransmissionCertification

    assert TransmissionCertification.MANUAL_AND_AUTO.can_drive(Transmission.MANUAL)
    assert TransmissionCertification.MANUAL_AND_AUTO.can_drive(Transmission.AUTOMATIC)
    assert not TransmissionCertification.AUTO_ONLY.can_drive(Transmission.MANUAL)
    assert TransmissionCertification.AUTO_ONLY.can_drive(Transmission.AUTOMATIC)
