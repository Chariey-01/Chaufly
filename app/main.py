"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import (
    routes_drivers,
    routes_health,
    routes_mpesa,
    routes_ops,
    routes_public,
    routes_quote,
    routes_trips,
)
from app.config import settings
from app.database import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
logger = logging.getLogger("ifinder")

API_PREFIX = "/api"

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
INDEX_HTML = WEB_DIR / "index.html"
TRACK_HTML = WEB_DIR / "track.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info(
        "%s starting | env=%s | AT enabled=%s | M-Pesa enabled=%s",
        settings.app_name,
        settings.environment,
        settings.at_enabled,
        settings.mpesa_enabled,
    )
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=f"{settings.app_name} API",
        version="0.1.0",
        description=(
            "Dial-a-driver MVP: verified chauffeurs drive intoxicated, fatigued or unwell "
            "customers home in their own vehicles. Powered by Africa's Talking SMS & Voice."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(routes_health.router, prefix=API_PREFIX)
    app.include_router(routes_quote.router, prefix=API_PREFIX)
    # /trips/{id}/public must be registered before the ops router so the literal
    # suffix is not swallowed by the /trips/{trip_id} detail route.
    app.include_router(routes_public.router, prefix=API_PREFIX)
    app.include_router(routes_drivers.router, prefix=API_PREFIX)
    app.include_router(routes_trips.router, prefix=API_PREFIX)
    app.include_router(routes_mpesa.router, prefix=API_PREFIX)
    app.include_router(routes_ops.router, prefix=API_PREFIX)

    if WEB_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def root():
        """Customer booking app. Falls back to a JSON index if web/ is missing."""
        if INDEX_HTML.is_file():
            return FileResponse(INDEX_HTML)
        return JSONResponse(
            {
                "app": settings.app_name,
                "version": "0.1.0",
                "docs": "/docs",
                "api": API_PREFIX,
                "frontend": "not installed (expected web/index.html)",
            }
        )

    @app.get("/track/{trip_id}", include_in_schema=False)
    def track_page(trip_id: str):
        """Landing page for the link in the safety SMS.

        Always returns 200 so a relative sees a friendly page even for a bad
        trip id; the page itself reports the missing trip via the API.
        """
        if TRACK_HTML.is_file():
            return FileResponse(TRACK_HTML)
        return JSONResponse(
            {"frontend": "not installed (expected web/track.html)"}, status_code=404
        )

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        icon = WEB_DIR / "favicon.svg"
        if icon.is_file():
            return FileResponse(icon, media_type="image/svg+xml")
        return JSONResponse({"detail": "no favicon"}, status_code=404)

    return app


app = create_app()
