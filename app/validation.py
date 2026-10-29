import re

PHONE_RE = re.compile(r"^\+?[1-9]\d{7,14}$")
TRANSMISSIONS = {"MANUAL", "AUTOMATIC"}


class ValidationError(Exception):
    def __init__(self, message, fields=None):
        self.message = message
        self.fields = fields or {}


def payload(request):
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise ValidationError("A JSON object request body is required.")
    return value


def required(data, names):
    missing = {name: "Required." for name in names if not str(data.get(name, "")).strip()}
    if missing:
        raise ValidationError("Validation failed.", missing)


def phone(value, field):
    if not isinstance(value, str) or not PHONE_RE.fullmatch(value.replace(" ", "")):
        raise ValidationError("Validation failed.", {field: "Use an international phone number, e.g. +2547XXXXXXXX."})


def transmission(value):
    if value not in TRANSMISSIONS:
        raise ValidationError("Validation failed.", {"transmission": "Must be MANUAL or AUTOMATIC."})


def coordinates(data, prefix=""):
    lat_key, lon_key = f"{prefix}latitude", f"{prefix}longitude"
    if lat_key not in data and lon_key not in data:
        return None
    try:
        lat, lon = float(data[lat_key]), float(data[lon_key])
    except (KeyError, TypeError, ValueError):
        raise ValidationError("Validation failed.", {lat_key: "Latitude and longitude must be numeric."})
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValidationError("Validation failed.", {lat_key: "Coordinates are outside valid ranges."})
    return lat, lon
