from datetime import datetime, timezone

ALLOWED_TRANSITIONS = {
    "DRIVER_EN_ROUTE": {"IN_PROGRESS", "SOS_TRIGGERED"},
    "IN_PROGRESS": {"COMPLETED", "SOS_TRIGGERED"},
    "SOS_TRIGGERED": {"IN_PROGRESS", "COMPLETED"},
    "COMPLETED": set(),
}


def can_drive(certification, transmission):
    return certification == "MANUAL" or (certification == "AUTOMATIC" and transmission == "AUTOMATIC")


def transition(trip, next_status):
    if next_status not in ALLOWED_TRANSITIONS.get(trip.status, set()):
        raise ValueError(f"Cannot transition from {trip.status} to {next_status}.")
    trip.status = next_status
    if next_status == "IN_PROGRESS" and trip.started_at is None:
        trip.started_at = datetime.now(timezone.utc)
    if next_status == "COMPLETED":
        trip.completed_at = datetime.now(timezone.utc)
