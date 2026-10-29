"""OpenRouteService routing adapter. Route values always originate with the provider."""
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests
from flask import current_app

logger = logging.getLogger(__name__)


class RoutingUnavailable(Exception):
    pass


class RoutingProviderError(Exception):
    pass


@dataclass
class Route:
    distance_km: float
    duration_minutes: int
    source: str


def _configuration():
    if current_app.config.get("ROUTING_PROVIDER") != "openrouteservice":
        raise RoutingUnavailable("Route-based quotes require ROUTING_PROVIDER=openrouteservice.")
    api_key = current_app.config.get("ORS_API_KEY")
    if not api_key:
        raise RoutingUnavailable("Route-based quotes require ORS_API_KEY.")
    return current_app.config["ORS_BASE_URL"].rstrip("/"), api_key


def _provider_error(operation, exc):
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    suffix = f" (HTTP {status_code})" if status_code else ""
    logger.warning("OpenRouteService %s failed%s: %s", operation, suffix, type(exc).__name__)
    return RoutingProviderError(f"Routing provider {operation} failed{suffix}.")


def _get_json(url, *, headers, params=None):
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        raise _provider_error("geocoding", exc) from exc


def _coordinates(location, base_url, headers):
    if "latitude" in location and "longitude" in location:
        return float(location["longitude"]), float(location["latitude"])
    address = location.get("address")
    if not address:
        raise RoutingProviderError("Routing provider requires a pickup and destination location.")
    data = _get_json(f"{base_url}/geocode/search", headers=headers, params={"text": address, "size": 1})
    try:
        longitude, latitude = data["features"][0]["geometry"]["coordinates"][:2]
        return float(longitude), float(latitude)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise RoutingProviderError("Routing provider returned no usable geocoding result.") from exc


def get_route(pickup, dropoff):
    """Resolve supplied locations and return an actual driving route from OpenRouteService."""
    base_url, api_key = _configuration()
    headers = {"Authorization": api_key, "Accept": "application/json"}
    coordinates = [_coordinates(pickup, base_url, headers), _coordinates(dropoff, base_url, headers)]
    try:
        response = requests.post(
            f"{base_url}/v2/directions/driving-car/json",
            headers=headers,
            json={"coordinates": coordinates},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        summary = data["routes"][0]["summary"]
        distance_km = float(summary["distance"]) / 1000
        duration_minutes = math.ceil(float(summary["duration"]) / 60)
        if distance_km < 0 or duration_minutes < 0:
            raise ValueError("negative route summary")
        return Route(distance_km=distance_km, duration_minutes=duration_minutes, source="openrouteservice")
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
        raise _provider_error("directions", exc) from exc


def calculate_fare(distance_km, base_fare=300, per_km_rate=80, minimum_fare=300):
    if distance_km < 0:
        raise ValueError("Distance cannot be negative.")
    return int(round(max(minimum_fare, base_fare + (distance_km * per_km_rate))))


def quote_from_route(route):
    base_fare = current_app.config["FARE_BASE_KES"]
    per_km_rate = current_app.config["FARE_PER_KM_KES"]
    minimum_fare = current_app.config["FARE_MINIMUM_KES"]
    return {
        "currency": "KES",
        "distance_km": round(route.distance_km, 3),
        "base_fare": base_fare,
        "minimum_fare": minimum_fare,
        "per_km_rate": per_km_rate,
        "estimated_fare": calculate_fare(route.distance_km, base_fare, per_km_rate, minimum_fare),
        "estimated_duration_minutes": route.duration_minutes,
        "quote_expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        "route_source": route.source,
    }
