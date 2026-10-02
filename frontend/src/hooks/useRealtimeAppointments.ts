import type { RealtimePostgresChangesPayload } from '@supabase/supabase-js'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'

import { useAuth } from '@/auth/context'
import { appointmentKeys } from '@/lib/appointments'
import { patientKeys } from '@/lib/patients'
import { supabase } from '@/lib/supabase'
import type { Database } from '@/types/database'

export type AppointmentRow = Database['public']['Tables']['appointments']['Row']
export type AppointmentChange = RealtimePostgresChangesPayload<AppointmentRow>

interface RealtimeOptions {
  /** A booking created by someone other than the current user. */
  onInsertByOthers?: (row: AppointmentRow) => void
  /** Every change (insert / update / delete) the user is allowed to see. */
  onChange?: (change: AppointmentChange) => void
}

/**
 * Live updates for the clinic's appointments via Supabase Realtime.
 *
 * Rows arrive only if RLS lets this user see them (doctors: their own). Every change refetches
 * appointment and patient queries, then the optional callbacks run.
 */
export function useRealtimeAppointments(options: RealtimeOptions = {}) {
  const { me, session } = useAuth()
  const queryClient = useQueryClient()
  const token = session?.access_token
  const clinicId = me?.clinic.id
  const userId = me?.id

  // Keep the latest callbacks without resubscribing on every render.
  const optionsRef = useRef(options)
  useEffect(() => {
    optionsRef.current = options
  }, [options])

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
            // Patient pages show visit history.
            void queryClient.invalidateQueries({ queryKey: patientKeys.all })
            const { onInsertByOthers, onChange } = optionsRef.current
            onChange?.(payload)
            if (payload.eventType === 'INSERT' && payload.new.created_by !== userId) {
              onInsertByOthers?.(payload.new)
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
