from app.extensions import db
from app.models import Driver


def make_driver():
    driver = Driver(full_name="Test Driver", phone="+254700000001", availability_status="AVAILABLE",
                    transmission_certification="MANUAL", verification_status="UNVERIFIED",
                    last_latitude=-1.286, last_longitude=36.817, location_source="driver_provided")
    db.session.add(driver)
    db.session.commit()
    return driver


def start_payload(driver_id):
    return {"customer_name": "Amina", "customer_phone": "+254700000002", "pickup_address": "Selected pickup",
            "dropoff_address": "Selected destination", "car_make_model": "Toyota Axio", "registration_plate": "KDA123A",
            "transmission": "AUTOMATIC", "emergency_contact_name": "Sam", "emergency_contact_phone": "+254700000003",
            "driver_id": driver_id}


def test_quote_rejects_unconfigured_routing_without_inventing_a_quote(client):
    response = client.post("/api/quote", json={"pickup_address": "A", "dropoff_address": "B", "transmission": "AUTOMATIC"})
    assert response.status_code == 503
    assert response.json["error"]["code"] == "ROUTING_UNAVAILABLE"


def test_mobile_entry_screen_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Chaufly" in response.data


def test_match_requires_user_permitted_or_selected_coordinate(client):
    response = client.post("/api/drivers/match", json={"transmission": "AUTOMATIC"})
    assert response.status_code == 400
    assert response.json["error"]["code"] == "LOCATION_REQUIRED"


def test_start_persists_trip_and_reports_unconfigured_sms(app, client):
    with app.app_context():
        driver = make_driver()
        response = client.post("/api/trips/start", json=start_payload(driver.id))
    assert response.status_code == 201
    assert response.json["trip"]["status"] == "DRIVER_EN_ROUTE"
    notification = response.json["notifications"][0]
    assert notification["status"] == "NOT_CONFIGURED"
    assert notification["attempted"] is False


def test_invalid_transition_is_rejected(app, client):
    with app.app_context():
        driver = make_driver()
        trip = client.post("/api/trips/start", json=start_payload(driver.id)).json["trip"]
    response = client.patch(f"/api/trips/{trip['id']}/status", json={"status": "COMPLETED"})
    assert response.status_code == 409
    assert response.json["error"]["code"] == "INVALID_STATUS_TRANSITION"


def test_complete_returns_actual_elapsed_duration_not_an_eta(app, client):
    with app.app_context():
        driver = make_driver()
        trip_id = client.post("/api/trips/start", json=start_payload(driver.id)).json["trip"]["id"]
    assert client.patch(f"/api/trips/{trip_id}/status", json={"status": "IN_PROGRESS"}).status_code == 200
    response = client.post(f"/api/trips/{trip_id}/complete")
    assert response.status_code == 200
    assert response.json["duration_minutes"] is not None
    assert response.json["payment_status"] == "NOT_PROCESSED"


def test_sos_persists_incident_when_notifications_are_unconfigured(app, client):
    with app.app_context():
        driver = make_driver()
        trip_id = client.post("/api/trips/start", json=start_payload(driver.id)).json["trip"]["id"]
    response = client.post(f"/api/trips/{trip_id}/sos", json={"trigger_reason": "Need assistance"})
    assert response.status_code == 201
    attempts = response.json["incident"]["notification_attempts"]
    assert len(attempts) == 2
    assert all(item["status"] == "NOT_CONFIGURED" for item in attempts)
