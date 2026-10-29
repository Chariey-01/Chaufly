"""Test harness: in-memory SQLite, isolated app, Africa's Talking mocked."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Configure settings before the app package is imported.
_tmpdir = tempfile.mkdtemp(prefix="ifinder-tests-")
_db_path = Path(_tmpdir) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"
os.environ["AT_ENABLED"] = "false"
os.environ["MPESA_ENABLED"] = "false"
os.environ["ENVIRONMENT"] = "test"

from app.database import Base, get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Driver, DriverStatus, TransmissionCertification, utcnow  # noqa: E402
from app.services.africastalking import sms_client, voice_client  # noqa: E402


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(f"sqlite:///{_db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    return eng


@pytest.fixture
def db_session(engine):
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(autouse=True)
def clean_tables(engine):
    """Truncate every table between tests for total isolation."""
    yield
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture
def client(engine, monkeypatch):
    app = create_app()

    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    # Force the console ("no real SMS") path in tests.
    monkeypatch.setattr(sms_client, "_client", None, raising=False)
    monkeypatch.setattr(type(sms_client), "enabled", property(lambda self: False))
    monkeypatch.setattr(type(voice_client), "enabled", property(lambda self: False))

    with TestClient(app) as c:
        yield c


@pytest.fixture
def drivers(db_session):
    """One driver per certification type, all verified and available."""
    manual = Driver(
        full_name="David Kamau",
        phone="+254712345678",
        transmission_certified=TransmissionCertification.MANUAL_AND_AUTO,
        dci_good_conduct_verified=True,
        dci_certificate_ref="DCI-CERT-88421",
        ntsa_license_no="DL-KE-488219",
        status=DriverStatus.AVAILABLE,
        # ~290 m from the pickup point so it is not the nearest driver.
        current_lat=-1.2662,
        current_lng=36.8065,
        rating=4.92,
        rating_sum=4.92 * 184,
        rating_count=184,
        total_trips=184,
        last_seen_at=utcnow(),
    )
    auto_only = Driver(
        full_name="Faith Wanjiru",
        phone="+254723456789",
        transmission_certified=TransmissionCertification.AUTO_ONLY,
        dci_good_conduct_verified=True,
        dci_certificate_ref="DCI-CERT-77310",
        ntsa_license_no="DL-KE-112907",
        status=DriverStatus.AVAILABLE,
        current_lat=-1.2645,
        current_lng=36.8046,  # slightly closer than the manual driver
        rating=4.87,
        rating_sum=4.87 * 96,
        rating_count=96,
        total_trips=96,
        last_seen_at=utcnow(),
    )
    unverified = Driver(
        full_name="Samuel Kiprop",
        phone="+254756789012",
        transmission_certified=TransmissionCertification.MANUAL_AND_AUTO,
        dci_good_conduct_verified=False,
        status=DriverStatus.AVAILABLE,
        current_lat=-1.2643,
        current_lng=36.8044,  # closest, but must never be matched
        last_seen_at=utcnow(),
    )
    far_away = Driver(
        full_name="Mombasa Man",
        phone="+254767890123",
        transmission_certified=TransmissionCertification.MANUAL_AND_AUTO,
        dci_good_conduct_verified=True,
        status=DriverStatus.AVAILABLE,
        # Nakuru: ~140 km from Nairobi.
        current_lat=-0.3031,
        current_lng=36.0800,
        last_seen_at=utcnow(),
    )
    db_session.add_all([manual, auto_only, unverified, far_away])
    db_session.commit()
    for d in (manual, auto_only, unverified, far_away):
        db_session.refresh(d)
    return {"manual": manual, "auto_only": auto_only, "unverified": unverified, "far_away": far_away}


@pytest.fixture
def trip_payload(drivers):
    return {
        "user_name": "Caroline",
        "user_phone": "+254700000001",
        "car_details": {
            "make_model": "Subaru Impreza",
            "registration_plate": "KDA 829X",
            "transmission": "MANUAL",
        },
        "driver_id": drivers["manual"].id,
        "pickup_address": "The Alchemist Bar, Westlands",
        "pickup_lat": -1.2642,
        "pickup_lng": 36.8045,
        "dropoff_address": "Kilimani, Nairobi",
        "dropoff_lat": -1.2974,
        "dropoff_lng": 36.7865,
        "distance_km": 8.5,
        "emergency_contact": {"name": "Grace (Sister)", "phone": "+254711223344"},
    }
