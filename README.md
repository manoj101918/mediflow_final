# MediFlow Reception

Clinic management for an Indian outpatient clinic: the front desk books and runs the day's
appointments, doctors see their own queue and open a patient's chart (history,
prescriptions, reports) with an assistant that answers questions from that patient's records
only, an admin manages staff, doctors, hours and leave, and WhatsApp / voice bots can book
through an API. Everyone signs in on the same login page and lands on their own role's
screens.

- **Backend:** FastAPI (Python 3.12, async SQLAlchemy + asyncpg) on Supabase Postgres
- **Frontend:** React 19 + TypeScript (strict), Vite, Tailwind v4, shadcn/ui, TanStack Query
- **Auth & live updates:** Supabase Auth (ES256 JWTs) and Supabase Realtime
- **Records assistant:** LangChain (`langchain-core`), Groq chat models, Voyage AI
  embeddings, pgvector in the same Postgres, private Supabase Storage for report files

## What each role can do

| Role | Screens |
|---|---|
| Receptionist | **Today**: summary cards, live appointment table with one-click next step (check in → start → complete), no-show / cancel / reschedule, *Upload report*, bot bookings to approve, bot requests to handle. **New appointment** (key `N`): find or add the patient (duplicate warning), pick a doctor and a free slot or squeeze in, confirm. **Appointments** (any date range, filters), **Patients** (typo-tolerant search, history, edit, upload reports and see their status, never their contents or any clinical notes), **Doctors** (hours and leave). |
| Doctor | Today's own queue: who is with them, who is waiting (token order, *Call next*), later today, finished. Arrivals appear instantly. **Patient chart** (from the queue): demographics, red allergy badges, chronic conditions; **Current visit** (notes, vitals, prescription builder with *Repeat last*, attach report, autosave, *Complete*); **Visit history** across all doctors with addenda; **Medications** (current ones highlighted); **Reports** (upload, inline viewer, indexing status, Retry); **Vitals trend**; and **Ask about this patient**, a chat that answers only from the patient's records with clickable citations. Doctors never see phone numbers. |
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
 Chart       ── Bearer JWT ─────────▶    records service ──────────────────────▶ clinical tables
 Report file ◀── 60 s signed URL ────    Storage (service role) ───────────────▶ patient-reports
 Chat (SSE)  ── fetch stream ───────▶    RAG service → retriever (pgvector + FTS) ─▶ chunks
                                         ingestion worker (asyncio) → Voyage → chunks
                                         chat model ──────────────────────────▶ Groq
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
- **Clinical data is backend-only.** Consultations, prescriptions, reports, chunks, chat and
  the access log have RLS on with no client policies, so only FastAPI can read them. The
  records service decides access (see [Decisions](#decisions-and-assumptions)).

```
backend/
  app/main.py              app factory: CORS, error envelope, logging, rate limit, routers,
                           ingestion worker (lifespan)
  app/core/                config, JWT verification, errors, logging, rate limiting
  app/api/                 routers: me, appointments, patients, doctors, admin, inbound,
                           records, reports, chat
  app/services/booking/    channel-agnostic booking service (slots, create, status, patients)
  app/services/records/    chart access, consultations, prescriptions, addenda, medical
                           profile, reports + storage, access log
  app/services/ingestion/  job queue, worker, rendering, PDF extraction, chunking, indexer
  app/services/rag/        providers, patient retriever, summary, prompt, citations, chat
  app/services/            read queries, patients, doctors, users, inbound
  app/db/models.py         SQLAlchemy models mirroring the SQL migrations
  scripts/                 seed_users, seed_clinical (synthetic history), reindex
  tests/                   pytest (real database, throwaway clinic per test); tests/live
                           is the live RAG evaluation
frontend/
  src/pages/               reception/, doctor/ (DoctorToday, PatientChart), admin/, Login
  src/components/          appointments/, patients/, chart/, chat/, admin/, layout/, ui/
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
3. Add the synthetic clinical history (fake data: past visits, prescriptions, medical
   profiles and lab PDFs for 5 seed patients) and index it for the assistant:
   `uv run python -m scripts.seed_clinical` (needs `VOYAGE_API_KEY`; with
   `RAG_FAKE_LLM=true` it indexes with fake embeddings instead). Idempotent.
4. In the dashboard: **Authentication → Sign In / Providers → turn off "Allow new users to
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
| `GROQ_API_KEY` | Chat model provider (server-only). Without it the assistant answers 503. |
| `LLM_MODEL`, `LLM_REASONING_EFFORT`, `LLM_MAX_TOKENS` | Default `openai/gpt-oss-120b` (Groq free tier), `low`, `1024`. |
| `VOYAGE_API_KEY` | Embeddings provider (server-only). Without it indexing pauses; jobs stay queued. |
| `EMBEDDING_MODEL`, `EMBEDDING_DIM` | Default `voyage-4`, `1024`. The dimension must match the `vector(1024)` column. Changing the model needs `scripts.reindex --all`. |
| `RAG_TOP_K`, `RAG_CHUNK_SIZE`, `RAG_CHUNK_OVERLAP`, `RAG_MAX_HISTORY_TURNS` | Retrieval and chunking: `6`, `1000`, `150` characters, `4` turns. |
| `RAG_FAKE_LLM` | `true` = deterministic fake chat model + fake embeddings (tests, E2E, demos without keys). |
| `CHAT_RATE_LIMIT` | Questions per signed-in user, default `6/minute`. |
| `REPORT_MAX_MB` | Upload limit, default `10` (must match the `patient-reports` bucket limit). |
| `MIN_TEXT_CHARS_PER_PAGE` | PDFs with less extracted text per page are treated as scans (stored, not searchable). |
| `SIGNED_URL_TTL_SECONDS` | Lifetime of report view links, default `60`. |
| `INGESTION_WORKER_ENABLED`, `INGESTION_MAX_ATTEMPTS` | Background indexing in the API process (`true`), retries (`5`). |

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
# Backend: lint, format, types, tests (~10 min against a remote database)
cd backend
uv run ruff check . && uv run ruff format --check . && uv run mypy app scripts tests
uv run python -m pytest
uv run python -m pytest -m live -s tests/live   # live RAG evaluation (real API keys)

# Frontend
cd frontend
npm run lint && npm run typecheck && npm run build
npm run e2e        # Playwright; starts the dev servers if they are not running
```

- **Backend tests (196)** run against `TEST_DATABASE_URL`. Each test creates its own clinic,
  staff and patients and deletes them afterwards, so seed data is never touched. No test
  calls a paid API: models are replaced by LangChain fakes. They cover:
  - slot generation, conflicts and concurrent bookings (exactly one wins), token sequencing
  - the transition rules and every endpoint's permissions
  - Row Level Security, checked by switching to the real `authenticated` / `anon` roles
  - the bot endpoint: auth, idempotency, rate limit and the needs-review cases
  - clinical access (any clinic doctor reads, only the visit's doctor writes, reception 403),
    finalized records are read-only, addenda, atomic *Complete*
  - uploads (type from bytes, size, storage path), ingestion (jobs → chunks, idempotent
    re-runs, replaced content, unreadable and scanned PDFs, retries, the worker loop)
  - patient isolation: two near-identical patients, zero cross-patient chunks on every
    retrieval path; chat SSE order, citations, persistence, rate limit, provider errors;
    prompt injection from an uploaded report
- **Live evaluation** (`tests/live`, deselected by default): 15 questions with expected facts
  over the seeded test patient (each answer must contain the facts and a valid citation)
  and 3 questions the records cannot answer (the answer must say so). Prints a scorecard.
  Paced for the Groq free tier.
- **E2E tests** run against the dev servers and the seeded clinic: a booking made by one
  receptionist appears live on another's screen, each role stays on its own screens, and a
  doctor opens a checked-in patient, sees the history and gets a cited answer.
  - They book *tomorrow* and cancel what they created.
  - The chart test needs the clinical seed and the API in `RAG_FAKE_LLM=true` mode (Playwright
    starts it that way; an API that is already running is reused as is).
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

## Patient-record assistant (RAG pipeline)

The doctor's "Ask about this patient" panel answers from one patient's records only, and every
statement cites its source.

**1. Records become text (ingestion).** Finalizing a visit, adding an addendum, uploading a
report or editing the medical profile enqueues a job (`ingestion_jobs`) in the same database
transaction. A background worker inside the API process picks jobs up within a few seconds
(`FOR UPDATE SKIP LOCKED`, retries with backoff):
- a finalized visit becomes one readable chunk with its date, doctor, complaint, diagnosis,
  vitals, prescription and addenda ("Visit on 12 Mar 2026 (IST) with Dr. Anil Sharma, General
  Physician. … Prescription: 1) Metformin 1000 mg tablet 1-0-1 after food for 90 days …");
- the medical profile (blood group, allergies, chronic conditions) is its own chunk;
- report PDFs are read page by page with pypdf, split into overlapping chunks, and every chunk
  starts with "Report: <title> (<type>, dated …), page N". Images and scanned PDFs (no text
  layer) are stored and viewable but marked *Not searchable*; there is no OCR.

Chunks are embedded with Voyage AI (`voyage-4`, 1024 dimensions) and stored in
`patient_record_chunks` (pgvector, HNSW index, plus a generated full-text column). Content
hashes make re-indexing idempotent: unchanged text is never re-embedded.

**2. A question becomes context (retrieval).** For each question the server:
- checks access (doctors only) and the per-user rate limit, and logs the question;
- rewrites follow-ups ("and before that?") into a standalone query using the last turns;
- searches **only this patient's chunks** (every query filters on clinic, patient and
  embedding model): exact vector similarity plus full-text search for drug and test names,
  merged with reciprocal rank fusion;
- for time questions ("last 3 visits", "trend", "since the last visit") also adds the most
  recent visits directly;
- builds a structured summary from SQL as source [1]: age, sex, allergies, chronic
  conditions, current medications (courses not yet finished), last visit, today's date (IST).

**3. The model answers (generation).** Sources are numbered and ordered by date inside
`<patient_records>` delimiters; record text is escaped so an uploaded document cannot inject
instructions. The fixed system prompt tells the model to answer only from the records, to say
plainly when something isn't in them, to cite every fact as `[n]`, to mention allergies for
medication questions, to use tables for trends, and not to make diagnoses or treatment
decisions. The chat model is Groq `openai/gpt-oss-120b` (free tier, reasoning hidden).

**4. Streaming and citations.** `POST /api/patients/{id}/chat` streams Server-Sent Events:
`token` (many), then `citations` (each `[n]` used, mapped to the visit, report page or
summary) and `done`, or a friendly `error` (timeout, provider busy). The browser reads the
stream with `fetch` because `EventSource` cannot send the Authorization header. Clicking a
citation opens the cited visit or the report at its page. Every question and answer is saved
with token counts and latency; prompts, answers and record text are never written to logs.

Models are created in one place (`app/services/rag/providers.py`), so the provider can be
swapped. `RAG_FAKE_LLM=true` replaces both with deterministic fakes.

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
- **Clinical records access:**
  - Any doctor of the clinic can open any patient's full chart (all doctors' visits,
    prescriptions and reports) and ask the assistant about it.
  - Only the appointment's own doctor writes the visit notes and prescription, and only while
    the patient is checked in or in consultation.
  - Reception and admin can upload reports and see their title, type, date and indexing
    status, but never notes, prescriptions, report contents or the assistant (403).
  - Every chart open, report view or upload and assistant question is written to an access
    log (ids only).
- **Visits:** one consultation per appointment. *Complete* finalizes the notes and completes
  the appointment in one transaction (also when reception completes the visit); completing
  without notes is allowed after a warning. Finalized notes are read-only; corrections are
  addenda.
- **Medical profile** (blood group, allergies, chronic conditions) is edited by doctors and
  kept in its own table, apart from the front-desk patient record.
- **Medications are "current"** while their course (visit date + duration) has not ended.
- **Reports:** PDF, JPEG or PNG up to 10 MB, checked from the file's bytes; stored in a private
  bucket and shown through 60-second signed links. Uploaded reports are never edited or
  deleted.
- **Assistant:** Groq free-tier model and Voyage embeddings (see the RAG section). Chat
  conversations belong to the doctor who started them.

## Known limitations and next steps

- The rate limiters (bot endpoint and chat) are in memory: correct for one API process. Use a
  shared store (Redis) if you run several. Several API processes are fine for ingestion (jobs
  are claimed with `SKIP LOCKED`).
- No OCR: scanned PDFs and photos are stored but not searchable by the assistant.
- The Groq free tier allows about 8K tokens per minute (two or three questions a minute) and
  200K per day; the prompt is kept to roughly 4K tokens. A paid tier or another provider in
  `providers.py` removes the limit.
- Printing, e-prescriptions, ABDM/ABHA, drug interaction checks and a patient-facing
  assistant are out of scope.
- "Bot requests to handle" polls every 30 seconds (those rows are not in the Realtime
  publication). Appointments themselves are live.
- Leaked-password protection is off. The Supabase advisor reports it until it's enabled in
  the dashboard.
- The UI assumes the clinic is in IST for display. The backend already supports a per-clinic
  time zone (`clinics.timezone`).
