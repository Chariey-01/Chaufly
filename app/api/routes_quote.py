"""POST /api/quote — distance-based fare quotation."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.schemas import QuoteRequest, QuoteResponse
from app.services.fare import calculate_fare

router = APIRouter(tags=["quote"])


@router.post("/quote", response_model=QuoteResponse, status_code=status.HTTP_200_OK)
def quote(payload: QuoteRequest) -> QuoteResponse:
    try:
        q = calculate_fare(payload.distance_km)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None

    return QuoteResponse(
        currency=q.currency,
        distance_km=q.distance_km,
        base_fare=q.base_fare,
        per_km_rate=q.per_km_rate,
        estimated_fare=q.estimated_fare,
        estimated_duration_min=q.estimated_duration_min,
        quote_expires_in_sec=q.quote_expires_in_sec,
    )
