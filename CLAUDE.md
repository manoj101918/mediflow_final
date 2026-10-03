# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

MediFlow: clinic system (reception, doctor chart with clinical records, a patient-record
chatbot, and the clinic's in-house lab). FastAPI backend (`backend/`) on Supabase Postgres + pgvector, React + TypeScript
frontend (`frontend/`), SQL migrations in `supabase/`. `README.md` has full setup, env vars,
the bot API contract, how the RAG pipeline works and the list of product decisions; read it
for product behaviour questions.

## Commands

Backend (run from `backend/`). This machine has Windows Smart App Control: use the system
Python 3.12 via uv, always `python -m …` (the `.exe` shims are blocked), and clear a stray
Anaconda env first.

```bash
unset VIRTUAL_ENV; export PATH="$HOME/.local/bin:$PATH"   # uv lives in ~/.local/bin
uv run ruff check . && uv run ruff format --check . && uv run mypy app scripts tests
uv run python -m pytest -q -p no:logging                      # full suite, ~10 min (remote DB)
uv run python -m pytest tests/test_booking_create.py -q       # one file
uv run python -m pytest "tests/test_inbound.py::test_rate_limit" -q
uv run python -m pytest -m live -s tests/live                 # live RAG eval (real API keys)
uv run python -m uvicorn app.main:app --port 8000             # do NOT use --reload (see Gotchas)
RAG_FAKE_LLM=true uv run python -m uvicorn app.main:app --port 8000   # no API keys (E2E)
uv run python -m scripts.seed_users                           # after supabase/seed.sql
uv run python -m scripts.seed_clinical                        # synthetic clinical history + PDFs
uv run python -m scripts.seed_lab                             # lab catalog, backfilled results, open orders
uv run python -m scripts.reindex --patient <id> | --all       # rebuild chatbot chunks
```

Never run `python -` (or anything reading stdin) in the Bash tool here: it hangs.

Frontend (run from `frontend/`):

```bash
npm run dev          # http://localhost:5173
npm run lint         # oxlint; the 3 warnings in src/components/ui/* are shadcn-generated, ignore
npm run typecheck
npm run build
npm run e2e          # Playwright; uses installed Chrome (channel "chrome"); reuses running servers
npx playwright test e2e/reception.spec.ts -g "own dashboard"
```

Pinned on purpose (newer native builds are blocked by Smart App Control): `ruff==0.15.0`,
`mypy<2`, system Python (`python-preference = "only-system"`). `tzdata` is a dependency
because Windows has no zoneinfo database.

## Architecture

### One booking service for every channel
`backend/app/services/booking/` holds all booking rules and imports nothing from FastAPI.
Dashboard routers and the bot endpoint (`app/api/inbound.py` → `app/services/inbound.py`) call
the same functions with an **actor**: `StaffActor` (user, role, clinic, doctor_id) or
`SystemActor` (whatsapp/voice). Permissions are decided from the actor inside the service.
For example, bots create `pending_confirmation` and staff create `scheduled`; doctors may only
do `checked_in→in_consultation→completed` on their own appointments, and get `NOT_FOUND`
for anyone else's.

- **Results are values.** Services return `BookingResult[T]` with a `BookingErrorCode`.
  Routers convert it with `app/api/results.py:unwrap()`: SLOT_TAKEN / INVALID_TRANSITION /
  ALREADY_EXISTS → 409; DOCTOR_ON_LEAVE / OUTSIDE_SCHEDULE / IN_PAST / VALIDATION → 422;
  NOT_FOUND → 404; FORBIDDEN → 403. Every error response is
  `{"error": {"code", "message", "details?"}}` (`app/core/errors.py`).
- **Write services own their transaction.** They commit on success and roll back on failure,
  including anything the caller left pending in the session. After a rollback, loaded ORM
  objects are expired, and touching them under async raises `MissingGreenlet`. Capture plain
  values (ids, names) before calling a write service whose failure you handle, as
  `services/inbound.py` does.
- **The database is the authority on conflicts.** The exclusion constraint
  `appointments_no_overlap` (live statuses only) prevents double booking. `dberrors.py` maps
  SQLSTATE 23P01 → SLOT_TAKEN and named unique constraints → codes. There is deliberately no
  pre-check.
- **Tokens:** per doctor per clinic-local day, `max+1` under
  `pg_advisory_xact_lock(hashtextextended('booking:<doctor>:<date>'))`
  (`booking/tokens.py`). They're never reused.
- **Shared rules:** slot listing, booking and rescheduling all use `booking/rules.py`
  (schedule windows → slot grid, leave days, `INACTIVE_STATUSES`, 5-minute past grace).
- **Patients:** phones are normalised to E.164 (+91 default). The same patient means the same
  phone and pg_trgm `similarity > 0.6`. Search uses `word_similarity ≥ 0.3`.

### Clinical records (`app/services/records/`)
Same pattern as booking (actor in, `BookingResult` out, no FastAPI imports).
- **Access** (`records/access.py`): any active doctor whose login is linked to a doctor reads
  any patient's full chart in their clinic (all doctors' visits, prescriptions, reports).
  Reception/admin get `FORBIDDEN` for all clinical content (notes, prescriptions, profile,
  report files/text, chat) but may upload reports and list report metadata. Another clinic's
  patient is `NOT_FOUND`.
