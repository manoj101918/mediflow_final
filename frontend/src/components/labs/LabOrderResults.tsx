import { FileTextIcon } from 'lucide-react'
import { useEffect, useRef } from 'react'

import { FlaggedValue, LabItemStatusBadge, LabOrderStatusBadge, LabPriorityBadge } from '@/components/labs/LabBadges'
import { Button } from '@/components/ui/button'
import { formatDate, formatTime } from '@/lib/format'
import { formatResultValue } from '@/lib/labs'
import { cn } from '@/lib/utils'
import type { LabItem, LabOrder } from '@/types/api'

interface Props {
  order: LabOrder
  /** Scroll to and highlight this test (e.g. from a chatbot citation). */
  focusItemId?: string | null
  onOpenReport?: (reportId: string) => void
  compact?: boolean
}

/** A lab order as the doctor sees it: statuses, and released values with flags and ranges. */
export function LabOrderResults({ order, focusItemId, onOpenReport, compact }: Props) {
  return (
    <div className="space-y-2" data-lab-order-id={order.id}>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">{order.order_number}</span>
        <span className="text-muted-foreground">
          {formatDate(order.created_at)}, {formatTime(order.created_at)} · {order.ordering_doctor_name}
        </span>
        <LabPriorityBadge priority={order.priority} hideRoutine />
        <LabOrderStatusBadge status={order.status} />
        {order.report_id && onOpenReport && order.status !== 'ordered' && order.status !== 'in_progress' && (
          <Button variant="outline" size="sm" className="ml-auto" onClick={() => onOpenReport(order.report_id!)}>
            <FileTextIcon />
            PDF report
          </Button>
        )}
      </div>
      {!compact && order.clinical_note && (
        <p className="text-xs text-muted-foreground">Note to lab: {order.clinical_note}</p>
      )}
      <div className="space-y-2">
        {order.items.map((item) => (
          <ItemResults key={item.id} item={item} focused={item.id === focusItemId} />
        ))}
      </div>
    </div>
  )
}

function ItemResults({ item, focused }: { item: LabItem; focused: boolean }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (focused) ref.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [focused])

  return (
    <div
      ref={ref}
      className={cn('rounded-lg border p-2', focused && 'ring-2 ring-primary')}
      data-lab-item-id={item.id}
      data-lab-item-status={item.status}
    >
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">{item.test_name}</span>
        <LabItemStatusBadge status={item.status} />
        {item.released_at && (
          <span className="text-xs text-muted-foreground">
            Reported {formatDate(item.released_at)}, {formatTime(item.released_at)}
          </span>
        )}
      </div>
      {item.results.length > 0 && (
        <table className="mt-2 w-full text-sm">
          <thead className="text-left text-xs text-muted-foreground">
            <tr>
              <th className="py-1 font-normal">Parameter</th>
              <th className="py-1 font-normal">Result</th>
              <th className="py-1 font-normal">Unit</th>
              <th className="hidden py-1 font-normal sm:table-cell">Reference</th>
            </tr>
          </thead>
          <tbody>
            {item.results.map((r) => {
              const older = item.history.filter((h) => h.parameter_id === r.parameter_id)
              return (
                <tr key={r.id} className="border-t align-top" data-parameter={r.parameter_code}>
                  <td className="py-1 pr-2">{r.parameter_name}</td>
                  <td className="py-1 pr-2">
                    <FlaggedValue value={formatResultValue(r)} flag={r.flag} />
                    {r.version > 1 && (
                      <div className="text-xs text-muted-foreground" data-amended>
                        Amended ({r.amended_reason}); was{' '}
                        {older.map((h) => formatResultValue(h)).join(', ') || 'n/a'}
                      </div>
                    )}
                  </td>
                  <td className="py-1 pr-2 text-muted-foreground">{r.unit}</td>
                  <td className="hidden py-1 text-muted-foreground sm:table-cell">{r.range_label}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}
