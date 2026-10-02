-- Lab rows reference catalog and doctor rows without cascading (history must survive; tests and
-- parameters are deactivated, never deleted). When a whole clinic is deleted, its cascade can
-- reach lab_tests/doctors before the lab rows that reference them, so these checks run at
-- commit instead of mid-cascade. They still reject a direct delete of a referenced row.
alter table public.lab_order_items
  alter constraint lab_order_items_test_id_fkey deferrable initially deferred;
alter table public.lab_results
  alter constraint lab_results_parameter_id_fkey deferrable initially deferred;
alter table public.lab_orders
  alter constraint lab_orders_ordering_doctor_id_fkey deferrable initially deferred;
alter table public.lab_critical_alerts
  alter constraint lab_critical_alerts_doctor_id_fkey deferrable initially deferred;