- **Writing a visit**: only the appointment's own doctor, only while `checked_in` /
  `in_consultation`; other doctors get `NOT_FOUND`. `PUT /appointments/{id}/consultation`
  upserts the draft (only sent fields change; `items` replaces the prescription).
- **Completing** (`consultations.complete_visit`) moves the appointment to completed (reusing
  `booking.status.transition_in_session`), finalizes the draft and enqueues indexing in ONE
  transaction. The generic status endpoint uses it for `completed` too.
- **Finalized is read-only**: service returns `RECORD_LOCKED` (409); DB triggers raise SQLSTATE
  `MF001` as a backstop (`dberrors.py` maps it). Corrections are addenda.
- **Medical profile** is a separate table (`patient_medical_profiles`), not columns on
  `patients`, because reception reads `patients`.
- **Reports**: type sniffed from magic bytes, size from `REPORT_MAX_MB`; stored in the private
  bucket `patient-reports` at `{clinic}/{patient}/{report}.{ext}` via the service role
  (`records/storage.py`, `ReportStorage` protocol); doctors get 60 s signed URLs.
- **Access log**: chart opens, report views/uploads and chat questions go to
  `patient_record_access_log` (ids only, never question text).
- New error codes: `RECORD_LOCKED` 409, `FILE_TOO_LARGE` 413, `UNSUPPORTED_FILE_TYPE` 415.

### Ingestion (`app/services/ingestion/`)
- Every record change enqueues an `ingestion_jobs` row in the same transaction (`jobs.enqueue`;
  a partial unique index collapses duplicate pending jobs).
- `IngestionWorker` (asyncio task, started once in the FastAPI lifespan) claims jobs with
  `FOR UPDATE SKIP LOCKED`, retries with exponential backoff up to `INGESTION_MAX_ATTEMPTS`,
  reclaims jobs stuck in `processing` > 10 min, and pauses (jobs stay queued) while the
  embedding key is missing. It skips clinics named `pytest-clinic-%` (see Gotchas).
- `render.py` turns a finalized visit (with prescription and addenda) or the profile into one
  readable text; reports are extracted per page with pypdf (`extract.py`) and split with
  `RecursiveCharacterTextSplitter`, each chunk prefixed with title/type/date/page.
  Images and scanned PDFs end as `no_text` (no OCR); unreadable PDFs as `failed` (Retry).
- `indexer.py` hashes chunks: unchanged sources are skipped, only new hashes are embedded,
  and a source's chunks are replaced in one transaction.

### Patient chatbot (`app/services/rag/`)
- `providers.py` is the only place models are built: Groq chat (`langchain-groq`, gpt-oss
  reasoning hidden via `include_reasoning=False`) and Voyage embeddings; `RAG_FAKE_LLM=true`
  gives `DeterministicFakeEmbedding` + `FakeRecordsChatModel` (cites a real source).
  Routers get them through the `rag_providers` dependency (tests override it).
