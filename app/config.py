import os


class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///chaufly.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    AT_USERNAME = os.getenv("AT_USERNAME", "sandbox")
    AT_API_KEY = os.getenv("AT_API_KEY")
    AT_VOICE_FROM = os.getenv("AT_VOICE_FROM")
    AT_VOICE_CALLBACK_URL = os.getenv("AT_VOICE_CALLBACK_URL")
    AT_SMS_SENDER_ID = os.getenv("AT_SMS_SENDER_ID")
    OPERATIONS_ALERT_RECIPIENTS = os.getenv("OPERATIONS_ALERT_RECIPIENTS", "")
    ROUTING_PROVIDER = os.getenv("ROUTING_PROVIDER", "unconfigured")
    ORS_API_KEY = os.getenv("ORS_API_KEY")
    ORS_BASE_URL = os.getenv("ORS_BASE_URL", "https://api.openrouteservice.org")
    FARE_BASE_KES = int(os.getenv("FARE_BASE_KES", "300"))
    FARE_MINIMUM_KES = int(os.getenv("FARE_MINIMUM_KES", "300"))
    FARE_PER_KM_KES = int(os.getenv("FARE_PER_KM_KES", "80"))
