-- A generated lab report row is created when results are released (same transaction), and the
-- ingestion job renders and uploads its PDF afterwards. Until then it has no file (size 0).
alter table public.patient_reports drop constraint patient_reports_size_bytes_check;
alter table public.patient_reports add constraint patient_reports_size_bytes_check
  check (size_bytes > 0 or (is_generated and size_bytes = 0));
