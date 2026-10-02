import type { RealtimePostgresChangesPayload } from '@supabase/supabase-js'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'

import { useAuth } from '@/auth/context'
import { appointmentKeys } from '@/lib/appointments'
import { supabase } from '@/lib/supabase'
import type { Database } from '@/types/database'

type AppointmentRow = Database['public']['Tables']['appointments']['Row']
export type AppointmentChange = RealtimePostgresChangesPayload<AppointmentRow>

/**
 * Live updates for the clinic's appointments via Supabase Realtime.
 *
 * Rows arrive only if RLS lets this user see them (doctors: their own). Every change refetches
 * appointment queries; `onInsertByOthers` fires for bookings made by someone else.
 */
export function useRealtimeAppointments(onInsertByOthers?: (row: AppointmentRow) => void) {
  const { me, session } = useAuth()
  const queryClient = useQueryClient()
  const token = session?.access_token
  const clinicId = me?.clinic.id
  const userId = me?.id

  // Keep the latest callback without resubscribing on every render.
  const callbackRef = useRef(onInsertByOthers)
  useEffect(() => {
    callbackRef.current = onInsertByOthers
  }, [onInsertByOthers])

  useEffect(() => {
    if (!token || !clinicId) return
    let cancelled = false
    const channel = supabase.channel(`appointments:${clinicId}:${crypto.randomUUID()}`)

    void (async () => {
      // RLS on the realtime stream is evaluated with this JWT.
      await supabase.realtime.setAuth(token)
      if (cancelled) return
      channel
        .on(
          'postgres_changes',
          {
            event: '*',
            schema: 'public',
            table: 'appointments',
            filter: `clinic_id=eq.${clinicId}`,
          },
          (payload: AppointmentChange) => {
            void queryClient.invalidateQueries({ queryKey: appointmentKeys.all })
            if (payload.eventType === 'INSERT' && payload.new.created_by !== userId) {
              callbackRef.current?.(payload.new)
            }
          },
        )
        .subscribe()
    })()

    return () => {
      cancelled = true
      void supabase.removeChannel(channel)
    }
  }, [token, clinicId, userId, queryClient])
}
