-- Core clinic schema. Every business table carries clinic_id for future multi-clinic support.

-- Internal helpers live in `private`, which is not exposed through the Data API.
create schema if not exists private;
revoke all on schema private from public;

-- ---------------------------------------------------------------------------
-- Enums
-- ---------------------------------------------------------------------------
create type public.user_role as enum ('admin', 'receptionist', 'doctor');

create type public.appointment_status as enum (
  'pending_confirmation',
  'scheduled',
  'checked_in',
  'in_consultation',
  'completed',
  'cancelled',
  'no_show'
);

create type public.appointment_source as enum ('walk_in', 'phone', 'manual', 'whatsapp', 'voice');

create type public.gender as enum ('male', 'female', 'other');

create type public.actor_type as enum ('user', 'system');

create type public.inbound_channel as enum ('whatsapp', 'voice');

create type public.inbound_status as enum ('received', 'auto_booked', 'needs_review', 'rejected');

-- ---------------------------------------------------------------------------
-- Shared trigger: updated_at
-- ---------------------------------------------------------------------------
create function private.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

-- ---------------------------------------------------------------------------
-- clinics
-- ---------------------------------------------------------------------------
create table public.clinics (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(name) between 1 and 200),
  phone text,
  address text,
  timezone text not null default 'Asia/Kolkata',
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- profiles (1:1 with auth.users; staff only, no public sign-up)
-- ---------------------------------------------------------------------------
create table public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  full_name text not null check (char_length(full_name) between 1 and 120),
  phone text,
  role public.user_role not null,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create index profiles_clinic_id_idx on public.profiles (clinic_id);

