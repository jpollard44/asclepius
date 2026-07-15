# Deploying the Asclepius service

The same codebase runs the private local app and the public multi-tenant
service behind the iOS app. This doc covers the public service.

## Architecture

- **FastAPI** app (`backend/main.py`), one process, served by uvicorn.
- **Auth**: Sign in with Apple → our own access JWT (1 h) + rotating refresh
  token (180 d). A small global `data/auth.db` holds users, refresh-token
  hashes, and APNs device tokens.
- **Per-user SQLite databases** (`data/users/<id>/health.db`). Hard file-level
  tenant isolation: a request can only ever query the database of the user its
  bearer token resolves to (see `backend/tenancy.py`). Deleting an account is
  deleting a directory.
- **HealthKit sync**: the iOS app computes daily aggregates on-device and
  POSTs them to `/api/sync/healthkit` (idempotent upserts). The original
  `export.xml` upload remains as a backfill path.
- **Push**: APNs (HTTP/2, token auth) for iOS + web push for the PWA. A
  5-minute sweep job checks every user's reminder preferences; a dedup log
  guarantees at-most-once delivery.
- **Coach**: the Anthropic API key is a **server-side** secret. Users never
  bring their own key. `ASCLEPIUS_CHAT_DAILY_LIMIT` caps per-user daily coach
  turns.

## Environment

| Variable | Required | Purpose |
| --- | --- | --- |
| `ASCLEPIUS_MULTI_TENANT=1` | yes | Enables accounts + per-user DBs + required auth |
| `ANTHROPIC_API_KEY` | yes | Powers the coach |
| `ASCLEPIUS_SECRET` | recommended | Session-token signing secret (`openssl rand -base64 48`) |
| `ASCLEPIUS_APPLE_BUNDLE_ID` | yes | iOS bundle id (Sign in with Apple audience) |
| `APNS_KEY`, `APNS_KEY_ID`, `APNS_TEAM_ID`, `APNS_TOPIC` | for push | APNs token-auth key from the Apple Developer portal |
| `ASCLEPIUS_CHAT_DAILY_LIMIT` | no (60) | Per-user daily coach-turn budget |
| `ASCLEPIUS_DEV_LOGIN` | never in prod | Email-only login for dev/tests |
| `PORT` | no (8080 in Docker) | Listen port |

## Run it

```bash
docker build -t asclepius .
docker run -p 8080:8080 --env-file .env -v asclepius-data:/app/data asclepius
```

`GET /api/health` is the unauthenticated liveness probe.

Any single-node host with a persistent volume works (Fly.io, Render,
a VPS behind Caddy/nginx). Terminate TLS in front of uvicorn — the iOS app
requires HTTPS (ATS). Point the app at your host by setting
`AsclepiusAPIBaseURL` in `ios/project.yml`.

## Scaling notes

Per-user SQLite on a single node comfortably serves tens of thousands of
users for this workload (a handful of small queries per request; the heavy
lifting is the Anthropic API call). When you outgrow one node:

1. Move coach calls to a queue/worker so slow model turns don't hold request
   workers.
2. Shard users across nodes by user id (the per-user DB layout makes this a
   file move), or
3. Swap `store.connect()` for Postgres with a `user_id` column — the tenancy
   context (`tenancy.current_user_id()`) is already threaded everywhere you'd
   need it.

## Backups & privacy

- Back up the `data/` volume (auth DB + user DBs). Restic/litestream both
  work well with many small SQLite files.
- The only data that leaves the server is the compact summaries sent to the
  Anthropic API for coach turns and food-photo analysis.
- Account deletion (`DELETE /api/account`) is immediate and total: auth rows
  plus the user's entire data directory.
