import { Badge } from '@/components/ui/badge'
import { SOURCE_META, STATUS_META } from '@/lib/appointments'
import { cn } from '@/lib/utils'
import type { AppointmentSource, AppointmentStatus } from '@/types/api'

export function StatusBadge({ status }: { status: AppointmentStatus }) {
  const meta = STATUS_META[status]
  return <Badge className={cn('font-medium', meta.className)}>{meta.label}</Badge>
}

export function SourceBadge({ source }: { source: AppointmentSource }) {
  const { label, icon: Icon } = SOURCE_META[source]
  const bot = source === 'whatsapp' || source === 'voice'
  return (
    <Badge
      variant="outline"
      className={cn(
        'gap-1 font-normal text-muted-foreground',
        bot && 'border-emerald-300 text-emerald-800 dark:border-emerald-700 dark:text-emerald-300',
      )}
    >
      <Icon aria-hidden />
      {label}
    </Badge>
  )
}
