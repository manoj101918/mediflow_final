-- RAG store: record chunks + embeddings (pgvector), ingestion job queue, chat sessions and
-- messages, and the patient-record access log. Backend-only (see phase2_rls_storage).

create type public.record_source_type as enum ('profile', 'consultation', 'report');
create type public.job_status as enum ('pending', 'processing', 'done', 'failed');
create type public.chat_role as enum ('user', 'assistant');
create type public.record_access_action as enum (
  'chart_open', 'chat_question', 'report_view', 'report_upload'
);

-- ---------------------------------------------------------------------------
-- patient_record_chunks: the vector store. Every query filters on (clinic_id, patient_id).
-- The dimension must match EMBEDDING_DIM (the backend checks at startup).
-- ---------------------------------------------------------------------------
create table public.patient_record_chunks (
  id uuid primary key default gen_random_uuid(),
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  patient_id uuid not null references public.patients (id) on delete cascade,
  source_type public.record_source_type not null,
  -- patient id (profile), consultation id or report id
  source_id uuid not null,
  -- Clinic-local date of the visit / report, for ordering and "recent" questions.
  source_date date,
  chunk_index integer not null check (chunk_index >= 0),
  content text not null,
  -- doctor name, report title, page number, ...
  metadata jsonb not null default '{}' check (jsonb_typeof(metadata) = 'object'),
  embedding extensions.vector(1024) not null,
  content_tsv tsvector generated always as (to_tsvector('english'::regconfig, content)) stored,
  content_hash text not null,
  embedding_model text not null,
  created_at timestamptz not null default now(),
  constraint patient_record_chunks_source_key
    unique (source_type, source_id, chunk_index, embedding_model)
);

create index patient_record_chunks_embedding_idx
  on public.patient_record_chunks using hnsw (embedding extensions.vector_cosine_ops);
create index patient_record_chunks_tsv_idx on public.patient_record_chunks using gin (content_tsv);
create index patient_record_chunks_clinic_patient_idx
  on public.patient_record_chunks (clinic_id, patient_id);
create index patient_record_chunks_patient_id_idx on public.patient_record_chunks (patient_id);

-- ---------------------------------------------------------------------------
-- ingestion_jobs: queue processed by the FastAPI worker (FOR UPDATE SKIP LOCKED).
-- ---------------------------------------------------------------------------
create table public.ingestion_jobs (
  id uuid primary key default gen_random_uuid(),
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  patient_id uuid not null references public.patients (id) on delete cascade,
  source_type public.record_source_type not null,
  source_id uuid not null,
  status public.job_status not null default 'pending',
  attempts integer not null default 0 check (attempts >= 0),
  last_error text,
  run_after timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Repeated triggers for the same source collapse into one pending job.
create unique index ingestion_jobs_pending_source_key
  on public.ingestion_jobs (source_type, source_id)
  where status = 'pending';
create index ingestion_jobs_claim_idx on public.ingestion_jobs (run_after) where status = 'pending';
create index ingestion_jobs_processing_idx
  on public.ingestion_jobs (updated_at) where status = 'processing';
create index ingestion_jobs_clinic_id_idx on public.ingestion_jobs (clinic_id);
create index ingestion_jobs_patient_id_idx on public.ingestion_jobs (patient_id);

create trigger ingestion_jobs_set_updated_at
before update on public.ingestion_jobs
for each row execute function private.set_updated_at();

-- ---------------------------------------------------------------------------
-- Chat: one session per doctor per patient conversation.
-- ---------------------------------------------------------------------------
create table public.patient_chat_sessions (
  id uuid primary key default gen_random_uuid(),
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  patient_id uuid not null references public.patients (id) on delete cascade,
  user_id uuid not null references public.profiles (id) on delete cascade,
  doctor_id uuid references public.doctors (id) on delete set null,
  title text not null check (char_length(title) between 1 and 200),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index patient_chat_sessions_patient_user_idx
  on public.patient_chat_sessions (patient_id, user_id, updated_at desc);
create index patient_chat_sessions_clinic_id_idx on public.patient_chat_sessions (clinic_id);
create index patient_chat_sessions_user_id_idx on public.patient_chat_sessions (user_id);
create index patient_chat_sessions_doctor_id_idx on public.patient_chat_sessions (doctor_id);

create trigger patient_chat_sessions_set_updated_at
before update on public.patient_chat_sessions
for each row execute function private.set_updated_at();

create table public.patient_chat_messages (
  id uuid primary key default gen_random_uuid(),
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  session_id uuid not null references public.patient_chat_sessions (id) on delete cascade,
  role public.chat_role not null,
  content text not null,
  -- [{n, source_type, source_id, label, date, page}]
  citations jsonb not null default '[]' check (jsonb_typeof(citations) = 'array'),
  model text,
  input_tokens integer,
  output_tokens integer,
  latency_ms integer,
  -- Set when the assistant turn failed (provider error, timeout, rate limit).
  error_code text,
  created_at timestamptz not null default now()
);

create index patient_chat_messages_session_idx
  on public.patient_chat_messages (session_id, created_at);
create index patient_chat_messages_clinic_id_idx on public.patient_chat_messages (clinic_id);

-- ---------------------------------------------------------------------------
-- patient_record_access_log: who opened which chart / asked the chatbot, and when.
-- Question text lives only in patient_chat_messages, never here.
-- ---------------------------------------------------------------------------
create table public.patient_record_access_log (
  id bigint generated always as identity primary key,
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  patient_id uuid not null references public.patients (id) on delete cascade,
  user_id uuid references public.profiles (id) on delete set null,
  action public.record_access_action not null,
  appointment_id uuid references public.appointments (id) on delete set null,
  session_id uuid references public.patient_chat_sessions (id) on delete set null,
  report_id uuid references public.patient_reports (id) on delete set null,
  created_at timestamptz not null default now()
);

create index patient_record_access_log_patient_idx
  on public.patient_record_access_log (patient_id, created_at desc);
create index patient_record_access_log_clinic_id_idx on public.patient_record_access_log (clinic_id);
create index patient_record_access_log_user_id_idx on public.patient_record_access_log (user_id);
create index patient_record_access_log_appointment_id_idx
  on public.patient_record_access_log (appointment_id);
create index patient_record_access_log_session_id_idx on public.patient_record_access_log (session_id);
create index patient_record_access_log_report_id_idx on public.patient_record_access_log (report_id);
