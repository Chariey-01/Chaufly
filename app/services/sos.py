"""SOS handling: emergency SMS broadcast + Africa's Talking voice alert."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models import SmsLog, SosIncident, Trip, TripStatus, VoiceLog
from app.services import notifications
from app.services.africastalking import sms_client, voice_client
from app.services.trips import record_event

logger = logging.getLogger("ifinder.sos")

# Ops support number is the always-on fallback recipient in an emergency.
OPS_SUPPORT_PHONE = "+254700000999"


class SosNotAllowed(Exception):
    """SOS fires only while a trip is live."""


def trigger_sos(
    db: Session, trip: Trip, *, lat: float, lng: float, trigger_reason: str
) -> tuple[SosIncident, list[SmsLog], VoiceLog | None]:
    if trip.status in {TripStatus.COMPLETED, TripStatus.CANCELLED}:
        raise SosNotAllowed(f"Trip {trip.id} is {trip.status.value}; SOS requires a live trip")

    incident = SosIncident(
        trip_id=trip.id,
        trigger_reason=trigger_reason,
        current_lat=lat,
        current_lng=lng,
    )
    db.add(incident)
    db.flush()

    driver_name = trip.driver.full_name if trip.driver else "Unknown driver"
    driver_phone = trip.driver.phone if trip.driver else "Unknown"

    message = notifications.sos_sms(
        user_name=trip.user_name,
        plate=trip.car_registration_plate,
        lat=lat,
        lng=lng,
        area=trip.dropoff_address or trip.pickup_address,
        driver_name=driver_name,
        driver_phone=driver_phone,
        trip_id=trip.id,
    )

    recipients = [r for r in [trip.emergency_contact_phone, OPS_SUPPORT_PHONE] if r]
    # De-duplicate while keeping order.
    recipients = list(dict.fromkeys(recipients))

    results = sms_client.send(message, recipients)
    sms_logs: list[SmsLog] = []
    for result in results:
        log = SmsLog(
            trip_id=trip.id,
            recipient=result.recipient,
            message=message,
            kind="SOS_BROADCAST",
            sent=result.sent,
            provider=result.provider,
            provider_message_id=result.message_id,
            provider_status=result.status,
            cost=result.cost,
            error=result.error,
            dedupe_key=f"SOS:{incident.id}:{result.recipient}",
        )
        db.add(log)
        sms_logs.append(log)

    # Voice alert to ops so a human hears about it, not just a text.
    voice_result = None
    voice_log = None
    if recipients:
        voice_results = voice_client.call([OPS_SUPPORT_PHONE])
        voice_result = voice_results[0] if voice_results else None
        voice_log = VoiceLog(
            trip_id=trip.id,
            recipient=OPS_SUPPORT_PHONE,
            kind="SOS_VOICE_ALERT",
            queued=bool(voice_result and voice_result.queued),
            provider_call_id=voice_result.call_id if voice_result else None,
            error=voice_result.error if voice_result else "No result returned",
        )
        db.add(voice_log)

    incident.sms_dispatched_to = [log.recipient for log in sms_logs if log.sent]
    incident.voice_alert_queued = bool(voice_result and voice_result.queued)

    previous = trip.status
    trip.status = TripStatus.SOS
    record_event(
        db,
        trip,
        "SOS_TRIGGERED",
        from_status=previous,
        to_status=TripStatus.SOS,
        detail={
            "incident_id": incident.id,
            "trigger_reason": trigger_reason,
            "lat": lat,
            "lng": lng,
            "sms_recipients": incident.sms_dispatched_to,
            "voice_alert_queued": incident.voice_alert_queued,
        },
    )

    db.commit()
    db.refresh(incident)
    return incident, sms_logs, voice_log
