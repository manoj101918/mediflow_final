-- MediFlow development seed data.
-- Run via Supabase MCP `execute_sql` BEFORE `backend/scripts/seed_users.py`
-- (the script creates auth users + profiles and links doctor logins).
-- Idempotent: fixed/deterministic ids + ON CONFLICT DO NOTHING.
-- Appointment dates are relative to "today" in IST at the time the seed runs.

begin;

-- ---------------------------------------------------------------------------
-- Clinic
-- ---------------------------------------------------------------------------
insert into public.clinics (id, name, phone, address, timezone)
values (
  '11111111-1111-4111-8111-111111111111',
  'MediFlow Family Clinic',
  '+914023456789',
  '12-2-45, Road No. 3, Banjara Hills, Hyderabad, Telangana 500034',
  'Asia/Kolkata'
)
on conflict (id) do nothing;

-- ---------------------------------------------------------------------------
-- Doctors (profile_id linked later by seed_users.py)
-- ---------------------------------------------------------------------------
insert into public.doctors (id, clinic_id, full_name, specialization, consultation_fee, default_slot_minutes)
values
  ('d0c00000-0000-4000-8000-000000000001', '11111111-1111-4111-8111-111111111111',
   'Dr. Anil Sharma', 'General Physician', 400, 15),
  ('d0c00000-0000-4000-8000-000000000002', '11111111-1111-4111-8111-111111111111',
   'Dr. Lakshmi Iyer', 'Pediatrician', 500, 15),
  ('d0c00000-0000-4000-8000-000000000003', '11111111-1111-4111-8111-111111111111',
   'Dr. Imran Khan', 'Orthopedics', 700, 20)
on conflict (id) do nothing;

-- ---------------------------------------------------------------------------
-- Weekly schedules: morning + evening shifts, Monday (0) to Saturday (5)
-- ---------------------------------------------------------------------------
insert into public.doctor_schedules (id, clinic_id, doctor_id, weekday, start_time, end_time)
select
  md5('mediflow-schedule-' || s.doctor_id::text || '-' || wd || '-' || s.start_time::text)::uuid,
  '11111111-1111-4111-8111-111111111111',
  s.doctor_id,
  wd,
  s.start_time,
  s.end_time
from (
  values
    ('d0c00000-0000-4000-8000-000000000001'::uuid, time '09:00', time '13:00'),
    ('d0c00000-0000-4000-8000-000000000001'::uuid, time '17:00', time '20:00'),
    ('d0c00000-0000-4000-8000-000000000002'::uuid, time '10:00', time '13:30'),
    ('d0c00000-0000-4000-8000-000000000002'::uuid, time '17:30', time '20:00'),
    ('d0c00000-0000-4000-8000-000000000003'::uuid, time '09:30', time '12:30'),
    ('d0c00000-0000-4000-8000-000000000003'::uuid, time '16:00', time '19:00')
) as s (doctor_id, start_time, end_time)
cross join generate_series(0, 5) as wd
on conflict (id) do nothing;

-- Dr. Iyer is on leave 5 days from today.
insert into public.doctor_leaves (id, clinic_id, doctor_id, leave_date, reason)
values (
  'eeee0000-0000-4000-8000-000000000001',
  '11111111-1111-4111-8111-111111111111',
  'd0c00000-0000-4000-8000-000000000002',
  (now() at time zone 'Asia/Kolkata')::date + 5,
  'Conference'
)
on conflict do nothing;

-- ---------------------------------------------------------------------------
-- Patients (~30). Patients 1/2 and 11/12 share a family phone number.
-- ---------------------------------------------------------------------------
insert into public.patients (
  id, clinic_id, full_name, phone, alternate_phone, gender, date_of_birth, age_years, address
)
select
  md5('mediflow-patient-' || p.n)::uuid,
  '11111111-1111-4111-8111-111111111111',
  p.full_name,
  p.phone,
  p.alternate_phone,
  p.gender::public.gender,
  p.dob,
  p.age_years,
  p.address
