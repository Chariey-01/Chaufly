"""Health and metadata endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)) -> HealthResponse:
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:  # noqa: BLE001 - health checks must never raise
        db_status = "error"

    return HealthResponse(
        status="ok" if db_status == "ok" else "degraded",
        app=settings.app_name,
        environment=settings.environment,
        database=db_status,
        at_enabled=bool(settings.at_enabled and settings.at_api_key),
    )
