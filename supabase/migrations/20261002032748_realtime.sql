-- Realtime: only appointments are broadcast. Subscribers receive rows their RLS policies allow.
alter publication supabase_realtime add table public.appointments;
