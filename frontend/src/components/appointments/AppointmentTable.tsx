import type { ReactNode } from 'react'

import { SourceBadge, StatusBadge } from '@/components/appointments/Badges'
import { RowActions } from '@/components/appointments/RowActions'
import { ViewChatButton } from '@/components/bot/ViewChatButton'
import { LabCountsBadge } from '@/components/labs/LabBadges'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { isLive } from '@/lib/appointments'
import { formatDate, formatPatientMeta, formatPhone, formatTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { Appointment, LabStatusCounts } from '@/types/api'

interface AppointmentTableProps {
  appointments: Appointment[]
  loading?: boolean
  empty: ReactNode
  /** Show the date column (multi-day lists). */
  showDate?: boolean
  /** Hide the actions column (read-only views). */
  readOnly?: boolean
  /** Lab test counts per appointment (statuses only, never values). */
  labCounts?: Map<string, LabStatusCounts>
}

export function AppointmentTable({
  appointments,
  loading,
  empty,
  showDate,
  readOnly,
  labCounts,
}: AppointmentTableProps) {
  const columns = 7 + (showDate ? 1 : 0) + (readOnly ? 0 : 1)

  return (
    <div className="overflow-hidden rounded-xl border bg-background">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/50 hover:bg-muted/50">
            <TableHead className="w-14 text-center">Token</TableHead>
            {showDate && <TableHead>Date</TableHead>}
            <TableHead className="w-24">Time</TableHead>
            <TableHead>Patient</TableHead>
            <TableHead className="hidden md:table-cell">Doctor</TableHead>
            <TableHead className="hidden lg:table-cell">Reason</TableHead>
            <TableHead className="hidden sm:table-cell">Source</TableHead>
            <TableHead>Status</TableHead>
            {!readOnly && <TableHead className="text-right">Actions</TableHead>}
          </TableRow>
        </TableHeader>
        <TableBody>
          {loading ? (
            Array.from({ length: 6 }, (_, i) => (
              <TableRow key={i}>
                <TableCell colSpan={columns}>
                  <Skeleton className="h-8 w-full" />
                </TableCell>
              </TableRow>
            ))
          ) : appointments.length === 0 ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={columns} className="py-12 text-center text-muted-foreground">
                {empty}
              </TableCell>
            </TableRow>
          ) : (
            appointments.map((a) => (
              <TableRow
                key={a.id}
                data-appointment-id={a.id}
                data-status={a.status}
                className={cn(!isLive(a.status) && 'text-muted-foreground')}
              >
                <TableCell className="text-center text-base font-semibold tabular-nums">
                  {a.token_number}
                </TableCell>
                {showDate && <TableCell className="whitespace-nowrap">{formatDate(a.starts_at)}</TableCell>}
                <TableCell className="whitespace-nowrap tabular-nums">{formatTime(a.starts_at)}</TableCell>
                <TableCell>
                  <div className="font-medium text-foreground">{a.patient.full_name}</div>
                  <div className="text-xs text-muted-foreground">
                    {[formatPatientMeta(a.patient.gender, a.patient.age), formatPhone(a.patient.phone)]
                      .filter(Boolean)
                      .join(' · ')}
                  </div>
                </TableCell>
                <TableCell className="hidden md:table-cell">{a.doctor.full_name}</TableCell>
                <TableCell className="hidden max-w-56 truncate lg:table-cell" title={a.reason_for_visit ?? ''}>
                  {a.reason_for_visit ?? <span className="text-muted-foreground">—</span>}
                </TableCell>
                <TableCell className="hidden sm:table-cell">
                  <div className="flex flex-col items-start gap-0.5">
                    <SourceBadge source={a.source} />
                    <ViewChatButton appointment={a} />
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap items-center gap-1">
                    <StatusBadge status={a.status} />
                    <LabCountsBadge counts={labCounts?.get(a.id)} />
                  </div>
                </TableCell>
                {!readOnly && (
                  <TableCell className="text-right">
                    <RowActions appointment={a} />
                  </TableCell>
                )}
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  )
}
