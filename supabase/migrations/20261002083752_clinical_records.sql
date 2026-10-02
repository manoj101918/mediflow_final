-- Clinical records: medical profile, consultations (one per appointment), addenda,
-- prescriptions and uploaded reports. All of it is backend-only (RLS on, no client policies;
-- see the phase2_rls_storage migration).

-- ---------------------------------------------------------------------------
-- Enums
-- ---------------------------------------------------------------------------
create type public.consultation_status as enum ('draft', 'finalized');

create type public.report_type as enum (
  'lab', 'imaging', 'discharge_summary', 'referral', 'old_prescription', 'other'
);

-- How a report's text was obtained. Only pypdf text extraction for now.
create type public.extraction_method as enum ('text');

-- no_text: stored and viewable, but no extractable text (images, scanned PDFs); not searchable.
create type public.ingestion_status as enum ('pending', 'processing', 'indexed', 'failed', 'no_text');

-- ---------------------------------------------------------------------------
-- patient_medical_profiles (1:1 with patients). A separate table rather than columns on
-- `patients`, because reception reads `patients` and must never see clinical data.
-- ---------------------------------------------------------------------------
create table public.patient_medical_profiles (
  patient_id uuid primary key references public.patients (id) on delete cascade,
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  blood_group text check (
    blood_group is null or blood_group in ('A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-')
  ),
  allergies text[] not null default '{}',
  chronic_conditions text[] not null default '{}',
  updated_by uuid references public.profiles (id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index patient_medical_profiles_clinic_id_idx on public.patient_medical_profiles (clinic_id);
create index patient_medical_profiles_updated_by_idx on public.patient_medical_profiles (updated_by);

create trigger patient_medical_profiles_set_updated_at
before update on public.patient_medical_profiles
for each row execute function private.set_updated_at();

-- ---------------------------------------------------------------------------
-- consultations: one per appointment (= one visit). Finalized ones are read-only;
-- corrections go into consultation_addenda.
-- ---------------------------------------------------------------------------
create table public.consultations (
  id uuid primary key default gen_random_uuid(),
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  appointment_id uuid not null unique references public.appointments (id) on delete cascade,
  patient_id uuid not null references public.patients (id) on delete cascade,
  doctor_id uuid not null references public.doctors (id),
  chief_complaint text check (char_length(chief_complaint) <= 5000),
  history text check (char_length(history) <= 10000),
  examination text check (char_length(examination) <= 10000),
  diagnosis text check (char_length(diagnosis) <= 5000),
  advice text check (char_length(advice) <= 10000),
  follow_up_date date,
  notes text check (char_length(notes) <= 10000),
  -- bp_systolic, bp_diastolic, pulse, temperature_c, weight_kg, height_cm, spo2, blood_sugar
  vitals jsonb not null default '{}' check (jsonb_typeof(vitals) = 'object'),
  status public.consultation_status not null default 'draft',
  finalized_at timestamptz,
  created_by uuid references public.profiles (id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint consultations_finalized_at check ((status = 'finalized') = (finalized_at is not null))
);

create index consultations_clinic_patient_idx on public.consultations (clinic_id, patient_id);
create index consultations_patient_id_idx on public.consultations (patient_id);
create index consultations_doctor_id_idx on public.consultations (doctor_id);
create index consultations_created_by_idx on public.consultations (created_by);

create trigger consultations_set_updated_at
before update on public.consultations
for each row execute function private.set_updated_at();

-- Database backstop for "finalized is read-only" (the service checks first and returns
-- RECORD_LOCKED). SQLSTATE MF001 is mapped by the backend.
create function private.prevent_finalized_consultation_edit()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if old.status = 'finalized' then
    raise exception 'consultation % is finalized and cannot be changed', old.id
      using errcode = 'MF001';
  end if;
  return new;
end;
$$;

create trigger consultations_prevent_finalized_edit
before update on public.consultations
for each row execute function private.prevent_finalized_consultation_edit();

-- ---------------------------------------------------------------------------
-- consultation_addenda: corrections/additions to a finalized consultation.
-- ---------------------------------------------------------------------------
create table public.consultation_addenda (
  id uuid primary key default gen_random_uuid(),
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  consultation_id uuid not null references public.consultations (id) on delete cascade,
  author_id uuid references public.profiles (id) on delete set null,
  -- Name at the time of writing, so the record still reads correctly if the profile changes.
  author_name text not null check (char_length(author_name) between 1 and 120),
  text text not null check (char_length(text) between 1 and 5000),
  created_at timestamptz not null default now()
);

create index consultation_addenda_consultation_id_idx on public.consultation_addenda (consultation_id);
create index consultation_addenda_clinic_id_idx on public.consultation_addenda (clinic_id);
create index consultation_addenda_author_id_idx on public.consultation_addenda (author_id);

-- ---------------------------------------------------------------------------
-- prescriptions (one per consultation) and their items.
-- ---------------------------------------------------------------------------
create table public.prescriptions (
  id uuid primary key default gen_random_uuid(),
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  consultation_id uuid not null unique references public.consultations (id) on delete cascade,
  patient_id uuid not null references public.patients (id) on delete cascade,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index prescriptions_clinic_patient_idx on public.prescriptions (clinic_id, patient_id);
create index prescriptions_patient_id_idx on public.prescriptions (patient_id);

create trigger prescriptions_set_updated_at
before update on public.prescriptions
for each row execute function private.set_updated_at();

create table public.prescription_items (
  id uuid primary key default gen_random_uuid(),
  prescription_id uuid not null references public.prescriptions (id) on delete cascade,
  medicine_name text not null check (char_length(medicine_name) between 1 and 200),
  strength text check (char_length(strength) <= 50),
  dosage_form text check (char_length(dosage_form) <= 50),
  dose text check (char_length(dose) <= 50),
  route text check (char_length(route) <= 50),
  -- Indian style, e.g. 1-0-1, 1-1-1, 0-0-1, SOS
  frequency text check (char_length(frequency) <= 30),
  timing text check (
    timing is null
    or timing in ('before_food', 'after_food', 'with_food', 'empty_stomach', 'bedtime', 'any')
  ),
  duration_days integer check (duration_days is null or duration_days between 1 and 3650),
  instructions text check (char_length(instructions) <= 1000),
  sort_order smallint not null default 0,
  created_at timestamptz not null default now()
);

create index prescription_items_prescription_idx
  on public.prescription_items (prescription_id, sort_order);

-- Backstop: items of a finalized consultation cannot be added or changed.
create function private.prevent_finalized_prescription_edit()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if exists (
    select 1
    from public.prescriptions p
    join public.consultations c on c.id = p.consultation_id
    where p.id = new.prescription_id and c.status = 'finalized'
  ) then
    raise exception 'prescription % belongs to a finalized consultation', new.prescription_id
      using errcode = 'MF001';
  end if;
  return new;
end;
$$;

create trigger prescription_items_prevent_finalized_edit
before insert or update on public.prescription_items
for each row execute function private.prevent_finalized_prescription_edit();

-- ---------------------------------------------------------------------------
-- patient_reports: uploaded files in the private `patient-reports` bucket at
-- {clinic_id}/{patient_id}/{report_id}.{ext}
-- ---------------------------------------------------------------------------
create table public.patient_reports (
  id uuid primary key default gen_random_uuid(),
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  patient_id uuid not null references public.patients (id) on delete cascade,
  consultation_id uuid references public.consultations (id) on delete set null,
  uploaded_by uuid references public.profiles (id) on delete set null,
  title text not null check (char_length(title) between 1 and 200),
  report_type public.report_type not null,
  report_date date,
  storage_path text not null unique,
  mime_type text not null check (mime_type in ('application/pdf', 'image/jpeg', 'image/png')),
  size_bytes integer not null check (size_bytes > 0),
  page_count integer check (page_count is null or page_count >= 0),
  extracted_text text,
  extraction_method public.extraction_method,
  ingestion_status public.ingestion_status not null default 'pending',
  ingestion_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index patient_reports_clinic_patient_idx on public.patient_reports (clinic_id, patient_id);
create index patient_reports_patient_date_idx on public.patient_reports (patient_id, report_date desc);
create index patient_reports_consultation_id_idx on public.patient_reports (consultation_id);
create index patient_reports_uploaded_by_idx on public.patient_reports (uploaded_by);

create trigger patient_reports_set_updated_at
before update on public.patient_reports
for each row execute function private.set_updated_at();
