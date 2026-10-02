-- Phase 3 RLS and Realtime. Every lab table has RLS on and no client grants, except the two
-- status-level tables that Realtime broadcasts:
--   lab_orders           doctors and lab staff of the clinic (reception is excluded because the
--                        row carries the doctor's clinical note; it gets counts from FastAPI)
--   lab_critical_alerts  only the doctor the alert is for
-- Result values (lab_results) are never readable by clients and never broadcast; screens
-- refetch them from FastAPI when a status row changes.

alter table public.lab_orders enable row level security;
alter table public.lab_samples enable row level security;
alter table public.lab_order_items enable row level security;
alter table public.lab_results enable row level security;
alter table public.lab_critical_alerts enable row level security;
alter table public.lab_order_events enable row level security;

revoke all on
  public.lab_orders, public.lab_samples, public.lab_order_items, public.lab_results,
  public.lab_critical_alerts, public.lab_order_events
from anon, authenticated;

grant select on public.lab_orders, public.lab_critical_alerts to authenticated;

create policy lab_orders_select on public.lab_orders
  for select to authenticated
  using (
    clinic_id = (select private.current_clinic_id())
    and (select private.current_app_role()) in ('doctor', 'lab_technician', 'lab_supervisor')
  );

create policy lab_critical_alerts_select on public.lab_critical_alerts
  for select to authenticated
  using (
    clinic_id = (select private.current_clinic_id())
    and doctor_id = (select private.current_doctor_id())
  );

alter publication supabase_realtime add table public.lab_orders, public.lab_critical_alerts;
