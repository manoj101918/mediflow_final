-- Phase 4: WhatsApp / voice booking bot. Every table here is backend-only: RLS on, no
-- policies, no grants for anon/authenticated, nothing in the realtime publication.

create type public.bot_channel as enum ('whatsapp', 'web_voice', 'phone');
create type public.bot_handoff_status as enum ('none', 'open', 'resolved');
create type public.message_direction as enum ('inbound', 'outbound');
-- Inbound: received -> processed | ignored | failed. Outbound: sent -> delivered -> read | failed.
create type public.channel_message_status as enum (
  'received', 'processed', 'ignored', 'sent', 'delivered', 'read', 'failed'
);
create type public.outbox_status as enum (
  'pending', 'sent', 'delivered', 'read', 'failed', 'blocked'
);

-- ---------------------------------------------------------------------------
-- bot_conversations: one per (clinic, channel, phone); the engine's state machine row.
-- ---------------------------------------------------------------------------
create table public.bot_conversations (
  id uuid primary key default gen_random_uuid(),
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  channel public.bot_channel not null,
  phone_e164 text not null check (phone_e164 ~ '^\+[1-9][0-9]{6,14}$'),
  state text not null default 'new' check (char_length(state) between 1 and 40),
  language text check (language in ('te', 'hi', 'en')),
  selected_patient_id uuid references public.patients (id) on delete set null,
  draft jsonb not null default '{}'::jsonb,
  attempt_counter integer not null default 0 check (attempt_counter >= 0),
  last_inbound_at timestamptz,
  -- Meta's timestamp of the newest processed inbound message (out-of-order detection).
  last_message_ts timestamptz,
  handoff_status public.bot_handoff_status not null default 'none',
  handoff_reason text check (handoff_reason in ('button', 'parse_failed', 'emergency', 'staff')),
  handoff_at timestamptz,
  assigned_to uuid references public.profiles (id) on delete set null,
  failed_parse_count integer not null default 0 check (failed_parse_count >= 0),
  version integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (clinic_id, channel, phone_e164)
);

create index bot_conversations_handoff_idx
  on public.bot_conversations (clinic_id, handoff_at desc) where handoff_status = 'open';
create index bot_conversations_patient_idx on public.bot_conversations (selected_patient_id);
create index bot_conversations_assigned_idx on public.bot_conversations (assigned_to);

create trigger bot_conversations_set_updated_at
before update on public.bot_conversations
for each row execute function private.set_updated_at();

