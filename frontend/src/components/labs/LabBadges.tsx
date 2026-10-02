import { AlertTriangleIcon } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import {
  LAB_FLAG_LABEL,
  LAB_FLAG_MARK,
  LAB_ITEM_STATUS_LABEL,
  LAB_ORDER_STATUS_LABEL,
  LAB_PRIORITY_LABEL,
  flagTone,
  isCritical,
} from '@/lib/labs'
import { cn } from '@/lib/utils'
import type { LabFlag, LabItemStatus, LabOrderStatus, LabPriority, LabStatusCounts } from '@/types/api'

const ITEM_TONE: Record<LabItemStatus, string> = {
  ordered: 'bg-slate-100 text-slate-800 dark:bg-slate-500/20 dark:text-slate-200',
  sample_collected: 'bg-sky-100 text-sky-900 dark:bg-sky-500/20 dark:text-sky-200',
  sample_rejected: 'bg-orange-100 text-orange-900 dark:bg-orange-500/20 dark:text-orange-200',
  result_entered: 'bg-violet-100 text-violet-900 dark:bg-violet-500/20 dark:text-violet-200',
  verified: 'bg-violet-100 text-violet-900 dark:bg-violet-500/20 dark:text-violet-200',
  released: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-500/20 dark:text-emerald-200',
  cancelled: 'bg-muted text-muted-foreground line-through',
}

export function LabItemStatusBadge({ status }: { status: LabItemStatus }) {
  return (
    <Badge className={ITEM_TONE[status]} data-lab-status={status}>
      {LAB_ITEM_STATUS_LABEL[status]}
    </Badge>
  )
}

const ORDER_TONE: Record<LabOrderStatus, string> = {
  ordered: ITEM_TONE.ordered,
  in_progress: ITEM_TONE.sample_collected,
  partially_released: 'bg-teal-100 text-teal-900 dark:bg-teal-500/20 dark:text-teal-200',
  released: ITEM_TONE.released,
  cancelled: ITEM_TONE.cancelled,
}

export function LabOrderStatusBadge({ status }: { status: LabOrderStatus }) {
  return (
    <Badge className={ORDER_TONE[status]} data-lab-order-status={status}>
      {LAB_ORDER_STATUS_LABEL[status]}
    </Badge>
  )
}

const PRIORITY_TONE: Record<LabPriority, string> = {
  routine: 'bg-muted text-muted-foreground',
  urgent: 'bg-amber-100 text-amber-900 dark:bg-amber-500/20 dark:text-amber-200',
  stat: 'bg-red-600 text-white dark:bg-red-500',
}

export function LabPriorityBadge({ priority, hideRoutine }: { priority: LabPriority; hideRoutine?: boolean }) {
  if (hideRoutine && priority === 'routine') return null
  return (
    <Badge className={PRIORITY_TONE[priority]} data-lab-priority={priority}>
      {LAB_PRIORITY_LABEL[priority]}
    </Badge>
  )
}

/** A value with its flag: colour plus the H/L/HH/LL mark and a readable title. */
export function FlaggedValue({ value, flag, className }: { value: string; flag: LabFlag | null; className?: string }) {
  return (
    <span
      className={cn('tabular-nums', flagTone(flag), className)}
      title={flag ? LAB_FLAG_LABEL[flag] : undefined}
      data-flag={flag ?? ''}
    >
      {isCritical(flag) && <AlertTriangleIcon className="mr-0.5 inline size-3.5 align-[-2px]" aria-hidden />}
      {value}
      {flag && LAB_FLAG_MARK[flag] && <span className="ml-1 text-xs">{LAB_FLAG_MARK[flag]}</span>}
      {flag && flag !== 'normal' && <span className="sr-only"> ({LAB_FLAG_LABEL[flag]})</span>}
    </span>
  )
}

/** "2 tests pending" / "Results ready" for queue rows (counts only, never values). */
export function LabCountsBadge({ counts }: { counts: LabStatusCounts | undefined }) {
  if (!counts || (counts.pending === 0 && counts.ready === 0)) return null
  if (counts.pending === 0) {
    return (
      <Badge className={ITEM_TONE.released} data-lab-badge="ready">
        Results ready
      </Badge>
    )
  }
  return (
    <Badge className={ITEM_TONE.sample_collected} data-lab-badge="pending">
      {counts.pending} test{counts.pending === 1 ? '' : 's'} pending
      {counts.ready > 0 && ` · ${counts.ready} ready`}
    </Badge>
  )
}