from (
  values
    (1,  'Ravi Kumar',          '+919848012345', null,            'male',   date '1984-03-12', null::smallint, 'Ameerpet, Hyderabad'),
    (2,  'Sunita Kumar',        '+919848012345', null,            'female', date '1987-07-21', null, 'Ameerpet, Hyderabad'),
    (3,  'Priya Reddy',         '+919912345670', null,            'female', date '1995-11-02', null, 'Kukatpally, Hyderabad'),
    (4,  'Mohammed Ali',        '+919700011122', '+919700011123', 'male',   null,              52,   'Tolichowki, Hyderabad'),
    (5,  'Lakshmi Narayanan',   '+919845098450', null,            'female', date '1960-01-15', null, 'Begumpet, Hyderabad'),
    (6,  'Arjun Mehta',         '+919820034567', null,            'male',   date '2001-09-30', null, 'Madhapur, Hyderabad'),
    (7,  'Kavya Nair',          '+919447012345', null,            'female', date '2019-05-08', null, 'Gachibowli, Hyderabad'),
    (8,  'Suresh Patel',        '+919825012345', null,            'male',   null,              67,   'Secunderabad'),
    (9,  'Ananya Iyer',         '+919884012345', null,            'female', date '2016-12-19', null, 'Kondapur, Hyderabad'),
    (10, 'Vikram Singh',        '+919810012345', null,            'male',   date '1979-04-04', null, 'Jubilee Hills, Hyderabad'),
    (11, 'Deepa Joshi',         '+919822054321', null,            'female', date '1990-08-25', null, 'Miyapur, Hyderabad'),
    (12, 'Aarav Joshi',         '+919822054321', null,            'male',   date '2018-02-14', null, 'Miyapur, Hyderabad'),
    (13, 'Fatima Begum',        '+919701234567', null,            'female', null,              45,   'Mehdipatnam, Hyderabad'),
    (14, 'Rajesh Gupta',        '+919811198765', null,            'male',   date '1972-06-18', null, 'Dilsukhnagar, Hyderabad'),
    (15, 'Meena Krishnan',      '+919840011223', null,            'female', date '1968-10-10', null, 'Banjara Hills, Hyderabad'),
    (16, 'Sanjay Rao',          '+919866123456', null,            'male',   date '1988-01-01', null, 'Kothapet, Hyderabad'),
    (17, 'Pooja Sharma',        '+919873456789', null,            'female', date '1999-03-03', null, 'Manikonda, Hyderabad'),
    (18, 'Harish Chandra',      '+919849567890', null,            'male',   null,              71,   'Malakpet, Hyderabad'),
    (19, 'Nisha Agarwal',       '+919830012345', null,            'female', date '1993-07-07', null, 'Somajiguda, Hyderabad'),
    (20, 'Karthik Subramanian', '+919841234560', null,            'male',   date '1985-12-12', null, 'HITEC City, Hyderabad'),
    (21, 'Divya Menon',         '+919895012345', null,            'female', date '2010-04-22', null, 'Kompally, Hyderabad'),
    (22, 'Abdul Rahman',        '+919703456789', null,            'male',   date '1958-09-09', null, 'Charminar, Hyderabad'),
    (23, 'Shreya Ghosh',        '+919831098765', null,            'female', date '1997-02-28', null, 'Tarnaka, Hyderabad'),
    (24, 'Manoj Verma',         '+919812345678', null,            'male',   date '1976-11-11', null, 'LB Nagar, Hyderabad'),
    (25, 'Revathi Pillai',      '+919846012345', null,            'female', null,              38,   'Uppal, Hyderabad'),
    (26, 'Gaurav Malhotra',     '+919818765432', null,            'male',   date '1991-05-05', null, 'Nanakramguda, Hyderabad'),
    (27, 'Swati Deshpande',     '+919823456789', null,            'female', date '1982-08-08', null, 'Attapur, Hyderabad'),
    (28, 'Naveen Yadav',        '+919849876543', null,            'male',   date '2005-06-15', null, 'Bowenpally, Hyderabad'),
    (29, 'Zoya Siddiqui',       '+919704567890', null,            'female', date '2021-01-20', null, 'Masab Tank, Hyderabad'),
    (30, 'Prakash Hegde',       '+919845567890', null,            'male',   date '1964-03-30', null, 'Sainikpuri, Hyderabad')
) as p (n, full_name, phone, alternate_phone, gender, dob, age_years, address)
on conflict (id) do nothing;

