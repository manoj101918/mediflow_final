import { LabOrderResults } from '@/components/labs/LabOrderResults'
import { Skeleton } from '@/components/ui/skeleton'
import { usePatientLabResults } from '@/hooks/usePatientLabResults'

/** Every lab order of the patient, newest first, with released values flagged. */
export function LabResultsTab({
  patientId,
  focus,
  onOpenReport,
}: {
  patientId: string
  /** Open this order (and highlight a test of it), e.g. from the inbox or a citation. */
  focus?: { orderId?: string | null; itemId?: string | null; token: number } | null
  onOpenReport: (reportId: string) => void
}) {
  const results = usePatientLabResults(patientId)
  if (results.isPending) return <Skeleton className="h-48" />
  if (results.isError) return <p className="text-sm text-destructive">{results.error.message}</p>
  const orders = results.data
  if (orders.length === 0) {
    return <p className="rounded-xl border bg-background p-6 text-sm text-muted-foreground">No lab tests ordered yet.</p>
  }
  return (
    <ol className="space-y-3">
      {orders.map((order) => {
        const focused = focus && (focus.orderId === order.id || order.items.some((i) => i.id === focus.itemId))
        return (
          <li
            key={order.id}
            className={focused ? 'rounded-xl border bg-background p-3 ring-2 ring-primary' : 'rounded-xl border bg-background p-3'}
          >
            <LabOrderResults
              key={focused ? focus.token : undefined}
              order={order}
              focusItemId={focused ? (focus.itemId ?? null) : null}
              onOpenReport={onOpenReport}
            />
          </li>
        )
      })}
    </ol>
  )
}
