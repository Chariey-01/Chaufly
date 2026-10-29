"""Geospatial helpers (no external GIS dependency needed for the MVP)."""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two WGS-84 points, in kilometres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def resolve_distance_km(
    *,
    declared_km: float | None,
    pickup: tuple[float | None, float | None],
    dropoff: tuple[float | None, float | None],
) -> float | None:
    """Prefer an explicit distance; otherwise derive it from the coordinates."""
    if declared_km and declared_km > 0:
        return round(declared_km, 3)
    plat, plng = pickup
    dlat, dlng = dropoff
    if None in (plat, plng, dlat, dlng):
        return None
    return round(haversine_km(plat, plng, dlat, dlng), 3)


def minutes_for_distance(distance_km: float, speed_kmh: float) -> int:
    """Travel time in minutes at a fixed average speed (never below 1)."""
    if speed_kmh <= 0:
        raise ValueError("speed_kmh must be positive")
    return max(1, round(distance_km / speed_kmh * 60))
