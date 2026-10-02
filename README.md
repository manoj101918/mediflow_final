# MediFlow Reception

Clinic management for an Indian outpatient clinic: the front desk books and runs the day's
appointments, doctors see their own queue, an admin manages staff, doctors, hours and leave,
and WhatsApp / voice bots can book through an API. Everyone signs in on the same login page
and lands on their own role's screens.

- **Backend:** FastAPI (Python 3.12, async SQLAlchemy + asyncpg) on Supabase Postgres
- **Frontend:** React 19 + TypeScript (strict), Vite, Tailwind v4, shadcn/ui, TanStack Query
- **Auth & live updates:** Supabase Auth (ES256 JWTs) and Supabase Realtime

## What each role can do

| Role | Screens |
|---|---|
| Receptionist | **Today**: summary cards, live appointment table with one-click next step (check in → start → complete), no-show / cancel / reschedule, bot bookings to approve, bot requests to handle. **New appointment** (key `N`): find or add the patient (duplicate warning), pick a doctor and a free slot or squeeze in, confirm. **Appointments** (any date range, filters), **Patients** (typo-tolerant search, history, edit), **Doctors** (hours and leave). |
| Doctor | Today's own queue: who is with them, who is waiting (token order, *Call next*), later today, finished. Arrivals appear instantly. Doctors never see other doctors' patients or any phone numbers. |
| Admin | **Staff** accounts (create with generated password, link a doctor login, deactivate). **Doctors**: profile, active flag, weekly multi-shift hours, leave days. |
| Bots | `POST /api/bookings/inbound` (see [Bot booking API](#bot-booking-api)). |

## Architecture

```
 Browser (React)                         FastAPI  (/api)                         Supabase
 ───────────────                         ───────────────                         ────────
 supabase-js ── sign-in ─────────────────────────────────────────────────────▶  Auth (JWT)
 lib/api.ts  ── Bearer JWT ─────────▶    verify JWT (JWKS) → staff profile
                                         routers → services → booking service ─▶ Postgres
 Realtime    ◀── row changes (RLS-filtered with the user's JWT) ─────────────  appointments
 Bots        ── X-API-Key ──────────▶    /bookings/inbound → booking service
```

- **One booking service for every channel.** `backend/app/services/booking/` has no FastAPI
  imports. Dashboard, WhatsApp and voice all call the same functions with an *actor*
  (`StaffActor` or `SystemActor`), so permissions and rules live in one place.
- **Double booking is impossible.** A Postgres exclusion constraint
  (`appointments_no_overlap`) rejects overlapping live appointments per doctor. The service
  turns that into `SLOT_TAKEN` (HTTP 409).
- **Token numbers** restart per doctor per clinic-local day. They're assigned under a
  per-doctor-per-day advisory lock and never reused (a cancelled token stays taken).
- **All data goes through FastAPI.** It connects as the database owner and enforces clinic,
  role and doctor scoping itself. **Row Level Security** is the second line: it governs
  Realtime and any direct Supabase access with a user's token. Doctors see only their own
  appointments and patients, and `anon` sees nothing.
- **Time.** Timestamps are stored and returned in UTC. Days, slots and tokens follow clinic
  time (Asia/Kolkata), and the UI always displays IST.

```
backend/
  app/main.py              app factory: CORS, error envelope, logging, rate limit, routers
  app/core/                config, JWT verification, errors, logging, rate limiting
  app/api/                 routers: me, appointments, patients, doctors, admin, inbound
  app/services/booking/    channel-agnostic booking service (slots, create, status, patients)
  app/services/            read queries, patients, doctors, users, inbound
  app/db/models.py         SQLAlchemy models mirroring the SQL migrations
  scripts/seed_users.py    creates the seeded staff logins
  tests/                   pytest (real database, throwaway clinic per test)
frontend/
  src/pages/               reception/, doctor/, admin/, Login
  src/components/          appointments/, patients/, admin/, layout/, ui/ (shadcn)
  src/lib/                 api client, supabase client, query modules, IST formatting
  e2e/                     Playwright tests
supabase/
  migrations/              schema, RLS and realtime, in the order they were applied
  seed.sql                 demo clinic, doctors, schedules, patients, appointments
```

## Setup

### Prerequisites

- Python 3.12 and [uv](https://docs.astral.sh/uv/). The backend is pinned to the system
  Python (`python-preference = "only-system"`).
- Node 24 and npm.
- A Supabase project (any plan).

> **Windows with Smart App Control:** use the python.org Python 3.12, run tools as
> `uv run python -m pytest` / `-m uvicorn` (not the `.exe` shims), and keep `ruff==0.15.0` and
> `mypy<2` as pinned. Newer native builds of those tools are blocked.

### 1. Database

The schema lives in `supabase/migrations/` and was applied with the Supabase MCP server's
`apply_migration`. Each file is named with the version Supabase recorded, so
`list_migrations` matches the folder. For a new project, apply the files in order (MCP
`apply_migration`, the SQL editor, or `supabase db push`). Then:

1. Run `supabase/seed.sql` (SQL editor or MCP `execute_sql`). It creates the demo clinic,
   doctors, weekly schedules, 30 patients and about 20 appointments around *today*.
2. Configure `backend/.env` (next step), then create the staff logins:
   `cd backend && uv run python -m scripts.seed_users`
3. In the dashboard: **Authentication → Sign In / Providers → turn off "Allow new users to
   sign up"** (staff accounts are created by the admin). Optionally enable
   [leaked-password protection](https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection)
   (may require a paid plan).

After any schema change, add a new migration (never edit an applied one), mirror it in
`app/db/models.py`, and regenerate `frontend/src/types/database.ts` (MCP
`generate_typescript_types`).

### 2. Backend

```bash
cd backend
cp .env.example .env        # fill it in (table below)
uv sync
uv run python -m uvicorn app.main:app --port 8000
```

API docs: <http://localhost:8000/api/docs> (only when `ENV=dev`).

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://…` session pooler (IPv4) or direct connection (IPv6). URL-encode special characters in the password. |
| `SUPABASE_URL` | `https://<ref>.supabase.co`. JWTs are verified against its JWKS. |
| `SUPABASE_SERVICE_ROLE_KEY` | Server-only. Used to create staff logins. |
| `SUPABASE_JWT_SECRET` | Only for projects still signing with the legacy HS256 secret. |
| `CORS_ORIGINS` | Comma-separated frontend origins. |
| `INBOUND_API_KEY` | Shared secret bots send as `X-API-Key`. Use a long random value. |
| `INBOUND_CLINIC_ID` | Clinic that bot bookings go to. |
| `INBOUND_RATE_LIMIT` | Default `30/minute` per client IP. |
| `TEST_DATABASE_URL` | Database used by pytest (can be the same project). |
| `ENV`, `LOG_LEVEL`, `SEED_PASSWORD` | `dev` / `prod`, log level, seed-script password. |

### 3. Frontend

```bash
cd frontend
cp .env.example .env.local  # VITE_SUPABASE_URL, VITE_SUPABASE_PUBLISHABLE_KEY, VITE_API_URL
npm install
npm run dev                 # http://localhost:5173
```

Only public values go in `.env.local`, never the service-role key.

### Demo logins

Password for all: `Clinic@12345`

| Role | Email |
|---|---|
| Admin | `admin@mediflow.test` |
| Receptionist | `reception1@mediflow.test`, `reception2@mediflow.test` |
| Doctor | `dr.sharma@mediflow.test`, `dr.iyer@mediflow.test`, `dr.khan@mediflow.test` |

## Testing

```bash
# Backend: lint, format, types, tests (~5 min against a remote database)
cd backend
uv run ruff check . && uv run ruff format --check . && uv run mypy app scripts tests
uv run python -m pytest

# Frontend
cd frontend
npm run lint && npm run typecheck && npm run build
npm run e2e        # Playwright; starts the dev servers if they are not running
```

- **Backend tests (152)** run against `TEST_DATABASE_URL`. Each test creates its own clinic,
  staff and patients and deletes them afterwards, so seed data is never touched. They cover:
  - slot generation, conflicts and concurrent bookings (exactly one wins), token sequencing
  - the transition rules and every endpoint's permissions
  - Row Level Security, checked by switching to the real `authenticated` / `anon` roles
  - the bot endpoint: auth, idempotency, rate limit and the needs-review cases
- **E2E tests** run against the dev servers and the seeded clinic: a booking made by one
  receptionist appears live on another's screen, and each role stays on its own screens.
  - They book *tomorrow* and cancel what they created.
  - They use the installed Google Chrome by default. Set `E2E_BROWSER_CHANNEL=chromium` after
    `npx playwright install chromium` to use the bundled browser instead.

## Bot booking API

`POST /api/bookings/inbound` with headers `X-API-Key: <INBOUND_API_KEY>` and
`Content-Type: application/json`:

```json
{
  "channel": "whatsapp",
  "external_ref": "wamid.HBgMOTE5ODQ4MDEyMzQ1FQIAERgS",
  "caller_phone": "98480 12345",
  "patient_name": "Ravi Kumar",
  "doctor_id": "d0c00000-0000-4000-8000-000000000003",
  "requested_time": "2026-10-03T09:30:00+05:30",
  "reason": "Knee pain"
}
```

- `channel` is `whatsapp` or `voice`. `external_ref` is the bot's unique id for the request:
  **retries with the same id never book twice**, even when they arrive at the same moment.
- Every request is stored (raw JSON included) in `inbound_booking_requests` before it is
  processed, with its outcome.
- The patient is matched by phone plus a similar name (families can share a phone), or
  created.

| Status | Meaning | Body |
|---|---|---|
| `201` | Booked as **pending confirmation**. It appears instantly in reception's "Waiting for confirmation" panel for approval. | `status: "auto_booked"`, `appointment {id, token_number, starts_at, doctor_name}` |
| `200` | Duplicate `external_ref`. Nothing new was booked. | The earlier result, `duplicate: true` |
| `202` | Could not book automatically (slot taken, outside hours, doctor on leave, no doctor or time given). The front desk sees it under "Bot requests to handle". | `status: "needs_review"`, `error_code`, `message`, `suggested_slots` (up to 5 free slots to offer the caller) |
| `422` | Invalid content (bad phone, missing name) or malformed JSON | Error envelope. Stored requests include `details.request_id`. |
| `401` / `429` | Wrong key / rate limit exceeded | Error envelope (`Retry-After` on 429) |

All errors use one envelope: `{"error": {"code": "...", "message": "...", "details": ...}}`.

## Adding a booking channel

Example: an SMS bot.

1. **Migration:** add the value to the `inbound_channel` and `appointment_source` enums, and
   extend the `appointment_events.channel` check constraint. Mirror the change in
   `app/db/models.py` and regenerate `frontend/src/types/database.ts`.
2. **Backend:** add it to `SystemChannel` in `app/services/booking/actor.py` and
   `_system_channel` in `app/services/inbound.py`.
3. **Frontend:** add a label and icon to `SOURCE_META` in `src/lib/appointments.ts`.
4. **Bot:** point it at `POST /api/bookings/inbound` with its own `channel` value. No booking
   logic needs to change. Slots, conflicts, tokens, patient matching and front-desk approval
   all come from the shared booking service.

Different authentication (for example a per-channel key or a webhook signature) belongs in
`app/api/inbound.py`, in front of the same service call.

## Decisions and assumptions

- **Time:** weekday `0` = Monday (Python `weekday()`). `appointment_date` holds the clinic-local
  (IST) date, set by a trigger, and scopes token numbers.
- **Tokens:** restart per doctor per day and are never reused.
- **Slots:** pending (bot) bookings hold their slot until approved or rejected.
- **Squeeze-in** (front desk only) bypasses the slot grid but never the overlap constraint or
  leave days.
- **Past times:** bookings may start up to 5 minutes in the past; anything earlier is rejected.
- **Rescheduling** keeps the doctor and is allowed while pending or scheduled. Moving to
  another day assigns a new token.
- **Status changes:**
  - Doctors may only start and complete their own consultations; check-in is the front
    desk's job.
  - A doctor gets "not found" for other doctors' appointments.
  - Bots can book but cannot change status.
- **Patients:**
  - Phones are stored in E.164, and 10-digit numbers default to +91.
  - The same patient means the same phone and a name similarity above 0.6.
  - Search uses `word_similarity` ≥ 0.3, so "laxmi" finds "Lakshmi Narayanan".
- **Bot bookings** go to a single clinic (`INBOUND_CLINIC_ID`).

## Known limitations and next steps

- The rate limiter is in memory: correct for one API process. Use a shared store (Redis) if
  you run several.
- "Bot requests to handle" polls every 30 seconds (those rows are not in the Realtime
  publication). Appointments themselves are live.
- Leaked-password protection is off. The Supabase advisor reports it until it's enabled in
  the dashboard.
- The UI assumes the clinic is in IST for display. The backend already supports a per-clinic
  time zone (`clinics.timezone`).
