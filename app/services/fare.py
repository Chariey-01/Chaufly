"""Distance-based fare calculation."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import settings
from app.services.geo import minutes_for_distance


@dataclass(frozen=True)
class FareQuote:
    currency: str
    distance_km: float
    base_fare: float
    per_km_rate: float
    estimated_fare: float
    estimated_duration_min: int
    quote_expires_in_sec: int


def calculate_fare(distance_km: float) -> FareQuote:
    """base fare + per-km rate, rounded to the nearest shilling.

    Matching the spec example: 300 + 65 * 8.5 = 852.5 KES.
    """
    if distance_km <= 0:
        raise ValueError("distance_km must be greater than zero")

    estimated = settings.fare_base + settings.fare_per_km * distance_km
    return FareQuote(
        currency="KES",
        distance_km=round(distance_km, 2),
        base_fare=float(settings.fare_base),
        per_km_rate=float(settings.fare_per_km),
        estimated_fare=round(estimated, 2),
        estimated_duration_min=minutes_for_distance(distance_km, settings.avg_speed_kmh),
        quote_expires_in_sec=settings.quote_ttl_seconds,
    )
