-- In-house lab orders: orders (one per doctor request), items (one per test), samples (tubes),
-- results (one row per parameter and version), critical alerts and an audit trail of events.
-- Backend-only except the status-level tables lab_orders and lab_critical_alerts, which are
-- readable through RLS for Realtime (see phase3_rls_realtime). Result values never leave
-- FastAPI.

create type public.lab_priority as enum ('routine', 'urgent', 'stat');
create type public.lab_order_status as enum (
  'ordered', 'in_progress', 'partially_released', 'released', 'cancelled'
);
create type public.lab_item_status as enum (
  'ordered', 'sample_collected', 'sample_rejected', 'result_entered', 'verified', 'released',
  'cancelled'
);
create type public.lab_flag as enum (
  'normal', 'low', 'high', 'critical_low', 'critical_high', 'abnormal'
);

-- ---------------------------------------------------------------------------
-- lab_orders. Status is derived from the items by the service in the same transaction;
-- every item change also touches updated_at so one Realtime subscription covers it.
-- ---------------------------------------------------------------------------
create table public.lab_orders (
  id uuid primary key default gen_random_uuid(),
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  patient_id uuid not null references public.patients (id) on delete cascade,
  ordering_doctor_id uuid not null references public.doctors (id),
  appointment_id uuid not null references public.appointments (id) on delete cascade,
  consultation_id uuid references public.consultations (id) on delete set null,
  -- LAB-YYYYMMDD-NNNN, sequential per clinic-local day (advisory lock in the service).
  order_number text not null check (order_number ~ '^LAB-[0-9]{8}-[0-9]{4,}$'),
  priority public.lab_priority not null default 'routine',
  clinical_note text check (char_length(clinical_note) <= 1000),
  status public.lab_order_status not null default 'ordered',
  cancelled_reason text check (char_length(cancelled_reason) <= 500),
  reviewed_by uuid references public.profiles (id) on delete set null,
  reviewed_at timestamptz,
  created_by uuid references public.profiles (id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint lab_orders_clinic_number_key unique (clinic_id, order_number)
);

create index lab_orders_clinic_status_idx on public.lab_orders (clinic_id, status);
create index lab_orders_clinic_patient_idx on public.lab_orders (clinic_id, patient_id);
create index lab_orders_patient_id_idx on public.lab_orders (patient_id);
create index lab_orders_appointment_id_idx on public.lab_orders (appointment_id);
create index lab_orders_consultation_id_idx on public.lab_orders (consultation_id);
create index lab_orders_ordering_doctor_id_idx on public.lab_orders (ordering_doctor_id);
create index lab_orders_reviewed_by_idx on public.lab_orders (reviewed_by);
create index lab_orders_created_by_idx on public.lab_orders (created_by);

create trigger lab_orders_set_updated_at
before update on public.lab_orders
for each row execute function private.set_updated_at();

-- ---------------------------------------------------------------------------
-- lab_samples: one tube. The code is printed on the label (S-YYMMDD-NNNN per clinic day).
-- Rejecting a sample sends its items back for recollection (a new sample).
-- ---------------------------------------------------------------------------
create table public.lab_samples (
  id uuid primary key default gen_random_uuid(),
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  order_id uuid not null references public.lab_orders (id) on delete cascade,
  sample_code text not null check (sample_code ~ '^S-[0-9]{6}-[0-9]{4,}$'),
  sample_type public.lab_sample_type not null,
  container text check (char_length(container) <= 100),
  collected_by uuid references public.profiles (id) on delete set null,
  collected_at timestamptz not null default now(),
  rejected_by uuid references public.profiles (id) on delete set null,
  rejected_at timestamptz,
  rejected_reason text check (char_length(rejected_reason) <= 500),
  constraint lab_samples_clinic_code_key unique (clinic_id, sample_code),
  constraint lab_samples_rejected check ((rejected_at is null) = (rejected_reason is null))
);

create index lab_samples_order_id_idx on public.lab_samples (order_id);
create index lab_samples_collected_by_idx on public.lab_samples (collected_by);
create index lab_samples_rejected_by_idx on public.lab_samples (rejected_by);

-- ---------------------------------------------------------------------------
-- lab_order_items: one test of an order. Test code/name are snapshotted.
-- ---------------------------------------------------------------------------
create table public.lab_order_items (
  id uuid primary key default gen_random_uuid(),
  order_id uuid not null references public.lab_orders (id) on delete cascade,
  test_id uuid not null references public.lab_tests (id),
  test_code text not null,
  test_name text not null,
  status public.lab_item_status not null default 'ordered',
  sample_id uuid references public.lab_samples (id) on delete set null,
  rejection_reason text check (char_length(rejection_reason) <= 500),
  -- Supervisor's comment when sending entered results back to the technician.
  return_comment text check (char_length(return_comment) <= 1000),
  entered_by uuid references public.profiles (id) on delete set null,
  entered_at timestamptz,
  verified_by uuid references public.profiles (id) on delete set null,
  verified_at timestamptz,
  released_by uuid references public.profiles (id) on delete set null,
  released_at timestamptz,
  cancelled_reason text check (char_length(cancelled_reason) <= 500),
  sort_order integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint lab_order_items_order_test_key unique (order_id, test_id),
  constraint lab_order_items_released check ((status = 'released') = (released_at is not null))
);

create index lab_order_items_test_id_idx on public.lab_order_items (test_id);
create index lab_order_items_sample_id_idx on public.lab_order_items (sample_id);
create index lab_order_items_entered_by_idx on public.lab_order_items (entered_by);
create index lab_order_items_verified_by_idx on public.lab_order_items (verified_by);
create index lab_order_items_released_by_idx on public.lab_order_items (released_by);

create trigger lab_order_items_set_updated_at
before update on public.lab_order_items
for each row execute function private.set_updated_at();

-- ---------------------------------------------------------------------------
-- lab_results: one value per parameter per version. Name, unit and the reference range used
-- are snapshotted at entry, so catalog changes never alter old reports. Corrections after
-- release are new versions (is_current moves to the new row); old versions stay.
-- ---------------------------------------------------------------------------
create table public.lab_results (
  id uuid primary key default gen_random_uuid(),
  order_item_id uuid not null references public.lab_order_items (id) on delete cascade,
  parameter_id uuid not null references public.lab_test_parameters (id),
  parameter_code text not null,
  parameter_name text not null,
  unit text,
  value_type public.lab_value_type not null,
  value_numeric numeric,
  value_text text check (char_length(value_text) <= 500),
  ref_low numeric,
  ref_high numeric,
  ref_critical_low numeric,
  ref_critical_high numeric,
  ref_text_normal text,
  -- Human-readable range as shown on the report, e.g. "4.0–5.6" or "Negative".
  range_label text,
  -- Null when no reference range applies.
  flag public.lab_flag,
  sort_order integer not null default 0,
  version integer not null default 1 check (version >= 1),
  is_current boolean not null default true,
  amended_reason text check (char_length(amended_reason) <= 1000),
  entered_by uuid references public.profiles (id) on delete set null,
  entered_at timestamptz not null default now(),
  constraint lab_results_value check (value_numeric is not null or value_text is not null),
  constraint lab_results_amended check ((version = 1) or (amended_reason is not null)),
  constraint lab_results_item_param_version_key unique (order_item_id, parameter_id, version)
);

create unique index lab_results_current_key
  on public.lab_results (order_item_id, parameter_id) where is_current;
create index lab_results_parameter_id_idx on public.lab_results (parameter_id);
create index lab_results_entered_by_idx on public.lab_results (entered_by);

-- Backstop for "released results are never overwritten" (the service checks first). Once the
-- item is released, a result row may only be retired (is_current true -> false) by an
-- amendment; its values never change. SQLSTATE MF001 is mapped to RECORD_LOCKED.
create function private.prevent_released_result_edit()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  item_status public.lab_item_status;
begin
  select i.status into item_status from public.lab_order_items i where i.id = old.order_item_id;
  if item_status = 'released' and (
    row(new.order_item_id, new.parameter_id, new.value_numeric, new.value_text, new.flag,
        new.version, new.ref_low, new.ref_high, new.ref_critical_low, new.ref_critical_high,
        new.ref_text_normal, new.unit, new.parameter_name, new.entered_by, new.entered_at)
    is distinct from
    row(old.order_item_id, old.parameter_id, old.value_numeric, old.value_text, old.flag,
        old.version, old.ref_low, old.ref_high, old.ref_critical_low, old.ref_critical_high,
        old.ref_text_normal, old.unit, old.parameter_name, old.entered_by, old.entered_at)
    or (new.is_current and not old.is_current)
  ) then
    raise exception 'lab result % is released and cannot be changed', old.id
      using errcode = 'MF001';
  end if;
  return new;
end;
$$;

create trigger lab_results_prevent_released_edit
before update on public.lab_results
for each row execute function private.prevent_released_result_edit();

-- ---------------------------------------------------------------------------
-- lab_critical_alerts: one per critical result, for the ordering doctor, until acknowledged.
-- ---------------------------------------------------------------------------
create table public.lab_critical_alerts (
  id uuid primary key default gen_random_uuid(),
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  result_id uuid not null unique references public.lab_results (id) on delete cascade,
  order_id uuid not null references public.lab_orders (id) on delete cascade,
  patient_id uuid not null references public.patients (id) on delete cascade,
  doctor_id uuid not null references public.doctors (id),
  created_at timestamptz not null default now(),
  acknowledged_by uuid references public.profiles (id) on delete set null,
  acknowledged_at timestamptz,
  note text check (char_length(note) <= 500)
);

create index lab_critical_alerts_open_idx
  on public.lab_critical_alerts (doctor_id) where acknowledged_at is null;
create index lab_critical_alerts_doctor_id_idx on public.lab_critical_alerts (doctor_id);
create index lab_critical_alerts_clinic_id_idx on public.lab_critical_alerts (clinic_id);
create index lab_critical_alerts_order_id_idx on public.lab_critical_alerts (order_id);
create index lab_critical_alerts_patient_id_idx on public.lab_critical_alerts (patient_id);
create index lab_critical_alerts_acknowledged_by_idx on public.lab_critical_alerts (acknowledged_by);

-- ---------------------------------------------------------------------------
-- lab_order_events: audit trail of every status change (ids and statuses only, never values).
-- 'lab_report_released' is the hook for notifying patients later (WhatsApp/SMS).
-- ---------------------------------------------------------------------------
create table public.lab_order_events (
  id bigint generated always as identity primary key,
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  order_id uuid not null references public.lab_orders (id) on delete cascade,
  order_item_id uuid references public.lab_order_items (id) on delete set null,
  event text not null check (event in (
    'ordered', 'cancelled', 'collected', 'rejected', 'recollected', 'results_saved',
    'submitted', 'sent_back', 'verified', 'released', 'amended', 'reviewed', 'critical_ack',
    'lab_report_released'
  )),
  from_status text,
  to_status text,
  actor_id uuid references public.profiles (id) on delete set null,
  created_at timestamptz not null default now()
);

create index lab_order_events_order_id_idx on public.lab_order_events (order_id);
create index lab_order_events_order_item_id_idx on public.lab_order_events (order_item_id);
create index lab_order_events_clinic_id_idx on public.lab_order_events (clinic_id);
create index lab_order_events_actor_id_idx on public.lab_order_events (actor_id);

-- ---------------------------------------------------------------------------
-- patient_reports: link lab PDFs to their order. is_generated marks the report the clinic
-- produces from structured results (one per order); others are the lab machine's own PDF.
-- Lab-linked reports are not indexed separately (their structured results are).
-- ---------------------------------------------------------------------------
alter table public.patient_reports
  add column lab_order_id uuid references public.lab_orders (id) on delete cascade,
  add column is_generated boolean not null default false,
  add constraint patient_reports_generated_has_order
    check (not is_generated or lab_order_id is not null);

create index patient_reports_lab_order_id_idx on public.patient_reports (lab_order_id);
create unique index patient_reports_generated_order_key
  on public.patient_reports (lab_order_id) where is_generated;