- `PatientRecordRetriever` (LangChain `BaseRetriever`, async only) is bound to one
  (clinic, patient, embedding model); every SQL statement filters on all three. Exact
  cosine search over the patient's rows + OR-ed full-text, merged by RRF.
- `chat.py`: `prepare_turn` (access, rate limit is in the router, session ownership,
  retrieval, prompt, saves the question) runs before streaming so failures are normal HTTP
  errors; `stream_turn` yields `token`… then `citations` + `done`, or `error`, and saves the
  answer with tokens/latency in its own session (`SessionFactory` dependency).
- Source [1] is always the SQL patient summary (`snapshot.py`). `prompt.SYSTEM_PROMPT` is a
  constant; record text is escaped inside `<patient_records>` (prompt-injection defence).
- vectors are bound as text (`vector_literal`) and cast in SQL; there is no numpy/pgvector
  Python dependency and vectors are never loaded into Python.

### In-house lab (`app/services/labs/`)
Same pattern (actor in, `BookingResult` out, no FastAPI imports); router `app/api/labs.py`,
admin catalog in `app/api/admin.py`.
- **Roles:** `lab_technician`, `lab_supervisor` (`LabUser` guard, `StaffActor.is_lab`). The
  per-clinic `clinics.lab_requires_verification` (default true) decides whether release needs
  a supervisor. `transitions.py` is the pure table: allowed moves per action
  (`allowed_sources`) and per role (`role_allowed`), and `derive_order_status`.
- **Access:** doctors (`clinician_check`) read any clinic patient's results and order only on
  their own `checked_in`/`in_consultation` appointment (others: NOT_FOUND). Lab staff get
  identifiers + order + note + same-parameter history (`read.lab_order_detail`); every
  records/chat service already rejects non-doctors. Reception/admin: counts and statuses only
  (`status_summary`, `patient_order_statuses`), never values.
- **Writes** (`workflow.py`, `orders.py`, `alerts.py`) lock the order row first, then the item
  (`common.lock_item`), record `lab_order_events` (ids/statuses only), re-derive the order
  status and touch `lab_orders.updated_at` (the Realtime ping) via `refresh_order`.
- **Results:** `ranges.select_range` (age band > sex-specific > any, narrowest band) at the
  collection date; `snapshot_result` copies name/unit/range/flag onto the row; values are
  quantized to the parameter's `decimals` (`parse_value`). Critical values need
  `confirm_critical`. Amendments insert version n+1 and retire the old row; the DB trigger
  `prevent_released_result_edit` (MF001 → RECORD_LOCKED) blocks any other change to a released
  result.
- **Release** (`release_in_session`, one transaction): statuses/timestamps, critical alerts
  for the ordering doctor, the generated `patient_reports` row (`is_generated`, size 0 until
  rendered), `enqueue(LAB_RESULT, order_id)`, the `lab_report_released` event, and clears
  `reviewed_at` so the order is back in the doctor's inbox.
- **Ingestion:** the worker's `LAB_RESULT` handler (source_id = order id) indexes one chunk
  per released test (`labs/render.py`, metadata `order_item_id`), renders the PDF
  (`labs/pdf.py`, fpdf2 core fonts → Latin-1 only, `_latin1`) and uploads it with
  `upsert=True`, then marks all the order's reports indexed. Lab-linked reports (generated or
  machine PDFs, `patient_reports.lab_order_id`) never get a `report` job.
- **Chatbot:** `lab_result` citations carry `item_id` (schemas/chat.py); trend questions also
  pull recent lab chunks; `snapshot.py` adds abnormal values (12 months) and open critical
  alerts via `labs.render.lab_summary_lines`.
- **Numbers:** `numbers.py`: `LAB-YYYYMMDD-NNNN` and `S-YYMMDD-NNNN` per clinic-local day under
  advisory locks (ordered by length then value).

