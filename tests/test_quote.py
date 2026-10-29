"""Quote endpoint tests."""

from __future__ import annotations


def test_quote_matches_spec_example(client):
    """300 base + 65/km on 8.5 km == 852.5 KES, exactly as in the spec."""
    response = client.post(
        "/api/quote",
        json={
            "pickup": {"address": "The Alchemist Bar, Parklands Rd, Nairobi", "lat": -1.2642, "lng": 36.8045},
            "dropoff": {"address": "Argwings Kodhek Rd, Kilimani, Nairobi", "lat": -1.2974, "lng": 36.7865},
            "distance_km": 8.5,
            "car_transmission": "AUTOMATIC",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["currency"] == "KES"
    assert body["distance_km"] == 8.5
    assert body["base_fare"] == 300.0
    assert body["per_km_rate"] == 65.0
    assert body["estimated_fare"] == 852.5
    assert body["quote_expires_in_sec"] == 300
    assert body["estimated_duration_min"] >= 1


def test_quote_rejects_zero_distance(client):
    response = client.post(
        "/api/quote",
        json={
            "pickup": {"address": "A"},
            "dropoff": {"address": "B"},
            "distance_km": 0,
            "car_transmission": "MANUAL",
        },
    )
    assert response.status_code == 422


def test_quote_rejects_negative_distance(client):
    response = client.post(
        "/api/quote",
        json={
            "pickup": {"address": "A"},
            "dropoff": {"address": "B"},
            "distance_km": -3,
            "car_transmission": "MANUAL",
        },
    )
    assert response.status_code == 422


def test_quote_rejects_bad_transmission(client):
    response = client.post(
        "/api/quote",
        json={
            "pickup": {"address": "A"},
            "dropoff": {"address": "B"},
            "distance_km": 4,
            "car_transmission": "CVT",
        },
    )
    assert response.status_code == 422


def test_quote_long_distance_scales(client):
    short = client.post(
        "/api/quote",
        json={"pickup": {"address": "A"}, "dropoff": {"address": "B"}, "distance_km": 2, "car_transmission": "MANUAL"},
    ).json()
    long = client.post(
        "/api/quote",
        json={"pickup": {"address": "A"}, "dropoff": {"address": "B"}, "distance_km": 40, "car_transmission": "MANUAL"},
    ).json()
    assert long["estimated_fare"] > short["estimated_fare"]
    assert short["estimated_fare"] == 430.0
    assert long["estimated_fare"] == 2900.0
