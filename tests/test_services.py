import pytest

from app.models import Trip
from app.services import routing
from app.services.routing import Route, RoutingProviderError, RoutingUnavailable, calculate_fare, get_route, quote_from_route
from app.services.trips import can_drive, transition


def test_fare_calculation_is_deterministic_from_provider_distance():
    assert calculate_fare(10) == 1100
    assert calculate_fare(1, base_fare=100, per_km_rate=10, minimum_fare=300) == 300
    with pytest.raises(ValueError):
        calculate_fare(-1)


class ProviderResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            error = routing.requests.HTTPError("provider error")
            error.response = self
            raise error

    def json(self):
        return self.payload


def test_openrouteservice_route_uses_provider_distance_and_duration(app, monkeypatch):
    def fake_post(url, *, headers, json, timeout):
        assert url.endswith("/v2/directions/driving-car/json")
        assert headers["Authorization"] == "ors-test-key"
        assert json["coordinates"] == [(36.817, -1.286), (36.821, -1.29)]
        assert timeout == 15
        return ProviderResponse({"routes": [{"summary": {"distance": 1840, "duration": 230}}]})

    with app.app_context():
        app.config.update(ROUTING_PROVIDER="openrouteservice", ORS_API_KEY="ors-test-key")
        monkeypatch.setattr(routing.requests, "post", fake_post)
        route = get_route({"latitude": -1.286, "longitude": 36.817}, {"latitude": -1.29, "longitude": 36.821})
        quote = quote_from_route(route)

    assert route == Route(distance_km=1.84, duration_minutes=4, source="openrouteservice")
    assert quote["estimated_fare"] == 447
    assert quote["distance_km"] == 1.84


def test_openrouteservice_geocodes_addresses_before_directions(app, monkeypatch):
    locations = iter([
        {"features": [{"geometry": {"coordinates": [36.817, -1.286]}}]},
        {"features": [{"geometry": {"coordinates": [36.821, -1.29]}}]},
    ])

    with app.app_context():
        app.config.update(ROUTING_PROVIDER="openrouteservice", ORS_API_KEY="ors-test-key")
        monkeypatch.setattr(routing.requests, "get", lambda *args, **kwargs: ProviderResponse(next(locations)))
        monkeypatch.setattr(routing.requests, "post", lambda *args, **kwargs: ProviderResponse({"routes": [{"summary": {"distance": 1000, "duration": 60}}]}))
        route = get_route({"address": "Pickup"}, {"address": "Destination"})

    assert route.distance_km == 1
    assert route.duration_minutes == 1


def test_routing_reports_missing_config_and_provider_error(app, monkeypatch):
    with app.app_context():
        with pytest.raises(RoutingUnavailable):
            get_route({"latitude": 0, "longitude": 0}, {"latitude": 1, "longitude": 1})
        app.config.update(ROUTING_PROVIDER="openrouteservice", ORS_API_KEY="ors-test-key")
        monkeypatch.setattr(routing.requests, "post", lambda *args, **kwargs: ProviderResponse({}, status_code=503))
        with pytest.raises(RoutingProviderError, match="HTTP 503"):
            get_route({"latitude": 0, "longitude": 0}, {"latitude": 1, "longitude": 1})


def test_manual_driver_can_drive_both_transmissions():
    assert can_drive("MANUAL", "MANUAL")
    assert can_drive("MANUAL", "AUTOMATIC")
    assert can_drive("AUTOMATIC", "AUTOMATIC")
    assert not can_drive("AUTOMATIC", "MANUAL")


def test_status_transitions_are_constrained():
    trip = Trip(status="DRIVER_EN_ROUTE")
    transition(trip, "IN_PROGRESS")
    assert trip.status == "IN_PROGRESS"
    with pytest.raises(ValueError):
        transition(trip, "DRIVER_EN_ROUTE")