### Time
Timestamps are timestamptz and API responses are always UTC (`UtcDateTime` in
`schemas/common.py`). Days, slots and tokens are clinic-local. A DB trigger sets
`appointments.appointment_date` (IST date of `starts_at`). Weekday 0 = Monday everywhere.
The frontend formats everything in Asia/Kolkata (`src/lib/format.ts`) and builds wall-clock
timestamps with a fixed `+05:30`.

### Auth and data access
- **Login flow:** the browser signs in with supabase-js. Every API call sends the Supabase
  JWT (`frontend/src/lib/api.ts`). `app/core/security.py` verifies it against the project
  JWKS (ES256), with 30 s leeway because Supabase's clock is slightly ahead.
  `deps.get_current_user` loads the active profile, clinic and linked doctor.
- **Role guards:** `FrontDeskUser` (receptionist + admin), `AdminUser`, `LabUser`
  (technician + supervisor), `AuthUser`.
- **Two access paths to the data:**
  - FastAPI connects as the DB owner, bypasses RLS, and scopes by clinic and doctor in code.
  - **RLS** (`supabase/migrations/*_rls.sql`, helpers in the `private` schema) governs
    Realtime and any direct Supabase access. Only `appointments` is in the realtime
    publication.
- **Bot endpoint** `POST /api/bookings/inbound`:
  - checks `X-API-Key` and a slowapi limit (`core/rate_limit.py`, in-memory, keyed by IP,
    limit read from settings per request)
  - stores the raw request first, then deduplicates on (clinic, channel, external_ref)
  - responds 201 / 200 duplicate / 202 needs_review (+ suggested slots) / 422 rejected

### Frontend data flow
- **All data goes through FastAPI** (`lib/api.ts`). supabase-js is only for auth and
  Realtime. A 401 signs out and redirects to `/login?expired=1`.
- **API types** are hand-written in `src/types/api.ts` and mirror `backend/app/schemas/*`.
  Update both together. `src/types/database.ts` is generated (MCP
  `generate_typescript_types`) and is used only for enums and realtime rows.
- **Query keys:** everything appointment-related starts with `'appointments'` (see
  `lib/appointments.ts`; slots and inbound lists live under it too), patients with
  `'patients'`, clinical data and reports with `'patient-records'` (`lib/records.ts`,
  `lib/reports.ts`), chat with `'patient-chat'` (`lib/chat.ts`). Lab (`lib/labs.ts`, `labKeys`):
  lab screens, inbox and alerts under `'labs'`; chart lab data under `'patient-records'`;
  Today counts under `['appointments', 'lab-summary', day]`; reception lists under `'patients'`.
- **Doctor chart:** `/doctor/patients/:patientId?appointment=` (`pages/doctor/PatientChart.tsx`,
  `components/chart/*`, `components/chat/*`). The current-visit form autosaves through
  `hooks/useAutosave.ts` (serialised saves, `flush()` before Complete). Reports poll every 3 s
  while pending/processing (`hooks/useReports.ts`).
- **Chat streaming:** `lib/chat.ts` reads SSE with `fetch` + `ReadableStream` (EventSource
  cannot send the Authorization header). Answers render through `AnswerText` (React elements
  only, no HTML injection).
- **Realtime:** `hooks/useRealtimeAppointments.ts` invalidates both key prefixes on any row
  change, which is how every open screen stays live. Mutations use
  `useAppointmentMutation`, which always refetches afterwards.
- **Lab Realtime:** `hooks/useRealtimeLabs.ts`: `useRealtimeLabOrders` (in `DoctorLayout` and
  `LabLayout`) invalidates every lab query on any `lab_orders` change; `useRealtimeLabAlerts`
  drives `CriticalAlertBanner`. Reception has no lab Realtime (RLS excludes it) and polls.
- **Routing:** `src/router.tsx` builds each role area with `area()` (a list of roles):
  `RequireRole` guard → lazily loaded layout → lazily loaded pages. `/lab` serves both lab
  roles; `/lab/orders/:id/labels` is a bare print page outside the layout. `ReceptionLayout` owns the realtime
  subscription and the booking sheet (`NewAppointmentContext`, hotkey `N`, lazy-loaded).
