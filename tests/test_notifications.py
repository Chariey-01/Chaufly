from app.services import notifications


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
