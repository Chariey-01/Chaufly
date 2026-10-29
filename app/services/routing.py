from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from flask import current_app


class RoutingUnavailable(Exception):
    pass


@dataclass
class Route:
    distance_km: float
    duration_minutes: int
    source: str


def get_route(_pickup, _dropoff):
    """Return provider data only. No fallback coordinates, distance, or ETA is invented."""
    provider = current_app.config.get("ROUTING_PROVIDER", "unconfigured")
    raise RoutingUnavailable(
        f"Route-based quotes are unavailable because routing provider '{provider}' is not configured."
    )


def calculate_fare(distance_km, base_fare=300, per_km_rate=80):
    if distance_km < 0:
        raise ValueError("Distance cannot be negative.")
    return int(round(base_fare + (distance_km * per_km_rate)))


def quote_from_route(route):
    return {
        "currency": "KES",
        "distance_km": route.distance_km,
        "base_fare": 300,
        "per_km_rate": 80,
        "estimated_fare": calculate_fare(route.distance_km),
        "estimated_duration_minutes": route.duration_minutes,
        "quote_expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        "route_source": route.source,
    }