-- ---------------------------------------------------------------------------
-- Appointments (~20) across today and the next few days. Tokens are sequential
-- per doctor per day in time order. Bot-sourced rows carry an external_ref.
-- ---------------------------------------------------------------------------
with t as (
  select (now() at time zone 'Asia/Kolkata')::date as today
),
raw (n, patient_n, doctor_id, day_offset, start_time, status, source, reason) as (
  values
    -- today: Dr. Sharma
    (1,  1,  'd0c00000-0000-4000-8000-000000000001'::uuid, 0, time '09:00', 'completed',            'walk_in',  'Fever and body ache'),
    (2,  4,  'd0c00000-0000-4000-8000-000000000001'::uuid, 0, time '09:15', 'completed',            'phone',    'Blood pressure follow-up'),
    (3,  10, 'd0c00000-0000-4000-8000-000000000001'::uuid, 0, time '09:30', 'no_show',              'phone',    'Diabetes review'),
    (4,  14, 'd0c00000-0000-4000-8000-000000000001'::uuid, 0, time '10:00', 'in_consultation',      'walk_in',  'Persistent cough'),
    (5,  16, 'd0c00000-0000-4000-8000-000000000001'::uuid, 0, time '10:15', 'checked_in',           'manual',   'Headache'),
    (6,  19, 'd0c00000-0000-4000-8000-000000000001'::uuid, 0, time '17:00', 'scheduled',            'phone',    'Thyroid report review'),
    (7,  24, 'd0c00000-0000-4000-8000-000000000001'::uuid, 0, time '17:30', 'pending_confirmation', 'whatsapp', 'Stomach pain'),
    -- today: Dr. Iyer
    (8,  7,  'd0c00000-0000-4000-8000-000000000002'::uuid, 0, time '10:00', 'completed',            'walk_in',  'Vaccination'),
    (9,  9,  'd0c00000-0000-4000-8000-000000000002'::uuid, 0, time '10:30', 'checked_in',           'phone',    'Cold and runny nose'),
    (10, 12, 'd0c00000-0000-4000-8000-000000000002'::uuid, 0, time '11:00', 'cancelled',            'phone',    'Growth check-up'),
    (11, 29, 'd0c00000-0000-4000-8000-000000000002'::uuid, 0, time '17:30', 'pending_confirmation', 'voice',    'Ear pain'),
    -- today: Dr. Khan
    (12, 8,  'd0c00000-0000-4000-8000-000000000003'::uuid, 0, time '09:30', 'completed',            'phone',    'Knee pain'),
    (13, 18, 'd0c00000-0000-4000-8000-000000000003'::uuid, 0, time '10:10', 'scheduled',            'manual',   'Lower back pain'),
    (14, 22, 'd0c00000-0000-4000-8000-000000000003'::uuid, 0, time '16:00', 'scheduled',            'walk_in',  'Shoulder stiffness'),
    -- upcoming days
    (15, 3,  'd0c00000-0000-4000-8000-000000000001'::uuid, 1, time '09:00', 'scheduled',            'phone',    'Annual health check'),
    (16, 17, 'd0c00000-0000-4000-8000-000000000001'::uuid, 1, time '09:15', 'scheduled',            'whatsapp', 'Skin rash'),
    (17, 21, 'd0c00000-0000-4000-8000-000000000002'::uuid, 1, time '10:00', 'scheduled',            'manual',   'Asthma follow-up'),
    (18, 26, 'd0c00000-0000-4000-8000-000000000003'::uuid, 2, time '09:30', 'scheduled',            'voice',    'Sports injury'),
    (19, 5,  'd0c00000-0000-4000-8000-000000000001'::uuid, 2, time '17:00', 'scheduled',            'phone',    'Joint pain'),
    (20, 30, 'd0c00000-0000-4000-8000-000000000003'::uuid, 3, time '16:20', 'scheduled',            'phone',    'Post-surgery review')
)
insert into public.appointments (
  id, clinic_id, patient_id, doctor_id, starts_at, ends_at, status, source,
  token_number, reason_for_visit, external_ref
)
select
  md5('mediflow-appt-' || r.n)::uuid,
  '11111111-1111-4111-8111-111111111111',
  md5('mediflow-patient-' || r.patient_n)::uuid,
  r.doctor_id,
  ((t.today + r.day_offset) + r.start_time) at time zone 'Asia/Kolkata',
  ((t.today + r.day_offset) + r.start_time + make_interval(mins => d.default_slot_minutes))
    at time zone 'Asia/Kolkata',
  r.status::public.appointment_status,
  r.source::public.appointment_source,
  row_number() over (partition by r.doctor_id, r.day_offset order by r.start_time)::integer,
  r.reason,
  case when r.source in ('whatsapp', 'voice') then 'seed-' || r.source || '-' || r.n end
from raw r
cross join t
join public.doctors d on d.id = r.doctor_id
on conflict (id) do nothing;

-- One audit event per seeded appointment recording its current status.
insert into public.appointment_events (clinic_id, appointment_id, from_status, to_status, actor_type, channel, note)
select
  a.clinic_id,
  a.id,
  null,
  a.status,
  'system',
  case when a.source in ('whatsapp', 'voice') then a.source::text else 'dashboard' end,
  'Seed data'
from public.appointments a
where a.clinic_id = '11111111-1111-4111-8111-111111111111'
  and not exists (select 1 from public.appointment_events e where e.appointment_id = a.id);

commit;
