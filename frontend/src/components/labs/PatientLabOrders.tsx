import { useQuery } from '@tanstack/react-query'

import { LabItemStatusBadge, LabOrderStatusBadge, LabPriorityBadge } from '@/components/labs/LabBadges'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDate } from '@/lib/format'
import { fetchPatientLabOrders, labKeys } from '@/lib/labs'

/** Front desk: a patient's lab orders with test statuses (never result values). */
export function PatientLabOrders({ patientId }: { patientId: string }) {
  const orders = useQuery({
    queryKey: labKeys.patientOrders(patientId),
    queryFn: ({ signal }) => fetchPatientLabOrders(patientId, signal),
    refetchInterval: 30_000,
  })
  if (orders.isPending) return <Skeleton className="h-16" />
  if (orders.isError) return <p className="text-sm text-destructive">{orders.error.message}</p>
  if (orders.data.length === 0) return <p className="text-sm text-muted-foreground">No lab tests ordered.</p>
  return (
    <ul className="divide-y" data-testid="patient-lab-orders">
      {orders.data.map((o) => (
        <li key={o.id} className="space-y-1 py-2 first:pt-0 last:pb-0" data-lab-order-id={o.id}>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-mono text-xs">{o.order_number}</span>
            <span className="text-muted-foreground">
              {formatDate(o.created_at)} · {o.ordering_doctor_name}
            </span>
            <LabPriorityBadge priority={o.priority} hideRoutine />
            <LabOrderStatusBadge status={o.status} />
          </div>
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-sm">
            {o.tests.map((t, i) => (
              <span key={i} className="inline-flex items-center gap-1.5">
                {t.test_name}
                <LabItemStatusBadge status={t.status} />
              </span>
            ))}
          </div>
        </li>
      ))}
    </ul>
  )
}
