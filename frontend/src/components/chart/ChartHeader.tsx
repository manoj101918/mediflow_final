import { AlertTriangleIcon, DropletIcon, PencilIcon } from 'lucide-react'
import { useState } from 'react'

import { StatusBadge } from '@/components/appointments/Badges'
import { MedicalProfileDialog } from '@/components/chart/MedicalProfileDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { clinicDate, formatDate, formatPatientMeta, formatTime } from '@/lib/format'
import type { Chart } from '@/types/api'

export function ChartHeader({ chart }: { chart: Chart }) {
  const [editing, setEditing] = useState(false)
  const { profile, appointment } = chart

  return (
    <header className="rounded-xl border bg-background p-4" data-patient-id={chart.patient_id}>
      <div className="flex flex-wrap items-start gap-4">
        {appointment && (
          <div
            className="flex size-14 shrink-0 flex-col items-center justify-center rounded-lg bg-muted"
            aria-label={`Token ${appointment.token_number}`}
          >
            <span className="text-[10px] uppercase text-muted-foreground">Token</span>
            <span className="text-xl font-semibold tabular-nums">{appointment.token_number}</span>
          </div>
        )}
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <h1 className="text-xl font-semibold tracking-tight">{chart.full_name}</h1>
            <span className="text-sm text-muted-foreground">
              {formatPatientMeta(chart.gender, chart.age) || 'Age and sex not recorded'}
            </span>
            {profile.blood_group && (
              <span className="inline-flex items-center gap-1 text-sm text-muted-foreground">
                <DropletIcon className="size-3.5 text-rose-600" />
                {profile.blood_group}
              </span>
            )}
            {appointment && <StatusBadge status={appointment.status} />}
          </div>
          <p className="text-sm text-muted-foreground">
            {chart.visit_count} previous visit{chart.visit_count === 1 ? '' : 's'}
            {chart.last_visit && <> · last on {formatDate(chart.last_visit)}</>}
            {appointment && (
              <>
                {' '}
                · {appointment.appointment_date === clinicDate() ? 'today' : formatDate(appointment.appointment_date)}{' '}
                {formatTime(appointment.starts_at)} with {appointment.doctor_name}
                {appointment.reason_for_visit && <> · {appointment.reason_for_visit}</>}
              </>
            )}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
          <PencilIcon />
          Allergies &amp; conditions
        </Button>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5" data-testid="allergies">
        {profile.allergies.length > 0 ? (
          profile.allergies.map((allergy) => (
            <Badge
              key={allergy}
              className="gap-1 bg-red-600 text-white dark:bg-red-500"
              data-allergy={allergy}
            >
              <AlertTriangleIcon className="size-3" />
              {allergy}
            </Badge>
          ))
        ) : (
          <span className="text-xs text-muted-foreground">No known allergies recorded</span>
        )}
        {profile.chronic_conditions.map((condition) => (
          <Badge key={condition} variant="outline">
            {condition}
          </Badge>
        ))}
      </div>

      {editing && (
        <MedicalProfileDialog
          patientId={chart.patient_id}
          profile={profile}
          open={editing}
          onOpenChange={setEditing}
        />
      )}
    </header>
  )
}
