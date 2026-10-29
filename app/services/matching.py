"""Driver matching: transmission capability + proximity ranking."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Driver, DriverStatus, Transmission, TransmissionCertification
from app.services.geo import haversine_km, minutes_for_distance


class NoDriverAvailable(Exception):
    """Raised when no online, qualified driver sits inside the radius."""


class DriverNotFound(Exception):
    """Raised when a specific driver id does not exist."""


class DriverUnavailable(Exception):
    """Raised when a driver exists but cannot take a trip right now."""


def _certification_filter(transmission: Transmission):
    """SQL filter for drivers certified for the requested transmission.

    Manual-certified drivers cover both; auto-only drivers cover automatic only.
    """
    if transmission is Transmission.MANUAL:
        return Driver.transmission_certified == TransmissionCertification.MANUAL_AND_AUTO
    return Driver.transmission_certified.in_(
        [TransmissionCertification.MANUAL_AND_AUTO, TransmissionCertification.AUTO_ONLY]
    )


def rank_candidates(
    drivers: list[Driver], pickup_lat: float, pickup_lng: float
) -> list[tuple[float, Driver]]:
    """Return (distance_km, driver) pairs sorted nearest-first, unknown positions last."""
    scored: list[tuple[float, Driver]] = []
    unknown: list[tuple[float, Driver]] = []
    for driver in drivers:
        if driver.current_lat is None or driver.current_lng is None:
            unknown.append((float("inf"), driver))
            continue
        dist = haversine_km(pickup_lat, pickup_lng, driver.current_lat, driver.current_lng)
        scored.append((dist, driver))
    scored.sort(key=lambda pair: pair[0])
    return scored + unknown


def find_best_driver(
    db: Session,
    *,
    transmission: Transmission,
    pickup_lat: float,
    pickup_lng: float,
    radius_km: float,
) -> tuple[Driver, float, int]:
    """Pick the nearest available, certified, verified driver inside the radius.

    Returns (driver, current_distance_km, eta_minutes).
    """
    stmt = select(Driver).where(
        Driver.status == DriverStatus.AVAILABLE,
        Driver.dci_good_conduct_verified.is_(True),
        _certification_filter(transmission),
    )
    candidates = list(db.scalars(stmt))
    ranked = rank_candidates(candidates, pickup_lat, pickup_lng)

    for distance, driver in ranked:
        if distance <= radius_km:
            eta = minutes_for_distance(distance, settings.approach_speed_kmh)
            return driver, round(distance, 2), eta

    raise NoDriverAvailable(
        f"No certified {transmission.value.lower()} driver available within {radius_km} km"
    )


def get_driver(db: Session, driver_id: str) -> Driver:
    driver = db.get(Driver, driver_id)
    if driver is None:
        raise DriverNotFound(driver_id)
    return driver


def ensure_driver_can_drive(driver: Driver, transmission: Transmission) -> None:
    """Enforce the manual/automatic certification boundary."""
    if driver.status is DriverStatus.SUSPENDED:
        raise DriverUnavailable("Driver is suspended")
    if driver.status is DriverStatus.ON_TRIP:
        raise DriverUnavailable("Driver is already on a trip")
    if driver.status is DriverStatus.OFFLINE:
        raise DriverUnavailable("Driver is offline")
    if not driver.dci_good_conduct_verified:
        raise DriverUnavailable("Driver is not DCI verified")
    if not driver.transmission_certified.can_drive(transmission):
        raise DriverUnavailable(
            f"Driver is only certified for {driver.transmission_certified.value}, "
            f"but the vehicle is {transmission.value}"
        )
