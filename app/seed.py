"""Seed demo drivers so the hackathon demo works immediately.

    python -m app.seed
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.database import SessionLocal, init_db
from app.models import Driver, DriverStatus, TransmissionCertification

# Real-ish Nairobi coordinates: Westlands, Kilimani, CBD, Lavington.
DEMO_DRIVERS = [
    {
        "full_name": "David Kamau",
        "phone": "+254712345678",
        "email": "david.kamau@example.co.ke",
        "photo_url": "https://assets.ifinder.app/drivers/drv-098.png",
        "transmission_certified": TransmissionCertification.MANUAL_AND_AUTO,
        "dci_good_conduct_verified": True,
        "dci_certificate_ref": "DCI-CERT-88421",
        "ntsa_license_no": "DL-KE-488219",
        "current_lat": -1.2642,
        "current_lng": 36.8045,
        "rating": 4.92,
        "rating_sum": 4.92 * 184,
        "rating_count": 184,
        "total_trips": 184,
    },
    {
        "full_name": "Faith Wanjiru",
        "phone": "+254723456789",
        "email": "faith.wanjiru@example.co.ke",
        "transmission_certified": TransmissionCertification.AUTO_ONLY,
        "dci_good_conduct_verified": True,
        "dci_certificate_ref": "DCI-CERT-77310",
        "ntsa_license_no": "DL-KE-112907",
        "current_lat": -1.2974,
        "current_lng": 36.7865,
        "rating": 4.87,
        "rating_sum": 4.87 * 96,
        "rating_count": 96,
        "total_trips": 96,
    },
    {
        "full_name": "Brian Otieno",
        "phone": "+254734567890",
        "email": "brian.otieno@example.co.ke",
        "transmission_certified": TransmissionCertification.MANUAL_AND_AUTO,
        "dci_good_conduct_verified": True,
        "dci_certificate_ref": "DCI-CERT-66125",
        "ntsa_license_no": "DL-KE-730441",
        "current_lat": -1.2864,
        "current_lng": 36.8172,
        "rating": 4.78,
        "rating_sum": 4.78 * 42,
        "rating_count": 42,
        "total_trips": 42,
    },
    {
        "full_name": "Grace Njeri",
        "phone": "+254745678901",
        "email": "grace.njeri@example.co.ke",
        "transmission_certified": TransmissionCertification.AUTO_ONLY,
        "dci_good_conduct_verified": True,
        "dci_certificate_ref": "DCI-CERT-55201",
        "ntsa_license_no": "DL-KE-998812",
        "current_lat": -1.2750,
        "current_lng": 36.7800,
        "rating": 4.95,
        "rating_sum": 4.95 * 61,
        "rating_count": 61,
        "total_trips": 61,
    },
    {
        "full_name": "Samuel Kiprop",
        "phone": "+254756789012",
        "email": "samuel.kiprop@example.co.ke",
        "transmission_certified": TransmissionCertification.MANUAL_AND_AUTO,
        "dci_good_conduct_verified": False,  # pending DCI check - should never be matched
        "dci_certificate_ref": None,
        "ntsa_license_no": "DL-KE-204118",
        "current_lat": -1.2620,
        "current_lng": 36.8020,
        "rating": 5.0,
        "rating_sum": 0.0,
        "rating_count": 0,
        "total_trips": 0,
    },
]


def seed() -> None:
    init_db()
    db = SessionLocal()
    created = 0
    try:
        for spec in DEMO_DRIVERS:
            existing = db.scalar(select(Driver).where(Driver.phone == spec["phone"]))
            if existing is not None:
                continue
            db.add(
                Driver(
                    **spec,
                    status=DriverStatus.AVAILABLE,
                    last_seen_at=datetime.now(timezone.utc),
                )
            )
            created += 1
        db.commit()

        total = db.scalar(select(Driver).order_by(Driver.id).limit(1))
        all_drivers = list(db.scalars(select(Driver).order_by(Driver.full_name)))
        print(f"Seed complete: {created} new driver(s), {len(all_drivers)} total.")
        for d in all_drivers:
            verified = "verified" if d.dci_good_conduct_verified else "NOT verified"
            print(f"  {d.id}  {d.full_name:<16} {d.transmission_certified.value:<16} {verified}")
        if total is None:
            print("Warning: no drivers present after seeding.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
