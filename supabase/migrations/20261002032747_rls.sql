-- Row Level Security.
-- FastAPI connects as the database owner and enforces access in its service layer; these
-- policies protect direct Supabase access (Realtime subscriptions with the user's JWT) and act
-- as a final safety net. Deactivated profiles resolve to NULL in every helper, so they see nothing.

-- ---------------------------------------------------------------------------
-- Helper functions (private schema, not exposed via the Data API)
-- ---------------------------------------------------------------------------
create function private.current_clinic_id()
returns uuid
language sql
stable
security definer
set search_path = ''
as $$
  select p.clinic_id
  from public.profiles p
  where p.id = (select auth.uid()) and p.is_active
$$;

create function private.current_app_role()
returns public.user_role
language sql
stable
security definer
set search_path = ''
as $$
  select p.role
  from public.profiles p
  where p.id = (select auth.uid()) and p.is_active
$$;

create function private.current_doctor_id()
returns uuid
language sql
stable
security definer
set search_path = ''
as $$
  select d.id
  from public.doctors d
  join public.profiles p on p.id = d.profile_id
  where p.id = (select auth.uid()) and p.is_active and p.role = 'doctor'
$$;

revoke all on all functions in schema private from public, anon;
grant usage on schema private to authenticated;
grant execute on function private.current_clinic_id() to authenticated;
grant execute on function private.current_app_role() to authenticated;
grant execute on function private.current_doctor_id() to authenticated;

-- ---------------------------------------------------------------------------
-- Enable RLS everywhere; the anon role gets no table access at all.
-- ---------------------------------------------------------------------------
alter table public.clinics enable row level security;
alter table public.profiles enable row level security;
alter table public.doctors enable row level security;
alter table public.doctor_schedules enable row level security;
alter table public.doctor_leaves enable row level security;
alter table public.patients enable row level security;
alter table public.appointments enable row level security;
alter table public.appointment_events enable row level security;
alter table public.inbound_booking_requests enable row level security;

revoke all on all tables in schema public from anon;

-- ---------------------------------------------------------------------------
-- Reference data: readable by any active staff member of the same clinic.
-- Writes go through FastAPI only (no client write policies).
-- ---------------------------------------------------------------------------
create policy clinics_select on public.clinics
  for select to authenticated
  using (id = (select private.current_clinic_id()));

create policy doctors_select on public.doctors
  for select to authenticated
  using (clinic_id = (select private.current_clinic_id()));

create policy doctor_schedules_select on public.doctor_schedules
  for select to authenticated
  using (clinic_id = (select private.current_clinic_id()));

create policy doctor_leaves_select on public.doctor_leaves
  for select to authenticated
  using (clinic_id = (select private.current_clinic_id()));

-- profiles: own row always; reception/admin see all staff in their clinic.
create policy profiles_select on public.profiles
  for select to authenticated
  using (
    id = (select auth.uid())
    or (
      clinic_id = (select private.current_clinic_id())
      and (select private.current_app_role()) in ('admin', 'receptionist')
    )
  );

-- ---------------------------------------------------------------------------
-- patients: reception/admin read+write in clinic; doctors read only their patients.
-- ---------------------------------------------------------------------------
create policy patients_select on public.patients
  for select to authenticated
  using (
    clinic_id = (select private.current_clinic_id())
    and (
      (select private.current_app_role()) in ('admin', 'receptionist')
      or exists (
        select 1
        from public.appointments a
        where a.patient_id = patients.id
          and a.doctor_id = (select private.current_doctor_id())
      )
    )
  );

create policy patients_insert on public.patients
  for insert to authenticated
  with check (
    clinic_id = (select private.current_clinic_id())
    and (select private.current_app_role()) in ('admin', 'receptionist')
  );

create policy patients_update on public.patients
  for update to authenticated
  using (
    clinic_id = (select private.current_clinic_id())
    and (select private.current_app_role()) in ('admin', 'receptionist')
  )
  with check (
    clinic_id = (select private.current_clinic_id())
    and (select private.current_app_role()) in ('admin', 'receptionist')
  );

-- ---------------------------------------------------------------------------
-- appointments: reception/admin read+write in clinic; doctors read only their own.
-- ---------------------------------------------------------------------------
create policy appointments_select on public.appointments
  for select to authenticated
  using (
    clinic_id = (select private.current_clinic_id())
    and (
      (select private.current_app_role()) in ('admin', 'receptionist')
      or doctor_id = (select private.current_doctor_id())
    )
  );

create policy appointments_insert on public.appointments
  for insert to authenticated
  with check (
    clinic_id = (select private.current_clinic_id())
    and (select private.current_app_role()) in ('admin', 'receptionist')
  );

create policy appointments_update on public.appointments
  for update to authenticated
  using (
    clinic_id = (select private.current_clinic_id())
    and (select private.current_app_role()) in ('admin', 'receptionist')
  )
  with check (
    clinic_id = (select private.current_clinic_id())
    and (select private.current_app_role()) in ('admin', 'receptionist')
  );

-- ---------------------------------------------------------------------------
-- appointment_events: same visibility as the parent appointment; written by FastAPI only.
-- ---------------------------------------------------------------------------
create policy appointment_events_select on public.appointment_events
  for select to authenticated
  using (
    clinic_id = (select private.current_clinic_id())
    and (
      (select private.current_app_role()) in ('admin', 'receptionist')
      or exists (
        select 1
        from public.appointments a
        where a.id = appointment_events.appointment_id
          and a.doctor_id = (select private.current_doctor_id())
      )
    )
  );

-- ---------------------------------------------------------------------------
-- inbound_booking_requests: reception/admin read only; written by FastAPI only.
-- ---------------------------------------------------------------------------
create policy inbound_booking_requests_select on public.inbound_booking_requests
  for select to authenticated
  using (
    clinic_id = (select private.current_clinic_id())
    and (select private.current_app_role()) in ('admin', 'receptionist')
  );
