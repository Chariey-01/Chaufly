"""Ops/admin read endpoints for the demo dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import SmsLog, Trip
from app.schemas import SmsLogOut, TripDetail, TripEventOut, TripListItem

router = APIRouter(tags=["ops"])


@router.get("/trips", response_model=list[TripListItem])
def list_trips(
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[Trip]:
    stmt = select(Trip).order_by(Trip.created_at.desc()).limit(limit)
    return list(db.scalars(stmt))


@router.get("/trips/{trip_id}", response_model=TripDetail)
def trip_detail(trip_id: str, db: Session = Depends(get_db)) -> TripDetail:
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Trip {trip_id} not found")

    sms_logs = list(
        db.scalars(select(SmsLog).where(SmsLog.trip_id == trip_id).order_by(SmsLog.created_at))
    )
    detail = TripDetail.model_validate(trip)
    detail.events = [TripEventOut.model_validate(e) for e in trip.events]
    detail.sms_logs = [SmsLogOut.model_validate(s) for s in sms_logs]
    return detail


@router.get("/sms-logs", response_model=list[SmsLogOut])
def list_sms_logs(
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[SmsLog]:
    stmt = select(SmsLog).order_by(SmsLog.created_at.desc()).limit(limit)
    return list(db.scalars(stmt))
