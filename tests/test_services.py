import pytest

from app.models import Trip
from app.services.routing import calculate_fare
from app.services.trips import can_drive, transition


def test_fare_calculation_is_deterministic_from_provider_distance():
    assert calculate_fare(10) == 1100
    with pytest.raises(ValueError):
        calculate_fare(-1)


def test_manual_driver_can_drive_both_transmissions():
    assert can_drive("MANUAL", "MANUAL")
    assert can_drive("MANUAL", "AUTOMATIC")
    assert can_drive("AUTOMATIC", "AUTOMATIC")
    assert not can_drive("AUTOMATIC", "MANUAL")


def test_status_transitions_are_constrained():
    trip = Trip(status="DRIVER_EN_ROUTE")
    transition(trip, "IN_PROGRESS")
    assert trip.status == "IN_PROGRESS"
    with pytest.raises(ValueError):
        transition(trip, "DRIVER_EN_ROUTE")
