import { createClient } from '@supabase/supabase-js'

import { env } from '@/lib/env'
import type { Database } from '@/types/database'

// Used only for auth and Realtime. All data reads/writes go through the FastAPI backend (lib/api.ts).
export const supabase = createClient<Database>(env.supabaseUrl, env.supabasePublishableKey, {
  auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false },
})
