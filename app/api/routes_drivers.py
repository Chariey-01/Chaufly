"""Driver matching and ops-facing driver management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Driver, DriverStatus
from app.schemas import DriverCreate, DriverOut, MatchRequest, MatchResponse, MatchedDriver, Qualifications
from app.services.matching import NoDriverAvailable, find_best_driver

router = APIRouter(tags=["drivers"])


@router.post("/drivers/match", response_model=MatchResponse, status_code=status.HTTP_200_OK)
def match_driver(payload: MatchRequest, db: Session = Depends(get_db)) -> MatchResponse:
    try:
        driver, distance_km, eta = find_best_driver(
            db,
            transmission=payload.car_transmission,
            pickup_lat=payload.pickup_lat,
            pickup_lng=payload.pickup_lng,
            radius_km=payload.radius_km,
        )
    except NoDriverAvailable as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from None

    return MatchResponse(
        matched_driver=MatchedDriver(
            driver_id=driver.id,
            full_name=driver.full_name,
            phone=driver.phone,
            rating=driver.rating,
            total_trips=driver.total_trips,
            photo_url=driver.photo_url,
            transmission_certified=driver.transmission_certified,
            qualifications=Qualifications(
                dci_good_conduct_verified=driver.dci_good_conduct_verified,
                dci_certificate_ref=driver.dci_certificate_ref,
                ntsa_license_no=driver.ntsa_license_no,
            ),
            eta_minutes=eta,
            current_distance_km=distance_km,
        )
    )


# ---------------------------------------------------------------------------
# Ops endpoints
# ---------------------------------------------------------------------------
@router.get("/drivers", response_model=list[DriverOut], tags=["ops"])
def list_drivers(
    db: Session = Depends(get_db),
    status_filter: DriverStatus | None = Query(default=None, alias="status"),
) -> list[Driver]:
    stmt = select(Driver).order_by(Driver.full_name)
    if status_filter is not None:
        stmt = stmt.where(Driver.status == status_filter)
    return list(db.scalars(stmt))


@router.post("/drivers", response_model=DriverOut, status_code=status.HTTP_201_CREATED, tags=["ops"])
def create_driver(payload: DriverCreate, db: Session = Depends(get_db)) -> Driver:
    if db.scalar(select(Driver).where(Driver.phone == payload.phone)) is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"A driver with phone {payload.phone} already exists"
        )
    driver = Driver(**payload.model_dump())
    db.add(driver)
    db.commit()
    db.refresh(driver)
    return driver


@router.get("/drivers/{driver_id}", response_model=DriverOut, tags=["ops"])
def get_driver_detail(driver_id: str, db: Session = Depends(get_db)) -> Driver:
    driver = db.get(Driver, driver_id)
    if driver is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Driver {driver_id} not found")
    return driver
