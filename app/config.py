"""Application settings loaded from environment / .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "iFinder"
    environment: str = "development"
    base_url: str = "http://localhost:8000"
    public_tracking_base: str = "http://localhost:8000/track"

    database_url: str = "sqlite:///./ifinder.db"

    # --- Africa's Talking ---------------------------------------------------
    at_enabled: bool = False
    at_username: str = "sandbox"
    at_api_key: str = ""
    at_sender_id: str = "iFinder"
    at_sms_url: str = "https://api.africastalking.com/version1/messaging"
    at_voice_url: str = "https://voice.africastalking.com/call"
    at_http_timeout: float = 10.0

    # --- Pricing ------------------------------------------------------------
    fare_base: float = 300.0
    fare_per_km: float = 65.0
    quote_ttl_seconds: int = 300
    avg_speed_kmh: float = 21.25
    approach_speed_kmh: float = 15.0

    # --- M-Pesa -------------------------------------------------------------
    mpesa_enabled: bool = False
    mpesa_env: str = "sandbox"
    mpesa_consumer_key: str = ""
    mpesa_consumer_secret: str = ""
    mpesa_shortcode: str = "174379"
    mpesa_passkey: str = ""
    mpesa_callback_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