- **Test hooks:** rows carry `data-appointment-id` / `data-status`; chart elements carry
  `data-consultation-id`, `data-report-id` / `data-report-status`, `data-allergy`; chat uses
  `data-testid="chat-panel"`, `data-chat-role`, `data-chat-message-id`, `data-citation` /
  `data-citation-type`. Lab: `data-lab-order-id`, `data-lab-item-id` / `data-lab-item-status`,
  `data-parameter`, `data-flag`, `data-live-flag`, `data-sample-code`, `data-lab-badge`,
  `data-testid="order-tests" | "lab-inbox" | "critical-alerts" | "lab-patient-name"`.

## Schema changes
The schema is owned by SQL migrations, never by SQLAlchemy.
1. Apply via the Supabase MCP `apply_migration` (project `hccsqofkmqyldkenapqr`).
2. Save the same SQL as `supabase/migrations/<version>_<name>.sql`, where `<version>` is
   what `list_migrations` reports, so the folder and the server match.
3. Mirror the change in `app/db/models.py`.
4. Regenerate `frontend/src/types/database.ts`.
5. Run `get_advisors` (security) afterwards.

Never edit an applied migration. Model notes: `Appointment`, `Patient`, `Consultation`,
`PatientReport` and the chat models use `eager_defaults` so trigger/server columns come back
via RETURNING; sessions use `expire_on_commit=False`. In SQLAlchemy 2.1, type selects as
`Select[A, B]`, not `Select[tuple[A, B]]`.

Phase 2 schema notes:
- `vector` lives in the `extensions` schema; use `extensions.vector(…)` and
  `operator(extensions.<=>)`. `patient_record_chunks.embedding` is `vector(1024)`;
  `EMBEDDING_DIM` must equal `models.EMBEDDING_DIM` (settings validate it). Changing the
  dimension needs a migration; changing `EMBEDDING_MODEL` needs `scripts.reindex --all`
  (chunks are stored per model).
- All clinical, chunk, job, chat and log tables have RLS on with no policies and no grants
  for `anon`/`authenticated` (backend only); none are in the realtime publication. The advisor
  shows them as INFO "RLS enabled, no policy" by design.
- The `patient-reports` bucket (private, 10 MB, pdf/jpeg/png) was created by migration; its
  size limit must match `REPORT_MAX_MB`. No `storage.objects` policies (service role only).

Phase 3 schema notes:
- Enum values were added in their own migration (`phase3_enum_values`); `ADD VALUE` can't be
  used in the transaction that adds it.
- Only `lab_orders` (doctors + lab roles of the clinic) and `lab_critical_alerts` (its doctor)
  have SELECT grants/policies and are in `supabase_realtime`. `lab_results` and the other lab
  tables are backend-only. `lab_orders` carries the doctor's clinical note, which is why
  reception is excluded.
- Catalog/doctor FKs on lab rows are `deferrable initially deferred` so whole-clinic cascades
  (test teardown) work; tests and parameters are deactivated, never deleted.
- `patient_reports.lab_order_id` is `on delete cascade` (lab PDFs belong to their order);
  generated reports may have `size_bytes = 0` until the worker renders them.

## Tests
- Backend tests hit the real database from `TEST_DATABASE_URL`. The `clinic` fixture
  (`tests/conftest.py`) creates a throwaway clinic, auth users and data per test and deletes
  them afterwards. Helpers include `add_doctor`, `add_schedule`, `add_patient`, `add_leave`,
  `staff(role)` and `system(channel)`.
- API tests swap only the JWT verifier: the bearer token is the user id (`auth(user_id)`).
  `auth_admin` fakes the Supabase Admin API.
- Clocks: `tests/booking_utils.py` gives service tests a fixed future clock (pass `now=`).
  `tests/api_utils.py` books *tomorrow* against the real clock.
- RLS tests switch to the `authenticated` / `anon` roles with forged JWT claims inside a
  rolled-back transaction.
