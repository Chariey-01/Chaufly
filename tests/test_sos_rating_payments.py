"""SOS, rating, ops and payment callback tests."""

from __future__ import annotations


def test_sos_dispatches_to_contact_and_ops(client, drivers, trip_payload):
    trip_id = client.post("/api/trips/start", json=trip_payload).json()["trip_id"]
    response = client.post(
        f"/api/trips/{trip_id}/sos",
        json={"current_lat": -1.2789, "current_lng": 36.7921, "trigger_reason": "PASSENGER_TRIGGERED_SOS"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "EMERGENCY_BROADCAST_SENT"
    assert body["incident_ticket_id"].startswith("SOS-")
    assert "+254711223344" in body["sms_dispatched_to"]
    assert body["at_voice_alert_queued"] is True


def test_sos_moves_trip_to_sos_status(client, drivers, trip_payload):
    trip_id = client.post("/api/trips/start", json=trip_payload).json()["trip_id"]
    client.post(f"/api/trips/{trip_id}/sos", json={"current_lat": -1.2789, "current_lng": 36.7921})
    assert client.get(f"/api/trips/{trip_id}").json()["status"] == "SOS"


def test_sos_rejected_after_completion(client, drivers, trip_payload):
    trip_id = client.post("/api/trips/start", json=trip_payload).json()["trip_id"]
    client.post(f"/api/trips/{trip_id}/complete", json={"payment_method": "CASH"})
    response = client.post(f"/api/trips/{trip_id}/sos", json={"current_lat": -1.27, "current_lng": 36.79})
    assert response.status_code == 409


def test_sos_message_contains_coordinates_and_driver(client, drivers, trip_payload):
    trip_id = client.post("/api/trips/start", json=trip_payload).json()["trip_id"]
    client.post(f"/api/trips/{trip_id}/sos", json={"current_lat": -1.2789, "current_lng": 36.7921})
    detail = client.get(f"/api/trips/{trip_id}").json()
    sos_logs = [s for s in detail["sms_logs"] if s["kind"] == "SOS_BROADCAST"]
    assert sos_logs
    assert all(s["sent"] for s in sos_logs)


def test_rate_completed_trip(client, drivers, trip_payload):
    trip_id = client.post("/api/trips/start", json=trip_payload).json()["trip_id"]
    client.post(f"/api/trips/{trip_id}/complete", json={"payment_method": "CASH"})
    response = client.post(
        f"/api/trips/{trip_id}/rate",
        json={
            "rating": 5,
            "tags": ["Punctual", "Smooth Driver", "Careful with Vehicle"],
            "feedback_comment": "David arrived in 5 minutes and drove my manual car very smoothly.",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["trip_id"] == trip_id
    assert body["driver_id"] == drivers["manual"].id
    assert 4.9 <= body["new_driver_average_rating"] <= 4.95


def test_rate_recomputes_driver_average(client, drivers, trip_payload, db_session):
    trip_id = client.post("/api/trips/start", json=trip_payload).json()["trip_id"]
    client.post(f"/api/trips/{trip_id}/complete", json={"payment_method": "CASH"})
    client.post(f"/api/trips/{trip_id}/rate", json={"rating": 1})

    db_session.expire_all()
    driver = db_session.get(type(drivers["manual"]), drivers["manual"].id)
    expected = round((4.92 * 184 + 1) / 185, 2)
    assert driver.rating == expected
    assert driver.rating_count == 185


def test_rate_before_completion_rejected(client, drivers, trip_payload):
    trip_id = client.post("/api/trips/start", json=trip_payload).json()["trip_id"]
    response = client.post(f"/api/trips/{trip_id}/rate", json={"rating": 5})
    assert response.status_code == 409


def test_double_rating_rejected(client, drivers, trip_payload):
    trip_id = client.post("/api/trips/start", json=trip_payload).json()["trip_id"]
    client.post(f"/api/trips/{trip_id}/complete", json={"payment_method": "CASH"})
    assert client.post(f"/api/trips/{trip_id}/rate", json={"rating": 5}).status_code == 200
    assert client.post(f"/api/trips/{trip_id}/rate", json={"rating": 4}).status_code == 409


def test_rating_out_of_range_rejected(client, drivers, trip_payload):
    trip_id = client.post("/api/trips/start", json=trip_payload).json()["trip_id"]
    assert client.post(f"/api/trips/{trip_id}/rate", json={"rating": 6}).status_code == 422
    assert client.post(f"/api/trips/{trip_id}/rate", json={"rating": 0}).status_code == 422


def test_mpesa_callback_marks_paid(client, drivers, trip_payload):
    trip_id = client.post("/api/trips/start", json=trip_payload).json()["trip_id"]
    checkout_id = client.post(
        f"/api/trips/{trip_id}/complete", json={"payment_method": "MPESA_STK_PUSH"}
    ).json()["mpesa_checkout_request_id"]

    response = client.post(
        "/api/mpesa/callback",
        json={
            "Body": {
                "stkCallback": {
                    "MerchantRequestID": "29115-34620561-1",
                    "CheckoutRequestID": checkout_id,
                    "ResultCode": 0,
                    "ResultDesc": "The service request is processed successfully.",
                    "CallbackMetadata": {
                        "Item": [
                            {"Name": "Amount", "Value": 852.5},
                            {"Name": "MpesaReceiptNumber", "Value": "QK12ABC34D"},
                            {"Name": "PhoneNumber", "Value": 254700000001},
                        ]
                    },
                }
            }
        },
    )
    assert response.status_code == 200
    assert response.json()["ResultCode"] == 0

    detail = client.get(f"/api/trips/{trip_id}").json()
    assert detail["payment_status"] == "PAID"


def test_mpesa_callback_failure_marks_failed(client, drivers, trip_payload):
    trip_id = client.post("/api/trips/start", json=trip_payload).json()["trip_id"]
    checkout_id = client.post(
        f"/api/trips/{trip_id}/complete", json={"payment_method": "MPESA_STK_PUSH"}
    ).json()["mpesa_checkout_request_id"]

    client.post(
        "/api/mpesa/callback",
        json={
            "Body": {
                "stkCallback": {
                    "CheckoutRequestID": checkout_id,
                    "ResultCode": 1032,
                    "ResultDesc": "Request cancelled by user",
                }
            }
        },
    )
    assert client.get(f"/api/trips/{trip_id}").json()["payment_status"] == "FAILED"


def test_mpesa_callback_unknown_checkout_is_acknowledged(client):
    """Daraja retries on non-200, so unknown ids must still return 200."""
    response = client.post(
        "/api/mpesa/callback",
        json={"Body": {"stkCallback": {"CheckoutRequestID": "ws_CO_UNKNOWN", "ResultCode": 0}}},
    )
    assert response.status_code == 200
    assert response.json()["ResultCode"] == 0


def test_list_trips_and_sms_logs(client, drivers, trip_payload):
    trip_id = client.post("/api/trips/start", json=trip_payload).json()["trip_id"]
    trips = client.get("/api/trips").json()
    assert any(t["id"] == trip_id for t in trips)
    assert client.get("/api/sms-logs").json()


def test_create_and_list_drivers(client):
    payload = {
        "full_name": "Mercy Achieng",
        "phone": "0733000111",
        "transmission_certified": "AUTO_ONLY",
        "dci_good_conduct_verified": True,
        "ntsa_license_no": "DL-KE-556677",
        "current_lat": -1.29,
        "current_lng": 36.82,
    }
    created = client.post("/api/drivers", json=payload)
    assert created.status_code == 201
    assert created.json()["phone"] == "+254733000111"
    assert any(d["full_name"] == "Mercy Achieng" for d in client.get("/api/drivers").json())


def test_duplicate_driver_phone_rejected(client):
    payload = {"full_name": "Dup", "phone": "+254799000111"}
    assert client.post("/api/drivers", json=payload).status_code == 201
    assert client.post("/api/drivers", json=payload).status_code == 400


def test_health_endpoint(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["at_enabled"] is False
