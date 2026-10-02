-- In-house lab test catalog (managed by admin). Backend-only: RLS on, no client policies
-- (see phase3_rls_realtime). Results snapshot name/unit/range at entry, so editing the catalog
-- never changes old results.

create type public.lab_category as enum (
  'haematology', 'biochemistry', 'hormones', 'urine', 'serology', 'other'
);
create type public.lab_sample_type as enum ('blood', 'urine', 'stool', 'swab', 'other');
create type public.lab_value_type as enum ('numeric', 'text', 'choice');
create type public.lab_range_sex as enum ('male', 'female', 'any');

-- Per-clinic setting: technician enters, supervisor verifies before release.
alter table public.clinics
  add column lab_requires_verification boolean not null default true;

create table public.lab_tests (
  id uuid primary key default gen_random_uuid(),
  clinic_id uuid not null references public.clinics (id) on delete cascade,
  code text not null check (code ~ '^[A-Z0-9_-]{1,20}$'),
  name text not null check (char_length(name) between 1 and 200),
  category public.lab_category not null,
  sample_type public.lab_sample_type not null,
  container text check (char_length(container) <= 100),
  turnaround_hours smallint not null default 24 check (turnaround_hours between 1 and 720),
  is_panel boolean not null default false,
  is_active boolean not null default true,
  sort_order integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint lab_tests_clinic_code_key unique (clinic_id, code)
);

create index lab_tests_clinic_active_idx on public.lab_tests (clinic_id, is_active);

create trigger lab_tests_set_updated_at
before update on public.lab_tests
for each row execute function private.set_updated_at();

create table public.lab_test_parameters (
  id uuid primary key default gen_random_uuid(),
  test_id uuid not null references public.lab_tests (id) on delete cascade,
  code text not null check (code ~ '^[A-Z0-9_-]{1,30}$'),
  name text not null check (char_length(name) between 1 and 200),
  unit text check (char_length(unit) <= 40),
  value_type public.lab_value_type not null default 'numeric',
  choices text[] not null default '{}',
  decimals smallint not null default 1 check (decimals between 0 and 4),
  -- Warn when a new value differs from the previous one by more than this percentage.
  delta_percent numeric check (delta_percent > 0),
  is_active boolean not null default true,
  sort_order integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint lab_test_parameters_test_code_key unique (test_id, code),
  constraint lab_test_parameters_choices check (
    (value_type = 'choice') = (cardinality(choices) > 0)
  )
);

create trigger lab_test_parameters_set_updated_at
before update on public.lab_test_parameters
for each row execute function private.set_updated_at();

create table public.lab_reference_ranges (
  id uuid primary key default gen_random_uuid(),
  parameter_id uuid not null references public.lab_test_parameters (id) on delete cascade,
  sex public.lab_range_sex not null default 'any',
  age_min_years smallint check (age_min_years between 0 and 150),
  age_max_years smallint check (age_max_years between 0 and 150),
  low numeric,
  high numeric,
  critical_low numeric,
  critical_high numeric,
  -- Expected value for text/choice parameters (e.g. 'Negative').
  text_normal text check (char_length(text_normal) <= 100),
  created_at timestamptz not null default now(),
  constraint lab_reference_ranges_age check (
    age_min_years is null or age_max_years is null or age_min_years <= age_max_years
  ),
  constraint lab_reference_ranges_low_high check (low is null or high is null or low <= high),
  constraint lab_reference_ranges_critical_low check (
    critical_low is null or ((low is null or critical_low <= low) and (high is null or critical_low < high))
  ),
  constraint lab_reference_ranges_critical_high check (
    critical_high is null or ((high is null or critical_high >= high) and (low is null or critical_high > low))
  )
);

create index lab_reference_ranges_parameter_id_idx on public.lab_reference_ranges (parameter_id);

alter table public.lab_tests enable row level security;
alter table public.lab_test_parameters enable row level security;
alter table public.lab_reference_ranges enable row level security;
revoke all on public.lab_tests, public.lab_test_parameters, public.lab_reference_ranges
  from anon, authenticated;
