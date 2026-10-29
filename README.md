# Chaufly Dial a Driver MVP

Chaufly helps a car owner request a qualified driver to drive the owner's own vehicle. This backend-first MVP is deliberately transparent: it never creates fake route data, GPS coordinates, SMS delivery, voice-call completion, or payment success.

## Current implementation

- Flask REST API with SQLite persistence through SQLAlchemy.
- Driver/car transmission eligibility: MANUAL drivers may drive either transmission; AUTOMATIC drivers may drive AUTOMATIC only.
- Persistent trip lifecycle, SOS incidents, optional ratings, consistent JSON errors, and protected transitions.
- Africa's Talking SDK integration boundary for sandbox SMS and Voice requests. A trip or SOS incident is committed before alerts are attempted, and each attempt is stored with its provider response/status when supplied.
- OpenRouteService integration for real address geocoding and driving directions when configured.
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

## Deployment

The Flask app serves its frontend and API from one origin, so no browser CORS policy is required or enabled. It includes a Dockerfile and `railway.toml` for Railway-compatible deployment; Gunicorn listens on the platform-provided `PORT` and Railway checks `GET /api/health`.

Before deployment, attach a persistent PostgreSQL database and set its connection string as `DATABASE_URL` (use `postgresql://...` rather than a local SQLite file). The current MVP calls `db.create_all()` at startup; it is suitable for initial schema creation only. Introduce and run reviewed migrations before production schema changes—do not rely on `create_all()` for schema evolution.

Set all provider and fare variables listed below as service variables, not in source or frontend code. Until credentials are supplied, the API returns its documented unavailable states. Run the deployment from an authenticated Railway account with `railway up`; no deployment has been created by this repository yet.

## Configuration

Copy `.env.example` and provide values through your environment (the application does not load `.env` itself):

- `AT_USERNAME` and `AT_API_KEY`: Africa's Talking sandbox credentials.
- `AT_SMS_SENDER_ID`: optional Africa's Talking sender ID; leave empty if the sandbox resource does not require one.
- `AT_VOICE_FROM`: Africa's Talking Voice caller ID/number required before a Voice request can be attempted.
- `AT_VOICE_CALLBACK_URL`: public HTTPS URL configured against the Voice number. Use `https://<public-host>/api/webhooks/voice/calls`; it is configuration metadata, not a secret.
- `OPERATIONS_ALERT_RECIPIENTS`: optional comma-separated operational SOS contacts.
- `ROUTING_PROVIDER`: set to `openrouteservice` to enable the real adapter.
- `ORS_API_KEY`: OpenRouteService API key, sent only in the request authorization header.
- `ORS_BASE_URL`: defaults to `https://api.openrouteservice.org`; override only for an approved compatible endpoint.
- `FARE_BASE_KES`, `FARE_MINIMUM_KES`, `FARE_PER_KM_KES`: integer fare settings. The quote formula is `max(minimum, base + distance_km × per_km)`.
- `DATABASE_URL`: defaults to `sqlite:///chaufly.db`.

## API

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/health` | Health check |
| POST | `/api/quote` | Takes pickup/drop-off coordinates or addresses; provider-derived directions generate the quote |
| POST | `/api/drivers/match` | Requires user-permitted or explicitly selected pickup coordinates and filters by radius/qualification |
| POST | `/api/trips/start` | Persists `DRIVER_EN_ROUTE`; attempts trusted-contact SMS |
| GET | `/api/trips/<trip_id>` | Retrieves safe trip/status fields |
| PATCH | `/api/trips/<trip_id>/status` | Allows only legal lifecycle transitions |
| POST | `/api/trips/<trip_id>/sos` | Persists incident and attempts SMS plus Voice alert |
| POST | `/api/trips/<trip_id>/complete` | Completes trip; payment remains `NOT_PROCESSED` |
| POST | `/api/trips/<trip_id>/rate` | Accepts one 1–5 rating after completion |
| POST | `/api/webhooks/voice/calls` | Public VoiceXML callback for the configured Africa's Talking Voice number |

Errors use `{ "error": { "code", "message", "fields"? } }` and do not include keys or tracebacks.

## Africa's Talking sandbox status

`app/services/notifications.py` calls the official `africastalking` Python SDK when credentials are present. Its SMS result is stored with the exact returned provider status and message ID when supplied; this means only that the provider responded, not that a recipient received a message. The Voice integration sends an actual call request only when both credentials and `AT_VOICE_FROM` are set; it stores the provider response/status/session ID, returns a safe failure class when the request fails, and never represents call completion.

To test sandbox SMS, create/select the Africa's Talking Sandbox app, obtain its sandbox API key, use `AT_USERNAME=sandbox`, and register consenting simulator numbers. Sandbox interactions occur in Africa's Talking's simulator rather than on physical handsets; inspect the simulator/session logs for actual SMS acceptance. Configure any SMS resource/sender ID required by that sandbox app.

For Voice, configure a Voice phone number in the Africa's Talking dashboard and set its callback URL to the public HTTPS `AT_VOICE_CALLBACK_URL` above (Dashboard → Voice → Phone Numbers → Actions → callback URL). Expose localhost with a tunnel only for development; Africa's Talking must be able to reach the URL. As of the provider's February 2026 Voice Sandbox notice, the Voice sandbox is not operational; request a Voice **Test Number** through Dashboard → Voice → Phone number / Voice Phones, and contact `voice@africastalking.com` for testing assistance. Therefore no sandbox Voice completion can currently be verified by this repository.

To enable routing, create an OpenRouteService account/key with Directions and Geocoding access, set `ROUTING_PROVIDER=openrouteservice` and `ORS_API_KEY`, then submit `/api/quote` with either `pickup_latitude`/`pickup_longitude` and `dropoff_latitude`/`dropoff_longitude`, or addresses. The adapter calls the documented driving-car directions endpoint and uses only its returned distance/duration.

## Known limitations and next steps

- Africa's Talking and OpenRouteService credentials are absent in this workspace, so live SMS, Voice, geocoding, and directions requests have not been made or verified.
- A minimal mobile-first browser UI is included for location-aware matching, trip-status lookup, and confirmed SOS. The next phase is a complete customer request and quote flow wired to these APIs.
- Driver verification, live location, authentication, authorization, rate limiting, audit logging, tracking, M-Pesa settlement, and operations tooling are not implemented.
- Seed only consented demo drivers; mark their location and verification sources accurately.
