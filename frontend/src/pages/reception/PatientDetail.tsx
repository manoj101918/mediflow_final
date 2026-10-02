import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeftIcon, CalendarPlusIcon, PencilIcon } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { toast } from 'sonner'

import { SourceBadge, StatusBadge } from '@/components/appointments/Badges'
import { useNewAppointment } from '@/components/appointments/newAppointmentContext'
import { PatientForm } from '@/components/patients/PatientForm'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ApiError } from '@/lib/api'
import { formatDate, formatPatientMeta, formatPhone, formatTime } from '@/lib/format'
import { fetchPatient, patientKeys, updatePatient } from '@/lib/patients'

export function PatientDetailPage() {
  const { patientId = '' } = useParams()
  const queryClient = useQueryClient()
  const { openNewAppointment } = useNewAppointment()
  const [editing, setEditing] = useState(false)

  const query = useQuery({
    queryKey: patientKeys.detail(patientId),
    queryFn: ({ signal }) => fetchPatient(patientId, signal),
  })

  if (query.isPending) {
    return (
      <div className="mx-auto max-w-5xl space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40" />
      </div>
    )
  }
  if (query.isError) {
    const notFound = query.error instanceof ApiError && query.error.status === 404
    return (
      <div className="mx-auto max-w-5xl space-y-3">
        <BackLink />
        <p className="text-muted-foreground">{notFound ? 'This patient does not exist.' : query.error.message}</p>
      </div>
    )
  }

  const p = query.data
  const facts: [string, string | null][] = [
    ['Phone', formatPhone(p.phone)],
    ['Alternate phone', formatPhone(p.alternate_phone)],
    ['Gender · age', formatPatientMeta(p.gender, p.age)],
    ['Date of birth', p.date_of_birth ? formatDate(p.date_of_birth) : null],
    ['Address', p.address],
    ['Registered', formatDate(p.created_at)],
  ]

  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <BackLink />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{p.full_name}</h1>
          <p className="text-sm text-muted-foreground">
            {[formatPatientMeta(p.gender, p.age), formatPhone(p.phone)].filter(Boolean).join(' · ')}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setEditing(true)}>
            <PencilIcon /> Edit
          </Button>
          <Button onClick={() => openNewAppointment({ patient: p })}>
            <CalendarPlusIcon /> Book appointment
          </Button>
        </div>
      </div>

      <Card>
        <CardContent>
          <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
            {facts.map(([label, value]) => (
              <div key={label}>
                <dt className="text-xs text-muted-foreground">{label}</dt>
                <dd className="text-sm">{value || '—'}</dd>
              </div>
            ))}
          </dl>
          {p.notes && (
            <div className="mt-4 rounded-lg bg-amber-50 p-3 text-sm dark:bg-amber-500/10">
              <div className="text-xs font-medium text-amber-900 dark:text-amber-200">Notes</div>
              <p className="whitespace-pre-wrap">{p.notes}</p>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Visits ({p.appointments.length})</CardTitle>
        </CardHeader>
        <CardContent className="px-0">
          {p.appointments.length === 0 ? (
            <p className="px-4 text-sm text-muted-foreground">No appointments yet.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-4">Date</TableHead>
                  <TableHead>Time</TableHead>
                  <TableHead className="text-center">Token</TableHead>
                  <TableHead>Doctor</TableHead>
                  <TableHead className="hidden md:table-cell">Reason</TableHead>
                  <TableHead className="hidden sm:table-cell">Source</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {p.appointments.map((a) => (
                  <TableRow key={a.id}>
                    <TableCell className="pl-4 whitespace-nowrap">{formatDate(a.appointment_date)}</TableCell>
                    <TableCell className="tabular-nums">{formatTime(a.starts_at)}</TableCell>
                    <TableCell className="text-center tabular-nums">{a.token_number}</TableCell>
                    <TableCell>{a.doctor_name}</TableCell>
                    <TableCell className="hidden max-w-60 truncate md:table-cell">{a.reason_for_visit ?? '—'}</TableCell>
                    <TableCell className="hidden sm:table-cell">
                      <SourceBadge source={a.source} />
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={a.status} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog open={editing} onOpenChange={setEditing}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Edit {p.full_name}</DialogTitle>
          </DialogHeader>
          <PatientForm
            patient={p}
            submitLabel="Save changes"
            onCancel={() => setEditing(false)}
            onSubmit={async (changes) => {
              await updatePatient(p.id, changes)
              await queryClient.invalidateQueries({ queryKey: patientKeys.all })
              toast.success('Patient updated')
              setEditing(false)
            }}
          />
        </DialogContent>
      </Dialog>
    </div>
  )
}

function BackLink() {
  return (
    <Button variant="ghost" size="sm" className="-ml-2" asChild>
      <Link to="/reception/patients">
        <ArrowLeftIcon /> Patients
      </Link>
    </Button>
  )
}
