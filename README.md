# Chaufly Dial a Driver MVP

Chaufly helps a car owner request a qualified driver to drive the owner's own vehicle. This backend-first MVP is deliberately transparent: it never creates fake route data, GPS coordinates, SMS delivery, voice-call completion, or payment success.

## Current implementation

- Flask REST API with SQLite persistence through SQLAlchemy.
- Driver/car transmission eligibility: MANUAL drivers may drive either transmission; AUTOMATIC drivers may drive AUTOMATIC only.
- Persistent trip lifecycle, SOS incidents, optional ratings, consistent JSON errors, and protected transitions.
- Africa's Talking SDK integration boundary for sandbox SMS and Voice requests. A trip or SOS incident is committed before alerts are attempted.
- No seeded driver or location data: add only consenting, clearly labelled test data through an admin/seeding process before a demo.

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python wsgi.py
```

The server listens on `http://127.0.0.1:5000`; check it with `GET /api/health`.

Run tests:

```bash
pytest -q
```

## Configuration

Copy `.env.example` and provide values through your environment (the application does not load `.env` itself):

- `AT_USERNAME` and `AT_API_KEY`: Africa's Talking sandbox credentials.
- `AT_VOICE_FROM`: Africa's Talking Voice caller ID/number required before a Voice request can be attempted.
- `OPERATIONS_ALERT_RECIPIENTS`: optional comma-separated operational SOS contacts.
- `ROUTING_PROVIDER`: remains `unconfigured` until a real routing adapter is implemented.
- `DATABASE_URL`: defaults to `sqlite:///chaufly.db`.

## API

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/health` | Health check |
| POST | `/api/quote` | Requires a real route adapter; currently returns `ROUTING_UNAVAILABLE` rather than inventing a quote |
| POST | `/api/drivers/match` | Requires user-permitted or explicitly selected pickup coordinates and filters by radius/qualification |
| POST | `/api/trips/start` | Persists `DRIVER_EN_ROUTE`; attempts trusted-contact SMS |
| GET | `/api/trips/<trip_id>` | Retrieves safe trip/status fields |
| PATCH | `/api/trips/<trip_id>/status` | Allows only legal lifecycle transitions |
| POST | `/api/trips/<trip_id>/sos` | Persists incident and attempts SMS plus Voice alert |
| POST | `/api/trips/<trip_id>/complete` | Completes trip; payment remains `NOT_PROCESSED` |
| POST | `/api/trips/<trip_id>/rate` | Accepts one 1–5 rating after completion |

Errors use `{ "error": { "code", "message", "fields"? } }` and do not include keys or tracebacks.

## Africa's Talking sandbox status

`app/services/notifications.py` calls the official `africastalking` Python SDK when credentials are present. Its SMS result is returned as `PROVIDER_RESPONSE`; this means only that the provider responded, not that a recipient received a message. The Voice integration sends an actual call request only when both credentials and `AT_VOICE_FROM` are set; it reports the real SDK response or failure and never represents call completion.

Before an end-to-end test, obtain sandbox credentials and Voice access/callback requirements from Africa's Talking and use consenting sandbox test numbers. The repository contains no credentials and no delivery/call-success mock.

## Known limitations and next steps

- A routing/geocoding provider has not been configured, so route-based quotes, distance, and ETA are intentionally unavailable.
- A minimal mobile-first browser UI is included for location-aware matching, trip-status lookup, and confirmed SOS. The next phase is a complete customer request and quote flow wired to these APIs.
- Driver verification, live location, authentication, authorization, rate limiting, audit logging, tracking, M-Pesa settlement, and operations tooling are not implemented.
- Seed only consented demo drivers; mark their location and verification sources accurately.