- Inbound tests reset the limiter and monkeypatch `get_settings()` (`inbound_clinic_id`,
  `inbound_rate_limit`).
- Phase 2 fixtures: `clinic.add_appointment(doctor, patient, status=…)` (direct SQL, past
  dates OK), `other_clinic`, `report_storage` (in-memory `FakeReportStorage`),
  `spy_embeddings` (deterministic, counts embedded texts, `fail_with`), `ingestion`
  (`await ingestion.run()` processes only this clinic's jobs), `rag` (fake chat model wired
  into the chat endpoint, chat limiter reset), `parse_sse(body)`. `tests/records_utils.Chart`
  builds reception/admin/three doctors/two patients with an in-consultation visit.
- Lab fixtures: `clinic.add_lab_catalog()` (bulk-inserts the starter catalog, returns test ids
  by code), `clinic.set_lab_verification(bool)`. `tests/lab_utils.LabWorld` builds every role
  plus Ravi (male, 56) in consultation and drives the flow through the API (`ordered`,
  `collect`, `save`, `act`, `released(...)`).
- The default suite never calls paid APIs. `tests/live/` is marked `live` (deselected by
  `addopts`); it needs real keys and the clinical seed.

## Gotchas
- `uvicorn --reload` on this machine leaves orphaned `spawn_main` workers holding port 8000
  that keep serving old code. To restart, kill python processes matching
  `uvicorn app.main:app|spawn_main` and start without `--reload`.
- The dev database is the shared seed clinic. Browser or E2E checks must act only on rows
  they created (target by `data-appointment-id`), book for tomorrow, and clean up by
  cancelling through the API. Never delete seed or dev rows via SQL without asking the user.
- pydantic `EmailStr` rejects the reserved `.test` TLD that the staff accounts use. Admin
  emails are validated with a regex instead.
- Work is committed per milestone directly on `main` and pushed to `origin`
  (github.com/manoj101918/mediflow_final). `.env` and `.env.local` are gitignored.
- Tests share the dev database with any running API. The background ingestion worker skips
  clinics named `pytest-clinic-%` so a dev server never steals (or mis-embeds) test jobs; tests
  run their own clinic's jobs with `run_pending(clinic_id=…)`.
- A running API with `RAG_FAKE_LLM=true` indexes with the fake model; chunks are stored per
  embedding model, so after switching to Voyage run `scripts.reindex --all`.
- Lab E2E (`lab.spec.ts`) and the smoke scripts use their own patient "E2E Lab Patient"
  (+919999000111), never the demo patients, and book from tomorrow on (Sundays have no slots).
  Released lab results can't be cancelled; they stay on that test patient.
- A long-running Vite dev server can serve stale Tailwind CSS for newly added files (classes
  like `lg:` or arbitrary values missing). Restart Vite if a new page's layout looks wrong.
- Ruff's formatter rewrites `\u` escapes into literal characters and then RUF001 flags
  ambiguous ones (en dash, curly quote): build such strings with `chr()` / `str.maketrans`.
- E2E (`doctor-chart.spec.ts`) needs the API in `RAG_FAKE_LLM=true` mode and the clinical
  seed. Playwright starts the API that way, but reuses an already running server as is.
- Groq free tier (`openai/gpt-oss-120b`): 8K tokens/min, so the prompt is capped at ~14K chars
  of records; 429s become a friendly `error` event. `asyncpg` needs `timedelta` (not strings)
  for `interval` parameters.
- `gpt-oss` cites as `【n】` / `[n†L3-L5]` despite the prompt; `rag/citations.py` normalises
  markers while streaming (`normalize_markers`) and in the stored answer (`clean_markers`),
  and `AnswerText` accepts the `†` suffix. Answers also contain non-breaking spaces/hyphens.
- Voyage without a payment method: 3 requests/min. `ThrottledEmbeddings`
  (`EMBEDDING_REQUESTS_PER_MINUTE`) paces each process; separate processes (API worker,
  scripts, live eval) do not share the budget, so avoid running them at the same time. The
  retriever falls back to full-text search if the query embedding fails.
