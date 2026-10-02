import type { RealtimePostgresChangesPayload } from '@supabase/supabase-js'
import { type QueryKey, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'

import { useAuth } from '@/auth/context'
import { supabase } from '@/lib/supabase'
import type { Database } from '@/types/database'

export type LabOrderRow = Database['public']['Tables']['lab_orders']['Row']
export type LabAlertRow = Database['public']['Tables']['lab_critical_alerts']['Row']

/** Every query that shows lab orders, statuses or results (values are refetched, never pushed). */
function isLabQuery(key: QueryKey): boolean {
  const [root, second, third, fourth] = key
  if (root === 'labs') return true
  if (root === 'appointments' && second === 'lab-summary') return true
  if (root === 'patients' && third === 'lab-orders') return true
  return root === 'patient-records' && (third === 'labs' || third === 'lab-trends' || fourth === 'labs')
}

function useChannel<Row extends Record<string, unknown>>(
  table: 'lab_orders' | 'lab_critical_alerts',
  onChange: (change: RealtimePostgresChangesPayload<Row>) => void,
) {
  const { me, session } = useAuth()
  const token = session?.access_token
  const clinicId = me?.clinic.id
  const handler = useRef(onChange)
  useEffect(() => {
    handler.current = onChange
  }, [onChange])

  useEffect(() => {
    if (!token || !clinicId) return
    let cancelled = false
    const channel = supabase.channel(`${table}:${clinicId}:${crypto.randomUUID()}`)
    void (async () => {
      // RLS decides which rows arrive: lab_orders for doctors and lab staff of the clinic,
      // alerts only for the doctor they belong to.
      await supabase.realtime.setAuth(token)
      if (cancelled) return
      channel
        .on(
          'postgres_changes',
          { event: '*', schema: 'public', table, filter: `clinic_id=eq.${clinicId}` },
          (payload: RealtimePostgresChangesPayload<Row>) => handler.current(payload),
        )
        .subscribe()
    })()
    return () => {
      cancelled = true
      void supabase.removeChannel(channel)
    }
  }, [token, clinicId, table])
}

/** Live lab order status for doctors and lab staff: refetches every lab view on any change. */
export function useRealtimeLabOrders(onChange?: (change: RealtimePostgresChangesPayload<LabOrderRow>) => void) {
  const queryClient = useQueryClient()
  useChannel<LabOrderRow>('lab_orders', (change) => {
    void queryClient.invalidateQueries({ predicate: (q) => isLabQuery(q.queryKey) })
    onChange?.(change)
  })
}

/** New critical-value alerts for the signed-in doctor. */
export function useRealtimeLabAlerts(onInsert?: (row: LabAlertRow) => void) {
  const queryClient = useQueryClient()
  useChannel<LabAlertRow>('lab_critical_alerts', (change) => {
    void queryClient.invalidateQueries({ queryKey: ['labs', 'alerts'] })
    if (change.eventType === 'INSERT') onInsert?.(change.new)
  })
}
