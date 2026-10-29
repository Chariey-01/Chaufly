import os


class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///chaufly.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    AT_USERNAME = os.getenv("AT_USERNAME", "sandbox")
    AT_API_KEY = os.getenv("AT_API_KEY")
    AT_VOICE_FROM = os.getenv("AT_VOICE_FROM")
    OPERATIONS_ALERT_RECIPIENTS = os.getenv("OPERATIONS_ALERT_RECIPIENTS", "")
    ROUTING_PROVIDER = os.getenv("ROUTING_PROVIDER", "unconfigured")
