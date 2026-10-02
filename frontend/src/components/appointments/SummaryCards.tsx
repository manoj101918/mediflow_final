import type { LucideIcon } from 'lucide-react'
import {
  CalendarCheckIcon,
  CheckCircle2Icon,
  HourglassIcon,
  StethoscopeIcon,
  UserXIcon,
} from 'lucide-react'

import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { Appointment, AppointmentStatus } from '@/types/api'

interface Tile {
  label: string
  icon: LucideIcon
  statuses: AppointmentStatus[]
  tone: string
}

const TILES: Tile[] = [
  {
    label: 'Booked',
    icon: CalendarCheckIcon,
    statuses: ['pending_confirmation', 'scheduled', 'checked_in', 'in_consultation', 'completed'],
    tone: 'text-foreground',
  },
  { label: 'Waiting', icon: HourglassIcon, statuses: ['checked_in'], tone: 'text-sky-700 dark:text-sky-300' },
  {
    label: 'With doctor',
    icon: StethoscopeIcon,
    statuses: ['in_consultation'],
    tone: 'text-violet-700 dark:text-violet-300',
  },
  {
    label: 'Completed',
    icon: CheckCircle2Icon,
    statuses: ['completed'],
    tone: 'text-emerald-700 dark:text-emerald-300',
  },
  {
    label: 'No-show / cancelled',
    icon: UserXIcon,
    statuses: ['no_show', 'cancelled'],
    tone: 'text-muted-foreground',
  },
]

export function SummaryCards({ appointments }: { appointments: Appointment[] | undefined }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      {TILES.map(({ label, icon: Icon, statuses, tone }) => {
        const count = appointments?.filter((a) => statuses.includes(a.status)).length
        return (
          <Card key={label} size="sm" className="gap-1 px-4">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Icon className="size-3.5" />
              {label}
            </div>
            <div className={cn('text-2xl font-semibold tabular-nums', tone)}>
              {count ?? <span className="text-muted-foreground">–</span>}
            </div>
          </Card>
        )
      })}
    </div>
  )
}
