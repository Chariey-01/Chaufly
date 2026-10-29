from app.services import notifications


def test_sms_preserves_provider_acceptance_metadata(app, monkeypatch):
    class SMS:
        def send(self, message, recipients, sender_id=None):
            assert message == "Trip started"
            assert recipients == ["+254700000003"]
            assert sender_id is None
            return {"SMSMessageData": {"Recipients": [{"status": "Success", "messageId": "AT-123"}]}}

    class Client:
        pass

    Client.SMS = SMS()

    with app.app_context():
        monkeypatch.setattr(notifications, "_client", lambda: (Client(), None))
        result = notifications.send_sms(["+254700000003"], "Trip started")

    assert result.status == "PROVIDER_RESPONSE"
    assert result.provider_status == "Success"
    assert result.provider_message_id == "AT-123"


def test_notification_provider_error_is_safe(app, monkeypatch):
    class SMS:
        def send(self, *_args, **_kwargs):
            raise RuntimeError("provider response containing a secret must not escape")

    class Client:
        pass

    Client.SMS = SMS()

    with app.app_context():
        monkeypatch.setattr(notifications, "_client", lambda: (Client(), None))
        result = notifications.send_sms(["+254700000003"], "Trip started")

    assert result.status == "FAILED"
    assert result.detail == "Provider request failed: RuntimeError."


def test_voice_request_uses_official_sdk_voice_service(app, monkeypatch):
    class Voice:
        def call(self, sender, recipients):
            assert sender == "+254700000099"
            assert recipients == ["+254700000003"]
            return {"entries": [{"status": "Queued"}]}

    class Client:
        pass

    Client.Voice = Voice()

    with app.app_context():
        app.config["AT_API_KEY"] = "test-key"
        app.config["AT_VOICE_FROM"] = "+254700000099"
        monkeypatch.setattr(notifications, "_client", lambda: (Client(), None))
        result = notifications.queue_voice_alert("+254700000003", "SOS")

    assert result.status == "PROVIDER_RESPONSE"
    assert result.attempted is True
