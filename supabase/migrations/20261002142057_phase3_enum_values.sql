-- Phase 3 enum values. ALTER TYPE ... ADD VALUE cannot be used in the transaction that adds
-- it, so these come in their own migration, before anything that uses them.
alter type public.user_role add value if not exists 'lab_technician';
alter type public.user_role add value if not exists 'lab_supervisor';
alter type public.record_source_type add value if not exists 'lab_result';
