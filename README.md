# MediFlow Reception

Clinic management for an Indian outpatient clinic: the front desk books and runs the day's
appointments, doctors see their own queue and open a patient's chart (history,
prescriptions, reports, lab results) with an assistant that answers questions from that
patient's records only, the clinic's own lab works through doctors' test orders and releases
results straight into the chart, an admin manages staff, doctors, hours, leave and the lab test
catalog, and patients book over **WhatsApp** (buttons, typed text or voice notes in Telugu,
Hindi or English) with reception approving each request. A browser **voice booking simulator**
demos the future phone line on the same conversation engine. Other bots can book through an
API. Everyone signs in on the same login page and lands on their own role's screens.

- **Backend:** FastAPI (Python 3.12, async SQLAlchemy + asyncpg) on Supabase Postgres
- **Frontend:** React 19 + TypeScript (strict), Vite, Tailwind v4, shadcn/ui, TanStack Query
- **Auth & live updates:** Supabase Auth (ES256 JWTs) and Supabase Realtime
- **Records assistant:** LangChain (`langchain-core`), Groq chat models, Voyage AI
  embeddings, pgvector in the same Postgres, private Supabase Storage for report files
- **Booking bot:** direct Meta WhatsApp Cloud API (PyWa), Sarvam speech (Groq Whisper
  fallback), Groq for free-text understanding; built to run at ₹0 (see
  [WhatsApp booking bot](#whatsapp-booking-bot))

## What each role can do

| Role | Screens |
|---|---|
| Receptionist | **Today**: summary cards, live appointment table with one-click next step (check in → start → complete) and lab test counts per patient ("2 tests pending" / "Results ready", never values), no-show / cancel / reschedule, *Upload report*, bot bookings to approve (approving or rejecting messages the patient on WhatsApp, or says "Window closed: call the patient"), *View chat* on WhatsApp / voice bookings, bot requests to handle. **Bot inbox**: patients who asked for reception, chats the bot couldn't follow and emergencies (red, first); reply from MediFlow while WhatsApp's 24-hour window is open, *Resume bot*. A red banner on every reception screen shows emergencies reported to the bot until handled. **New appointment** (key `N`): find or add the patient (duplicate warning), pick a doctor and a free slot or squeeze in, confirm. **Appointments** (any date range, filters), **Patients** (typo-tolerant search, history, edit, lab orders with test statuses, upload reports and see their status, never their contents, result values or any clinical notes), **Doctors** (hours and leave). |
| Doctor | Today's own queue: who is with them, who is waiting (token order, *Call next*), later today, finished. Arrivals appear instantly. **Patient chart** (from the queue): demographics, red allergy badges, chronic conditions; **Current visit** (notes, vitals, prescription builder with *Repeat last*, **Lab tests** to order with priority and a note for the lab, attach report, autosave, *Complete*); **Visit history** across all doctors with addenda and the lab results of each visit; **Lab results** (flagged values, amendments, PDF); **Lab trends** (a parameter over time with its reference band); **Medications** (current ones highlighted); **Reports** (upload, inline viewer, indexing status, Retry); **Vitals trend**; and **Ask about this patient**, a chat that answers only from the patient's records with clickable citations. Today shows lab badges per patient and a **Lab results** inbox (*Mark reviewed*); a red banner on every doctor screen shows critical values until acknowledged. Doctors never see phone numbers. |
| Lab technician / supervisor | **Lab worklist** (to collect, in progress, awaiting verification, released today, rejected; STAT and urgent on top; live). **Order**: identity check, sample collection into tubes, printable barcode labels, sample rejection and recollection, result entry with the patient's reference ranges, live flags, critical confirmation and a delta check against the previous value, attach the lab machine's PDF. Technicians submit; supervisors verify and release, send back, or amend released results. Lab staff see only what testing needs. |
| Admin | **Staff** accounts (create with generated password, link a doctor login, deactivate). **Doctors**: profile, active flag, weekly multi-shift hours, leave days. **Lab tests**: the test catalog (parameters, units, reference ranges by sex and age, critical limits, activate) and the *Require verification before release* setting. Staff roles include the two lab roles. **WhatsApp bot**: connection and webhook status, the free-message meter (warning at 80 %), emergency / STOP / START word lists per language. **Voice simulator**: hold-to-talk test calls that make real bookings. |
| Patients (WhatsApp) | Book (who it's for, doctor, day, time, reason, confirm), see upcoming appointments, cancel or reschedule them, talk to reception. Menus, typed text or voice notes; Telugu, Hindi or English. |
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
 Meta        ── signed webhook ─────▶    /whatsapp/webhook → store → bot worker → engine
             ◀── replies (outbox) ───    → inbound/booking service; Sarvam STT, Groq
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
                           whatsapp (webhook), bot (inbox), bot_admin, voice_sim,
                           records, reports, chat
  app/services/booking/    channel-agnostic booking service (slots, create, status, patients)
  app/services/records/    chart access, consultations, prescriptions, addenda, medical
                           profile, reports + storage, access log
  app/services/ingestion/  job queue, worker, rendering, PDF extraction, chunking, indexer
  app/services/rag/        providers, patient retriever, summary, prompt, citations, chat
  app/services/conversation/ booking bot engine: states, i18n (te/hi/en), dates, keywords,
                           intents, option matching, turn persistence, voice rendering
  app/services/whatsapp/   webhook parsing, PyWa sender, voice-note transcription
  app/services/messaging/  outbox dispatch (opt-out, consent, 24 h window, free-tier meter),
                           approval / rejection messages
  app/services/bot_jobs/   bot job queue and worker; services/speech/: STT and TTS providers
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
4. Add the lab: test catalog, structured results matching the seed lab PDFs, a few open orders
   for the lab worklist and one unacknowledged critical value, then index the results:
   `uv run python -m scripts.seed_lab && uv run python -m scripts.reindex --all`. Idempotent.
5. In the dashboard: **Authentication → Sign In / Providers → turn off "Allow new users to
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
| `EMBEDDING_REQUESTS_PER_MINUTE` | Client-side pacing of embedding calls per process, default `3` (Voyage without a payment method: 3 requests and 10K tokens per minute). `0` = no pacing. |
| `RAG_TOP_K`, `RAG_CHUNK_SIZE`, `RAG_CHUNK_OVERLAP`, `RAG_MAX_HISTORY_TURNS` | Retrieval and chunking: `6`, `1000`, `150` characters, `4` turns. |
| `RAG_FAKE_LLM` | `true` = deterministic fake chat model + fake embeddings (tests, E2E, demos without keys). |
| `CHAT_RATE_LIMIT` | Questions per signed-in user, default `6/minute`. |
| `REPORT_MAX_MB` | Upload limit, default `10` (must match the `patient-reports` bucket limit). |
| `MIN_TEXT_CHARS_PER_PAGE` | PDFs with less extracted text per page are treated as scans (stored, not searchable). |
| `SIGNED_URL_TTL_SECONDS` | Lifetime of report view links, default `60`. |
| `INGESTION_WORKER_ENABLED`, `INGESTION_MAX_ATTEMPTS` | Background indexing in the API process (`true`), retries (`5`). |
| `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_WABA_ID` | From Meta's *WhatsApp → API Setup* page. |
| `WHATSAPP_ACCESS_TOKEN` | **Permanent** System User token (not the 24-hour test token). Server-only. |
| `WHATSAPP_APP_SECRET` | App secret; every webhook's `X-Hub-Signature-256` is checked with it. |
| `WHATSAPP_VERIFY_TOKEN` | Any random string; type the same one in Meta's webhook form. |
| `WHATSAPP_API_VERSION` | Empty = PyWa's default Graph API version. |
| `WHATSAPP_ALLOW_PAID_TEMPLATES` | Keep `false`: nothing is sent outside the free 24-hour window (no template path is built). |
| `WHATSAPP_FAKE` | `true` = record outbound messages instead of calling Meta (demos without WhatsApp). |
| `PUBLIC_BASE_URL` | Your tunnel's HTTPS URL (shown on the admin page as the webhook URL). |
| `BOT_WORKER_ENABLED`, `BOT_MAX_ATTEMPTS` | Bot worker in the API process (`true`), retries (`5`). |
| `BOT_FREE_REPLY_LIMIT`, `BOT_ESSENTIAL_RESERVE` | Monthly free WhatsApp messages (`1000`, Meta's free tier) and the part kept for essential messages (`100`). |
| `BOT_LLM_ENABLED` | `true` = understand free text with the Groq LLM (free tier); `false` = free keyword rules. |
| `BOT_NOTICE_VERSION` | Recorded with every consent event; bump it when the privacy notice text changes. |
| `STT_PROVIDER`, `SARVAM_API_KEY` | `sarvam` (Groq Whisper as fallback when `GROQ_API_KEY` is set), `groq` or `fake`. |
| `TTS_PROVIDER` | `browser` (free, default), `sarvam` or `fake`, for the voice simulator. |

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
| Lab technician | `lab1@mediflow.test` |
| Lab supervisor | `labhead@mediflow.test` |

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

- **Backend tests (415)** run against `TEST_DATABASE_URL`. Each test creates its own clinic,
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
  - the lab: every status transition per role with verification on and off, cancellation
    rules, reference range selection by sex and age, flags and critical confirmation,
    snapshots that survive catalog edits, amendments as new versions, atomic release (report
    row, ingestion job and critical alert together), concurrent order numbers, the generated
    PDF, `lab_result` chunks and citations, lab and reception access, lab RLS and Realtime
  - the booking bot (fake Meta, Groq and Sarvam): webhook signatures, duplicate `wamid`s
    processed once, out-of-order messages, statuses that never move backwards; every
    conversation step in Telugu, Hindi and English, family members on one phone, a slot taken
    between listing and confirm, cancel / reschedule, handoff, STOP on every channel,
    emergencies, medical-question refusal; free text and voice notes that suggest but never
    book without Confirm, two failures → reception, audio never stored; approve sends exactly
    one confirmation, nothing to opted-out numbers or outside the 24-hour window, the
    free-message limit and its reserve; the reception inbox, alerts and keyword lists; the
    voice simulator
- **Live evaluation** (`tests/live`, deselected by default): 20 questions (5 about lab results) with expected facts
  over the seeded test patient (each answer must contain the facts and a valid citation)
  and 3 questions the records cannot answer (the answer must say so). Prints a scorecard.
  Paced for the Groq free tier. `tests/live/test_bot_live.py` checks the bot's services:
  the WhatsApp number is reachable, a free-form message reaches `LIVE_WHATSAPP_TO` (a test
  recipient who messaged the number in the last 24 hours), Sarvam speaks and transcribes
  Telugu, Groq Whisper transcribes, and Groq extracts the Telugu booking intent. Each test
  skips without its key.
- **E2E tests** run against the dev servers and the seeded clinic: a booking made by one
  receptionist appears live on another's screen, each role stays on its own screens, and a
  doctor opens a checked-in patient, sees the history and gets a cited answer, and the lab
  flow end to end (order → collect → enter with one high value → verify → results inbox,
  flagged value, PDF and a cited answer). The lab test uses its own patient,
  "E2E Lab Patient", and books from tomorrow on. The voice simulator test books by voice/text as
  "Voice Simulator Patient" (+919999000222) for a day from tomorrow on, reception approves it
  with *View chat* open, and the caller receives the confirmation with its token; it cancels
  what it booked.
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

## WhatsApp booking bot

Patients message the clinic's WhatsApp number and book with buttons and lists, typed text or
voice notes, in Telugu, Hindi or English. Requests land on reception's Today screen as
*pending confirmation*; approving or rejecting sends the patient a WhatsApp message.

**How a message flows**

1. Meta calls `POST /api/whatsapp/webhook`. The signature (`X-Hub-Signature-256`, HMAC-SHA256
   with the app secret) is checked, each message is stored once in `channel_messages` (unique
   `wamid`, so redelivered webhooks are ignored) with a `bot_jobs` row, and Meta gets `200`
   at once.
2. The **bot worker** (in the API process, `FOR UPDATE SKIP LOCKED`, retries with backoff)
   turns the message into the engine's format. Voice notes are downloaded, transcribed
   (Sarvam, Groq Whisper as fallback) and only the transcript is kept.
3. The **conversation engine** (`app/services/conversation/`, no FastAPI imports) is a
   deterministic state machine: notice and language → menu → who is it for (first names of the
   patients on that phone, or someone new) → doctor → day (next 7 days with free slots) →
   time (≤10 free slots) → reason (a short category) → **Confirm**. Bookings go through the
   existing inbound/booking service as `SystemActor(whatsapp)`, with
   `external_ref = <conversation id>:<attempt>`, so a retried turn never books twice. If the
   slot was taken meanwhile, the next free times are offered.
4. Replies are queued in `message_outbox` (idempotency key per inbound message) and sent by
   `app/services/messaging/` after four checks: not opted out, consent recorded, the 24-hour
   window open, and the free-message allowance.

**Understanding free text and voice notes.** Typed answers and transcripts are matched
against the options on screen ("2", "two", "రెండు", "Dr Sharma", "tomorrow", "10:30", "yes").
Anything else goes to a closed intent schema (book / cancel / reschedule / my appointments /
reception / unknown, plus doctor, day, time, name): keyword rules with doctor names matched
across scripts (శర్మ = Sharma), or the Groq LLM when `BOT_LLM_ENABLED=true` (rules are its
fallback). Parsed values only skip ahead in the menus (e.g. straight to tomorrow's slots for
Dr. Sharma); **nothing is booked until the patient presses Confirm**. Today's IST date is in
the prompt, but relative dates ("next Tuesday", "రేపు", "कल") are resolved in code. Two
messages in a row that can't be understood hand the chat to reception.

**Safety**

- The bot never gives medical advice: questions about medicines, doses, diagnosis or
  seriousness get a polite refusal in the chosen language (and the menu).
- **Emergency words** (Telugu, Hindi, English; editable on the admin page) get an immediate
  "call 108 / 112" reply, a red alert on every reception screen, and a handoff.
- **STOP** (and ఆపండి, बंद करो, …) opts the phone out on every channel; START opts it back in.
- *Talk to reception* pauses the bot for that chat until reception presses *Resume bot*.
- Every consent step (notice shown, consented, opted out / in) is logged with its version.

**Cost: ₹0 by design**

- Direct Meta Cloud API, no BSP. Since 1 October 2026 Meta gives each business number
  **1,000 free service messages a month** (each delivered button / list / text counts) and
  stops delivering after that unless a payment method is added. The bot counts every message
  it sends: menus stop at `BOT_FREE_REPLY_LIMIT − BOT_ESSENTIAL_RESERVE` (900), the last 100
  are kept for confirmations, emergencies, opt-out and handoff messages, and nothing is sent
  at 1,000. The admin page shows the meter (warning at 80 %). One booking takes about 8–10
  messages, so the free tier covers roughly 100 bookings a month.
- Only free-form replies inside the 24-hour customer-service window are ever sent. Template
  messages (needed outside the window, and charged) are not built;
  `WHATSAPP_ALLOW_PAID_TEMPLATES` stays `false`. When the window is closed, reception sees
  "Window closed: call the patient".
- Groq (LLM and Whisper) is on its free tier. Sarvam gives signup credits (speech-to-text
  ₹30/hour, text-to-speech from ₹15 per 10,000 characters), so it is free until they run out;
  Groq Whisper and the browser's own voice are the free fallbacks.

**What reception and admin see.** Today: bot bookings with *View chat*, approve / reject (with
the message result). **Bot inbox** (`/reception/inbox`): handed-off chats (emergencies
first), transcripts, replies while the window is open, *Resume bot*. Admin **WhatsApp bot**
page: connection, webhook last seen, usage meter, keyword lists.

## WhatsApp setup (step by step)

You need: a Facebook account, the WhatsApp app on your phone, and about 30 minutes. Everything
below is free. Meta renames menu items now and then; if a name differs, look for the closest
match.

**A. Make the backend reachable from the internet (ngrok)**

Meta can only call a public HTTPS address, so a free ngrok tunnel forwards one to your laptop.

1. ngrok is installed through winget (`Ngrok.Ngrok`). If `ngrok` is not found in a new
   terminal, use the full path
   `%LOCALAPPDATA%\Microsoft\WinGet\Packages\Ngrok.Ngrok_Microsoft.Winget.Source_8wekyb3d8bbwe\ngrok.exe`.
2. Sign up at <https://dashboard.ngrok.com/signup> (free). Copy your **authtoken** from
   *Getting Started → Your Authtoken* and run: `ngrok config add-authtoken <token>`.
3. In the ngrok dashboard open *Domains* and claim your **free static domain** (something like
   `calm-otter-123.ngrok-free.app`). A static domain means you only enter the webhook URL in
   Meta once.
4. Start the tunnel to the API: `ngrok http --url=<your-domain> 8000`. Keep this window open.

**B. Create the Meta app and get a test number**

1. Go to <https://developers.facebook.com>, log in, and open *My Apps → Create App*. Choose the
   use case **Connect with customers through WhatsApp** (or app type **Business**), give it a
   name, and create it. Meta also creates a *business portfolio* if you don't have one.
2. In the app, open **WhatsApp → API Setup**. Meta gives you a free **test phone number**.
   Copy the **Phone number ID** and the **WhatsApp Business Account ID**.
3. Under *To*, choose **Manage phone number list** and add your own WhatsApp number (up to 5
   numbers). Enter the code WhatsApp sends you. The test number can only talk to numbers on
   this list.

**C. Create a permanent access token** (the token on the API Setup page expires in 24 hours)

1. Open <https://business.facebook.com/settings> → **Users → System users → Add**. Name it
   (e.g. `mediflow-bot`), role **Admin**.
2. Select the new system user → **Assign assets**: under *Apps* pick your app (full control),
   under *WhatsApp accounts* pick your WhatsApp account (full control). Save.
3. Click **Generate new token**: choose your app, expiry **Never**, and tick the permissions
   `whatsapp_business_messaging` and `whatsapp_business_management`. Copy the token now (it is
   shown once).

**D. Find the app secret**

In the app dashboard: **App settings → Basic → App secret → Show**. Copy it.

**E. Fill in `backend/.env`**

```env
WHATSAPP_PHONE_NUMBER_ID=<Phone number ID from B2>
WHATSAPP_WABA_ID=<WhatsApp Business Account ID from B2>
WHATSAPP_ACCESS_TOKEN=<permanent token from C3>
WHATSAPP_APP_SECRET=<app secret from D>
WHATSAPP_VERIFY_TOKEN=<any long random text you make up>
PUBLIC_BASE_URL=https://<your-ngrok-domain>
INBOUND_CLINIC_ID=<the clinic the bot books into; seed clinic: 11111111-1111-4111-8111-111111111111>
WHATSAPP_ALLOW_PAID_TEMPLATES=false
# optional: voice notes in Telugu/Hindi (Sarvam signup credits) and the free LLM
SARVAM_API_KEY=<from https://dashboard.sarvam.ai>
BOT_LLM_ENABLED=true
```

Start (or restart) the API **without** `--reload`:
`uv run python -m uvicorn app.main:app --port 8000`.

**F. Connect the webhook**

1. In the app dashboard open **WhatsApp → Configuration**. Under *Webhook* click **Edit**.
2. *Callback URL*: `https://<your-ngrok-domain>/api/whatsapp/webhook`.
   *Verify token*: the same text as `WHATSAPP_VERIFY_TOKEN`. Click **Verify and save**. (If it
   fails, check that ngrok and the API are both running.)
3. Under *Webhook fields* click **Manage** and **Subscribe** to `messages`.

**G. Try it**

1. From your phone, send "hi" to the test number. You should get the privacy notice with
   three language buttons within a few seconds.
2. Book with the buttons. The request appears on reception's Today screen under *Waiting for
   confirmation*. Approve it and your phone receives the confirmation with the token number.
3. In MediFlow, log in as admin → **WhatsApp bot**: *Connected*, *Webhook last seen* and the
   message meter should all update.

**Troubleshooting**

| Symptom | Likely cause |
|---|---|
| Webhook verification fails | ngrok or the API is not running, or the verify token differs. |
| Nothing arrives after "hi" | `messages` field not subscribed; your number is not on the recipient list; ngrok window closed. |
| API log shows `401 INVALID_SIGNATURE` | `WHATSAPP_APP_SECRET` is wrong. |
| Bot doesn't reply | The phone opted out (send START); the monthly allowance is used up (admin page); token missing or expired (admin page shows *Not reachable*). |
| Voice notes get "couldn't understand" | No `SARVAM_API_KEY` / `GROQ_API_KEY`, or the note is longer than 30 seconds. |

Going live with a real number later means verifying the business with Meta and adding a phone
number you own; nothing in the code changes.

## Voice booking simulator

Admin → **Voice simulator** (`/admin/voice-simulator`) is a free demo of a future phone
booking line. Enter a test phone number, pick a language, and hold the microphone button
while speaking (or type, or tap an option). Each turn: the browser records audio (opus /
webm) → `POST /api/admin/voice-sim/turn` → speech-to-text → the same conversation engine as
WhatsApp on the `web_voice` channel → text-to-speech → the browser plays the reply.

- Spoken prompts are short: at most three options at a time ("say 2 for …", with *more*),
  and confirmations read back doctor, day and time.
- Speech: Sarvam (speech-to-text, and Bulbul voices when `TTS_PROVIDER=sarvam`) or free
  fallbacks: Groq Whisper and the browser's `speechSynthesis` (the default voice).
- Bookings are real `pending_confirmation` requests with source **voice**. Reception approves
  them as usual; the confirmation appears in the simulator's *Messages to this caller*.
- A telephony adapter (e.g. Pipecat + Plivo) can reuse it: `app/services/voice_sim.py` shows
  the per-utterance loop (transcribe → `run_turn` → deliver → `speakable` → synthesize).
  Telephony is not built.

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

## In-house lab

**Workflow.** A doctor orders tests during their own consultation (patient checked in or in
consultation). The order appears on the lab worklist instantly. The lab collects samples:
tests sharing a sample type and container go into one tube with a printed code
(`S-261002-0042`). Results are entered per parameter. The server picks the reference range
for the patient's sex and age at collection (an age band beats an adult range; a sex-specific
range beats an "any" range), copies it onto the result (so catalog edits never change old
results) and flags the value (low, high, critical low/high, abnormal for text). Critical
values need an explicit confirmation.

```
 ordered ─▶ sample_collected ─▶ result_entered ─▶ verified ─▶ released
    │            │    ▲              │   (supervisor)          ▲
    ▼            ▼    │ recollect    └─ verification off ──────┘
 cancelled   sample_rejected         └─ sent back ─▶ sample_collected
```

**Release** (one transaction): item statuses and timestamps, a critical alert per critical
value for the ordering doctor, the order's generated report row, the ingestion job and a
`lab_report_released` event (the hook for notifying patients later). The order status is
derived from its items, so tests are released one by one as they're ready.

**After release** the ingestion worker indexes one `lab_result` chunk per test (date, order,
values, ranges and flags), renders the clinic's PDF report (fpdf2) into the private bucket
and marks the order's reports indexed. The PDF is for viewing; its text is not embedded,
since the structured results already are. Amendments create a new result version with a
reason; the old one stays in history; the PDF is regenerated as "Amended" and re-indexed.

**Realtime:** only `lab_orders` (doctors and lab staff) and `lab_critical_alerts` (the doctor
they belong to) are published. Result values never go through Realtime; screens refetch them
from the API. Reception gets status counts from the API (polled), because the order row
carries the doctor's note for the lab.

**Reference ranges in the starter catalog are common adult intervals** (plus paediatric CBC
bands for ages 1 to 12). Labs differ by method and analyser: the clinic must review every
range and critical limit under **Admin → Lab tests** before use.

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
  - Bots book as *pending confirmation*. A bot may cancel or reschedule only upcoming
    (pending or scheduled) appointments of patients registered with the sender's own phone;
    a bot reschedule goes back to *pending confirmation* for reception to approve again.
    Bots never approve, check in or squeeze in.
- **Patients:**
  - Phones are stored in E.164, and 10-digit numbers default to +91.
  - The same patient means the same phone and a name similarity above 0.6.
  - Search uses `word_similarity` ≥ 0.3, so "laxmi" finds "Lakshmi Narayanan".
- **Bot bookings** go to a single clinic (`INBOUND_CLINIC_ID`); the voice simulator books into
  the signed-in admin's clinic.
- **WhatsApp bot:**
  - A pending bot booking holds its slot (the overlap constraint and slot listing treat only
    cancelled / no-show as free) until reception approves or rejects it; it never expires.
  - A rejection offers up to three other times and the chat continues from there.
  - Family members sharing one phone are told apart by first name; a new name goes through
    the usual duplicate check (same phone and a similar name = the same patient).
  - The reason for the visit is a short category, never free-text symptoms.
  - Bot tables (conversations, messages, outbox, consent, jobs, usage, alerts, keywords) are
    backend-only (RLS on, no client grants, not in Realtime); the inbox and alerts poll every
    10 seconds.
  - Out-of-order webhooks: a message older than the last one handled is recorded but not
    acted on (STOP and emergencies always are). Delivery statuses only move forward
    (sent → delivered → read, or failed).
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
- **Lab roles:** a technician enters and submits results; a supervisor verifies and releases
  them (and can do every lab step). With *Require verification before release* turned off,
  whoever enters results can release them.
- **Lab access:** lab staff see what testing needs: name, age, sex and phone, the order and
  the doctor's note for the lab, and the patient's earlier results of the same parameters
  (for delta checks). Notes, prescriptions, other reports and the assistant are 403.
  Reception and admin see order numbers, test names and statuses, never values.
- **Ordering** is only possible during the doctor's own consultation. A test can be cancelled
  until its sample is collected (by the ordering doctor, or by the lab with a reason).
- **Lab values** are stored at each parameter's reporting precision (e.g. HbA1c to 0.1).
  Released results are never overwritten; a database trigger enforces it.
- **Lab seed data:** the seed lab PDFs were backfilled as structured results on the same
  dates; each PDF is linked to its order as the lab machine's PDF and is no longer indexed on
  its own, so the assistant sees every value once.
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
- Voyage without a payment method allows 3 requests per minute: indexing runs at one record
  every 20 seconds, and each chat question needs one embedding. If the embedding call is
  rate-limited, the question is answered from full-text search alone. Adding a payment method
  in the Voyage dashboard (the free token allowance still applies) lifts the limit; then set
  `EMBEDDING_REQUESTS_PER_MINUTE=0` or a higher value.
- Lab: no billing, no external reference labs, no analyser (LIS/HL7/ASTM) interface, no
  walk-in tests without a doctor's order, and no sending of reports to patients yet (the
  `lab_report_released` event is the hook). Tube labels print through the browser.
- Printing, e-prescriptions, ABDM/ABHA, drug interaction checks and a patient-facing
  assistant are out of scope.
- "Bot requests to handle" polls every 30 seconds (those rows are not in the Realtime
  publication). Appointments themselves are live.
- WhatsApp bot:
  - The Telugu and Hindi texts were written for this MVP and should be reviewed by a native
    speaker (`app/services/conversation/i18n.py`).
  - The usage meter counts messages *sent*; Meta bills *delivered* ones, so the meter errs on
    the safe side.
  - No reminder or other template messages (they cost money), no WhatsApp Flows, no payments,
    and no clinical content (lab reports, prescriptions) over WhatsApp.
  - The keyword rules understand common phrasings; unusual sentences need `BOT_LLM_ENABLED`.
  - Real phone calls (telephony), missed-call booking and BSPs are not built.
  - The Meta test number can only message the (up to 5) numbers on its recipient list.
- Leaked-password protection is off. The Supabase advisor reports it until it's enabled in
  the dashboard.
- The UI assumes the clinic is in IST for display. The backend already supports a per-clinic
  time zone (`clinics.timezone`).
