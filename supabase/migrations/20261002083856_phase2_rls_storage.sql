-- Phase 2 security: every clinical / RAG table is backend-only. RLS is enabled with no policies
-- and client roles have no grants, so only FastAPI (database owner / service role) can read or
-- write them. None of these tables are in the realtime publication.

alter table public.patient_medical_profiles enable row level security;
alter table public.consultations enable row level security;
alter table public.consultation_addenda enable row level security;
alter table public.prescriptions enable row level security;
alter table public.prescription_items enable row level security;
alter table public.patient_reports enable row level security;
alter table public.patient_record_chunks enable row level security;
alter table public.ingestion_jobs enable row level security;
alter table public.patient_chat_sessions enable row level security;
alter table public.patient_chat_messages enable row level security;
alter table public.patient_record_access_log enable row level security;

revoke all on table
  public.patient_medical_profiles,
  public.consultations,
  public.consultation_addenda,
  public.prescriptions,
  public.prescription_items,
  public.patient_reports,
  public.patient_record_chunks,
  public.ingestion_jobs,
  public.patient_chat_sessions,
  public.patient_chat_messages,
  public.patient_record_access_log
from anon, authenticated;

revoke all on function private.prevent_finalized_consultation_edit() from public, anon, authenticated;
revoke all on function private.prevent_finalized_prescription_edit() from public, anon, authenticated;

-- ---------------------------------------------------------------------------
-- Storage: private bucket for report files, path {clinic_id}/{patient_id}/{report_id}.{ext}.
-- No storage.objects policies: only the service role (FastAPI) can read or write; the browser
-- only ever gets short-lived signed URLs. file_size_limit must match REPORT_MAX_MB (10 MB).
-- ---------------------------------------------------------------------------
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'patient-reports',
  'patient-reports',
  false,
  10485760,
  array['application/pdf', 'image/jpeg', 'image/png']
)
on conflict (id) do nothing;