-- ---------------------------------------------------------------------------
-- channel_messages: every inbound and outbound message (the chat transcript).
-- Raw webhook payloads are stored here before any processing; wamid deduplicates.
-- ---------------------------------------------------------------------------
create table public.channel_messages (
  id uuid primary key default gen_random_uuid(),
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  conversation_id uuid references public.bot_conversations (id) on delete cascade,
  direction public.message_direction not null,
  channel public.bot_channel not null,
  phone_e164 text not null,
  wamid text,
  type text not null check (char_length(type) between 1 and 40),
  payload jsonb not null default '{}'::jsonb,
  -- Readable text of the message: typed text, the chosen button/row title, or the reply.
  body_text text,
  -- Voice notes: only the transcript is kept; the audio is never stored.
  transcript text,
  status public.channel_message_status not null,
  error text,
  -- When the message was sent (Meta's timestamp for inbound).
  message_ts timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index channel_messages_wamid_key on public.channel_messages (wamid)
  where wamid is not null;
create index channel_messages_conversation_idx
  on public.channel_messages (conversation_id, message_ts);
create index channel_messages_clinic_created_idx
  on public.channel_messages (clinic_id, created_at desc);

create trigger channel_messages_set_updated_at
before update on public.channel_messages
for each row execute function private.set_updated_at();

-- ---------------------------------------------------------------------------
-- message_outbox: every message the clinic wants to send, idempotent by key.
-- ---------------------------------------------------------------------------
create table public.message_outbox (
  id uuid primary key default gen_random_uuid(),
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  conversation_id uuid not null references public.bot_conversations (id) on delete cascade,
  appointment_id uuid references public.appointments (id) on delete set null,
  channel public.bot_channel not null,
  phone_e164 text not null,
  kind text not null check (kind in (
    'reply', 'notice', 'approval', 'rejection', 'staff_reply', 'emergency', 'opt_out'
  )),
  essential boolean not null default false,
  idempotency_key text not null unique check (char_length(idempotency_key) between 1 and 200),
  body jsonb not null,
  status public.outbox_status not null default 'pending',
  blocked_reason text check (blocked_reason in (
    'opted_out', 'no_consent', 'window_closed', 'limit', 'not_configured'
  )),
  wamid text,
  attempts integer not null default 0 check (attempts >= 0),
  last_error text,
  sent_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index message_outbox_conversation_idx on public.message_outbox (conversation_id, created_at);
create index message_outbox_appointment_idx on public.message_outbox (appointment_id);
create index message_outbox_clinic_idx on public.message_outbox (clinic_id, created_at desc);
create unique index message_outbox_wamid_key on public.message_outbox (wamid) where wamid is not null;

create trigger message_outbox_set_updated_at
before update on public.message_outbox
for each row execute function private.set_updated_at();

-- ---------------------------------------------------------------------------
-- contact_preferences: opt-in / opt-out per phone. An opt-out applies to every channel.
-- ---------------------------------------------------------------------------
create table public.contact_preferences (
  id uuid primary key default gen_random_uuid(),
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  phone_e164 text not null,
  -- Channel of the most recent change.
  channel public.bot_channel not null,
  opted_in_at timestamptz,
  opted_in_source text,
  opted_out_at timestamptz,
  updated_at timestamptz not null default now(),
  unique (clinic_id, phone_e164)
);

create trigger contact_preferences_set_updated_at
before update on public.contact_preferences
for each row execute function private.set_updated_at();

-- ---------------------------------------------------------------------------
-- consent_events: append-only evidence of notices shown, consent given and opt-outs.
-- ---------------------------------------------------------------------------
create table public.consent_events (
  id bigint generated always as identity primary key,
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  phone_e164 text not null,
  patient_id uuid references public.patients (id) on delete set null,
  channel public.bot_channel not null,
  notice_version text not null,
  action text not null check (action in ('notice_shown', 'consented', 'opted_out', 'opted_in')),
  -- wamid (or simulator message id) of the message that is the evidence.
  evidence text,
  created_at timestamptz not null default now()
);

create index consent_events_phone_idx on public.consent_events (clinic_id, phone_e164, created_at);
create index consent_events_patient_idx on public.consent_events (patient_id);

-- ---------------------------------------------------------------------------
-- bot_jobs: queue processed by the FastAPI bot worker (FOR UPDATE SKIP LOCKED).
-- ---------------------------------------------------------------------------
create table public.bot_jobs (
  id uuid primary key default gen_random_uuid(),
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  kind text not null check (kind in ('inbound', 'status', 'outbox')),
  -- inbound: channel_messages.id; outbox: message_outbox.id; status: null (payload holds it).
  ref_id uuid,
  payload jsonb not null default '{}'::jsonb,
  status public.job_status not null default 'pending',
  attempts integer not null default 0 check (attempts >= 0),
  last_error text,
  run_after timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index bot_jobs_pending_ref_key on public.bot_jobs (kind, ref_id)
  where status = 'pending' and ref_id is not null;
create index bot_jobs_claim_idx on public.bot_jobs (run_after) where status = 'pending';
create index bot_jobs_processing_idx on public.bot_jobs (updated_at) where status = 'processing';
create index bot_jobs_clinic_id_idx on public.bot_jobs (clinic_id);

create trigger bot_jobs_set_updated_at
before update on public.bot_jobs
for each row execute function private.set_updated_at();

-- ---------------------------------------------------------------------------
-- bot_usage_monthly: outbound messages sent per channel per calendar month (UTC),
-- compared against Meta's free service-message allowance.
-- ---------------------------------------------------------------------------
create table public.bot_usage_monthly (
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  channel public.bot_channel not null,
  month date not null check (extract(day from month) = 1),
  sent_count integer not null default 0 check (sent_count >= 0),
  updated_at timestamptz not null default now(),
  primary key (clinic_id, channel, month)
);

-- ---------------------------------------------------------------------------
-- bot_alerts: emergencies and handoffs for the reception inbox.
-- ---------------------------------------------------------------------------
create table public.bot_alerts (
  id uuid primary key default gen_random_uuid(),
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  conversation_id uuid not null references public.bot_conversations (id) on delete cascade,
  message_id uuid references public.channel_messages (id) on delete set null,
  kind text not null check (kind in ('emergency', 'handoff')),
  created_at timestamptz not null default now(),
  acknowledged_at timestamptz,
  acknowledged_by uuid references public.profiles (id) on delete set null
);

create index bot_alerts_open_idx on public.bot_alerts (clinic_id, created_at desc)
  where acknowledged_at is null;
create index bot_alerts_conversation_idx on public.bot_alerts (conversation_id);
create index bot_alerts_message_idx on public.bot_alerts (message_id);
create index bot_alerts_ack_by_idx on public.bot_alerts (acknowledged_by);

-- ---------------------------------------------------------------------------
-- bot_keyword_lists: per-clinic overrides of the built-in keyword lists.
-- ---------------------------------------------------------------------------
create table public.bot_keyword_lists (
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  kind text not null check (kind in ('emergency', 'stop', 'start')),
  language text not null check (language in ('te', 'hi', 'en')),
  words text[] not null default '{}',
  updated_by uuid references public.profiles (id) on delete set null,
  updated_at timestamptz not null default now(),
  primary key (clinic_id, kind, language)
);

create index bot_keyword_lists_updated_by_idx on public.bot_keyword_lists (updated_by);

create trigger bot_keyword_lists_set_updated_at
before update on public.bot_keyword_lists
for each row execute function private.set_updated_at();

-- ---------------------------------------------------------------------------
-- Security: backend only.
-- ---------------------------------------------------------------------------
alter table public.bot_conversations enable row level security;
alter table public.channel_messages enable row level security;
alter table public.message_outbox enable row level security;
alter table public.contact_preferences enable row level security;
alter table public.consent_events enable row level security;
alter table public.bot_jobs enable row level security;
alter table public.bot_usage_monthly enable row level security;
alter table public.bot_alerts enable row level security;
alter table public.bot_keyword_lists enable row level security;

revoke all on table
  public.bot_conversations,
  public.channel_messages,
  public.message_outbox,
  public.contact_preferences,
  public.consent_events,
  public.bot_jobs,
  public.bot_usage_monthly,
  public.bot_alerts,
  public.bot_keyword_lists
from anon, authenticated;