-- ---------------------------------------------------------------------------
-- doctors (profile_id nullable: a doctor may exist before they get a login)
-- ---------------------------------------------------------------------------
create table public.doctors (
  id uuid primary key default gen_random_uuid(),
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  profile_id uuid unique references public.profiles (id) on delete set null,
  full_name text not null check (char_length(full_name) between 1 and 120),
  specialization text not null check (char_length(specialization) between 1 and 120),
  consultation_fee numeric(10, 2) not null default 0 check (consultation_fee >= 0),
  default_slot_minutes integer not null default 15 check (default_slot_minutes between 5 and 240),
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create index doctors_clinic_id_idx on public.doctors (clinic_id);

-- weekday: 0 = Monday ... 6 = Sunday (matches Python date.weekday()).
-- Multiple rows per weekday allowed (e.g. morning + evening shift).
create table public.doctor_schedules (
  id uuid primary key default gen_random_uuid(),
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  doctor_id uuid not null references public.doctors (id) on delete cascade,
  weekday smallint not null check (weekday between 0 and 6),
  start_time time not null,
  end_time time not null,
  created_at timestamptz not null default now(),
  constraint doctor_schedules_time_order check (start_time < end_time)
);

create index doctor_schedules_clinic_id_idx on public.doctor_schedules (clinic_id);
create index doctor_schedules_doctor_weekday_idx on public.doctor_schedules (doctor_id, weekday);

create table public.doctor_leaves (
  id uuid primary key default gen_random_uuid(),
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  doctor_id uuid not null references public.doctors (id) on delete cascade,
  leave_date date not null,
  reason text,
  created_at timestamptz not null default now(),
  constraint doctor_leaves_doctor_date_key unique (doctor_id, leave_date)
);

create index doctor_leaves_clinic_id_idx on public.doctor_leaves (clinic_id);

-- ---------------------------------------------------------------------------
-- patients (phone NOT unique: families share numbers)
-- ---------------------------------------------------------------------------
create table public.patients (
  id uuid primary key default gen_random_uuid(),
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  full_name text not null check (char_length(full_name) between 1 and 120),
  phone text not null check (phone ~ '^\+[1-9][0-9]{7,14}$'),
  alternate_phone text check (alternate_phone is null or alternate_phone ~ '^\+[1-9][0-9]{7,14}$'),
  gender public.gender,
  date_of_birth date,
  age_years smallint check (age_years is null or age_years between 0 and 130),
  address text,
  notes text,
  created_by uuid references public.profiles (id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index patients_clinic_phone_idx on public.patients (clinic_id, phone);
create index patients_created_by_idx on public.patients (created_by);
create index patients_full_name_trgm_idx on public.patients using gin (full_name extensions.gin_trgm_ops);
create index patients_phone_trgm_idx on public.patients using gin (phone extensions.gin_trgm_ops);

create trigger patients_set_updated_at
before update on public.patients
for each row execute function private.set_updated_at();

-- ---------------------------------------------------------------------------
-- appointments
-- ---------------------------------------------------------------------------
create table public.appointments (
  id uuid primary key default gen_random_uuid(),
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  patient_id uuid not null references public.patients (id),
  doctor_id uuid not null references public.doctors (id),
  starts_at timestamptz not null,
  ends_at timestamptz not null,
  -- Clinic-local (IST) calendar date of starts_at; maintained by trigger. Scopes token numbers.
  appointment_date date not null,
  status public.appointment_status not null default 'scheduled',
  source public.appointment_source not null,
  token_number integer not null check (token_number > 0),
  reason_for_visit text,
  notes text,
  created_by uuid references public.profiles (id) on delete set null,
  external_ref text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint appointments_time_order check (ends_at > starts_at),
  -- No double booking: a doctor cannot have two live appointments overlapping in time.
  constraint appointments_no_overlap exclude using gist (
    doctor_id with =,
    tstzrange(starts_at, ends_at, '[)') with &&
  ) where (status not in ('cancelled', 'no_show'))
);

create unique index appointments_doctor_day_token_key
  on public.appointments (doctor_id, appointment_date, token_number);
create unique index appointments_external_ref_key
  on public.appointments (clinic_id, source, external_ref)
  where external_ref is not null;
create index appointments_clinic_date_idx on public.appointments (clinic_id, appointment_date);
create index appointments_patient_id_idx on public.appointments (patient_id);
create index appointments_created_by_idx on public.appointments (created_by);

create function private.set_appointment_date()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  tz text;
begin
  select c.timezone into tz from public.clinics c where c.id = new.clinic_id;
  new.appointment_date := (new.starts_at at time zone coalesce(tz, 'Asia/Kolkata'))::date;
  return new;
end;
$$;

create trigger appointments_set_date
before insert or update of starts_at, clinic_id on public.appointments
for each row execute function private.set_appointment_date();

create trigger appointments_set_updated_at
before update on public.appointments
for each row execute function private.set_updated_at();

-- ---------------------------------------------------------------------------
-- appointment_events (audit log)
-- ---------------------------------------------------------------------------
create table public.appointment_events (
  id bigint generated always as identity primary key,
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  appointment_id uuid not null references public.appointments (id) on delete cascade,
  from_status public.appointment_status,
  to_status public.appointment_status not null,
  changed_by uuid references public.profiles (id) on delete set null,
  actor_type public.actor_type not null,
  -- 'dashboard' for staff actions, otherwise the bot channel ('whatsapp' | 'voice').
  channel text not null check (channel in ('dashboard', 'whatsapp', 'voice')),
  note text,
  created_at timestamptz not null default now()
);

create index appointment_events_appointment_id_idx on public.appointment_events (appointment_id);
create index appointment_events_clinic_id_idx on public.appointment_events (clinic_id);
create index appointment_events_changed_by_idx on public.appointment_events (changed_by);

-- ---------------------------------------------------------------------------
-- inbound_booking_requests (future WhatsApp / voice channels)
-- ---------------------------------------------------------------------------
create table public.inbound_booking_requests (
  id uuid primary key default gen_random_uuid(),
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  channel public.inbound_channel not null,
  external_ref text,
  raw_payload jsonb not null,
  caller_phone text,
  parsed_patient_name text,
  requested_doctor_id uuid references public.doctors (id) on delete set null,
  requested_time timestamptz,
  status public.inbound_status not null default 'received',
  appointment_id uuid references public.appointments (id) on delete set null,
  error text,
  created_at timestamptz not null default now()
);

create unique index inbound_booking_requests_external_ref_key
  on public.inbound_booking_requests (clinic_id, channel, external_ref)
  where external_ref is not null;
create index inbound_booking_requests_clinic_created_idx
  on public.inbound_booking_requests (clinic_id, created_at desc);
create index inbound_booking_requests_doctor_idx on public.inbound_booking_requests (requested_doctor_id);
create index inbound_booking_requests_appointment_idx on public.inbound_booking_requests (appointment_id);
