import { useQuery } from '@tanstack/react-query'

import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatDate } from '@/lib/format'
import { TIMING_LABEL, fetchMedications, recordKeys } from '@/lib/records'
import { cn } from '@/lib/utils'

export function MedicationsTab({ patientId }: { patientId: string }) {
  const meds = useQuery({
    queryKey: recordKeys.medications(patientId),
    queryFn: ({ signal }) => fetchMedications(patientId, signal),
  })
  if (meds.isPending) return <Skeleton className="h-48" />
  if (meds.isError) return <p className="text-sm text-destructive">{meds.error.message}</p>
  if (meds.data.length === 0) {
    return <p className="rounded-xl border bg-background p-6 text-sm text-muted-foreground">No medicines prescribed yet.</p>
  }
  // Current courses first, then newest visit first (the API already sorts by visit).
  const rows = [...meds.data].sort((a, b) => Number(b.current) - Number(a.current))

  return (
    <div className="rounded-xl border bg-background">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Medicine</TableHead>
            <TableHead>Dosage</TableHead>
            <TableHead>Prescribed</TableHead>
            <TableHead>Until</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((m) => (
            <TableRow
              key={m.item.id}
              className={cn(m.current && 'bg-emerald-50/70 dark:bg-emerald-500/10')}
              data-current={m.current}
            >
              <TableCell>
                <div className="flex items-center gap-2 font-medium">
                  {m.item.medicine_name}
                  {m.current && (
                    <Badge className="bg-emerald-600 text-white dark:bg-emerald-500">Current</Badge>
                  )}
                </div>
                <div className="text-xs text-muted-foreground">
                  {[m.item.strength, m.item.dosage_form].filter(Boolean).join(' ')}
                </div>
              </TableCell>
              <TableCell className="text-sm">
                {[m.item.frequency, m.item.timing ? TIMING_LABEL[m.item.timing] : null, m.item.duration_days ? `${m.item.duration_days} days` : null]
                  .filter(Boolean)
                  .join(' · ')}
                {m.item.instructions && (
                  <div className="text-xs text-muted-foreground">{m.item.instructions}</div>
                )}
              </TableCell>
              <TableCell className="text-sm">
                {formatDate(m.visit_date)}
                <div className="text-xs text-muted-foreground">{m.doctor_name}</div>
              </TableCell>
              <TableCell className="text-sm tabular-nums">
                {m.end_date ? formatDate(m.end_date) : '—'}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
