"""Driver rating and trust-score recomputation."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Rating, Trip, TripStatus


class RatingNotAllowed(Exception):
    """Ratings only exist for completed trips."""


class AlreadyRated(Exception):
    """One rating per trip."""


def rate_trip(
    db: Session, trip: Trip, *, rating: int, tags: list[str] | None, feedback_comment: str | None
) -> tuple[Rating, float]:
    if trip.status is not TripStatus.COMPLETED:
        raise RatingNotAllowed(f"Trip {trip.id} is {trip.status.value}; only completed trips can be rated")
    if trip.driver is None:
        raise RatingNotAllowed(f"Trip {trip.id} has no assigned driver")
    if trip.ratings:
        raise AlreadyRated(f"Trip {trip.id} has already been rated")

    record = Rating(
        trip_id=trip.id,
        driver_id=trip.driver_id,
        rating=rating,
        tags=tags or [],
        feedback_comment=feedback_comment,
    )
    db.add(record)

    driver = trip.driver
    driver.rating_sum += rating
    driver.rating_count += 1
    # Seed value of 5.0 for brand-new drivers should not dilute once real ratings exist.
    driver.rating = round(driver.rating_sum / driver.rating_count, 2)

    db.commit()
    db.refresh(record)
    db.refresh(driver)
    return record, driver.rating
