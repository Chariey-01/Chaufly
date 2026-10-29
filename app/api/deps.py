"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Trip
from app.services.trips import TripNotFound, get_trip


def require_trip(trip_id: str, db: Session = Depends(get_db)) -> Trip:
    """Resolve a trip or raise 404."""
    try:
        return get_trip(db, trip_id)
    except TripNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Trip {trip_id} not found"
        ) from None
