import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircleIcon,
  CheckCheckIcon,
  CheckIcon,
  CloudIcon,
  Loader2Icon,
  PaperclipIcon,
  PlayIcon,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'

import { ReportUploadDialog } from '@/components/chart/ReportUploadDialog'
import { VisitDetails } from '@/components/chart/VisitDetails'
import { PrescriptionBuilder } from '@/components/chart/PrescriptionBuilder'
import { type ItemDraft, itemFromServer } from '@/lib/prescriptionDraft'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { type SaveState, useAutosave } from '@/hooks/useAutosave'
import { ApiError } from '@/lib/api'
import { appointmentKeys, changeStatus } from '@/lib/appointments'
import { completeVisit, fetchLatestPrescription, fetchVisit, recordKeys, saveVisit } from '@/lib/records'
import type { Consultation, ConsultationInput, Timing, Visit, Vitals } from '@/types/api'

type TextField = 'chief_complaint' | 'history' | 'examination' | 'diagnosis' | 'advice' | 'notes'
type VitalKey = keyof Vitals

const TEXT_FIELDS: { key: TextField; label: string; rows: number }[] = [
  { key: 'chief_complaint', label: 'Chief complaint', rows: 2 },
  { key: 'history', label: 'History', rows: 3 },
  { key: 'examination', label: 'Examination', rows: 3 },
  { key: 'diagnosis', label: 'Diagnosis', rows: 2 },
  { key: 'advice', label: 'Advice', rows: 2 },
  { key: 'notes', label: 'Private notes', rows: 2 },
]

const VITAL_FIELDS: { key: VitalKey; label: string; unit?: string; decimal?: boolean }[] = [
  { key: 'bp_systolic', label: 'BP systolic', unit: 'mmHg' },
  { key: 'bp_diastolic', label: 'BP diastolic', unit: 'mmHg' },
  { key: 'pulse', label: 'Pulse', unit: '/min' },
  { key: 'temperature_c', label: 'Temp', unit: '°C', decimal: true },
  { key: 'spo2', label: 'SpO₂', unit: '%' },
  { key: 'weight_kg', label: 'Weight', unit: 'kg', decimal: true },
  { key: 'height_cm', label: 'Height', unit: 'cm', decimal: true },
  { key: 'blood_sugar', label: 'Blood sugar', unit: 'mg/dL', decimal: true },
]

interface Draft {
  text: Record<TextField, string>
  follow_up_date: string
  vitals: Partial<Record<VitalKey, string>>
  items: ItemDraft[]
}

function draftFrom(consultation: Consultation | null): Draft {
  const text = Object.fromEntries(
    TEXT_FIELDS.map(({ key }) => [key, consultation?.[key] ?? '']),
  ) as Record<TextField, string>
  const vitals: Partial<Record<VitalKey, string>> = {}
  for (const { key } of VITAL_FIELDS) {
    const value = consultation?.vitals[key]
    if (value != null) vitals[key] = String(value)
  }
  return {
    text,
    follow_up_date: consultation?.follow_up_date ?? '',
    vitals,
    items: (consultation?.items ?? []).map(itemFromServer),
  }
}

const orNull = (value: string) => (value.trim() ? value.trim() : null)

function toInput(draft: Draft): ConsultationInput {
  const vitals: Vitals = {}
  for (const { key } of VITAL_FIELDS) {
    const raw = draft.vitals[key]?.trim()
    const value = raw ? Number(raw) : NaN
    if (Number.isFinite(value)) vitals[key] = value
  }
  return {
    ...Object.fromEntries(TEXT_FIELDS.map(({ key }) => [key, orNull(draft.text[key])])),
    follow_up_date: draft.follow_up_date || null,
    vitals,
    items: draft.items
      .filter((item) => item.medicine_name.trim())
      .map((item) => ({
        medicine_name: item.medicine_name.trim(),
        strength: orNull(item.strength),
        dosage_form: orNull(item.dosage_form),
        dose: orNull(item.dose),
        route: orNull(item.route),
        frequency: orNull(item.frequency),
        timing: orNull(item.timing) as Timing | null,
        duration_days: item.duration_days ? Number(item.duration_days) : null,
        instructions: orNull(item.instructions),
      })),
  }
}

function isEmpty(input: ConsultationInput): boolean {
  const { vitals, items, ...rest } = input
  return (
    Object.values(rest).every((v) => v == null) &&
    Object.keys(vitals ?? {}).length === 0 &&
    (items ?? []).length === 0
  )
}

interface Props {
  patientId: string
  appointmentId: string
}

export function CurrentVisit({ patientId, appointmentId }: Props) {
  const visit = useQuery({
    queryKey: recordKeys.visit(appointmentId),
    queryFn: ({ signal }) => fetchVisit(appointmentId, signal),
    // The form owns its state once loaded; refetching would not change what is shown.
    staleTime: Infinity,
  })

  if (visit.isPending) return <Skeleton className="h-96" />
  if (visit.isError) return <p className="text-sm text-destructive">{visit.error.message}</p>
  if (!visit.data.editable) return <ReadOnlyVisit visit={visit.data} />
  return <VisitForm key={appointmentId} visit={visit.data} patientId={patientId} />
}

function ReadOnlyVisit({ visit }: { visit: Visit }) {
  const c = visit.consultation
  const startable = visit.appointment_status === 'checked_in'
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {c?.status === 'finalized' ? 'This visit is finalized' : 'Visit notes'}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {c ? (
          <VisitDetails visit={c} />
        ) : (
          <p className="text-muted-foreground">
            {startable
              ? 'Only the treating doctor can write notes for this visit.'
              : 'No notes were recorded for this visit.'}
          </p>
        )}
        {c?.status === 'finalized' && (
          <p className="text-muted-foreground">
            Corrections can be added as an addendum from Visit history.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function VisitForm({ visit, patientId }: { visit: Visit; patientId: string }) {
  const appointmentId = visit.appointment_id
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [draft, setDraft] = useState<Draft>(() => draftFrom(visit.consultation))
  const [status, setStatus] = useState(visit.appointment_status)
  const [confirming, setConfirming] = useState(false)
  const [attaching, setAttaching] = useState(false)
  const [consultationId, setConsultationId] = useState(visit.consultation?.id ?? null)

  const payload = useMemo(() => toInput(draft), [draft])
  const autosave = useAutosave(
    payload,
    async (body: ConsultationInput) => {
      const saved = await saveVisit(appointmentId, body)
      setConsultationId(saved.consultation?.id ?? null)
      queryClient.setQueryData(recordKeys.visit(appointmentId), saved)
    },
    { enabled: true },
  )

  const start = useMutation({
    mutationFn: () => changeStatus(appointmentId, 'in_consultation'),
    onSuccess: () => {
      setStatus('in_consultation')
      void queryClient.invalidateQueries({ queryKey: appointmentKeys.all })
      void queryClient.invalidateQueries({ queryKey: recordKeys.patient(patientId) })
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : 'Could not start.'),
  })

  const complete = useMutation({
    mutationFn: async () => {
      await autosave.flush()
      return completeVisit(appointmentId)
    },
    onSuccess: () => {
      toast.success('Consultation completed')
      void queryClient.invalidateQueries({ queryKey: appointmentKeys.all })
      void queryClient.invalidateQueries({ queryKey: recordKeys.all })
      navigate('/doctor')
    },
    onError: (error) => {
      setConfirming(false)
      toast.error(error instanceof ApiError ? error.message : 'Could not complete.')
    },
  })

  const repeat = useMutation({
    mutationFn: () => fetchLatestPrescription(patientId),
    onSuccess: (latest) => {
      if (!latest || latest.items.length === 0) {
        toast.info('No earlier prescription to repeat')
        return
      }
      setDraft((d) => ({ ...d, items: [...d.items, ...latest.items.map(itemFromServer)] }))
      toast.success(`Added ${latest.items.length} medicine(s) from ${latest.doctor_name}'s prescription`)
    },
  })

  const setText = (key: TextField, value: string) =>
    setDraft((d) => ({ ...d, text: { ...d.text, [key]: value } }))
  const setVital = (key: VitalKey, value: string) =>
    setDraft((d) => ({ ...d, vitals: { ...d.vitals, [key]: value } }))

  return (
    <div className="space-y-4" data-consultation-id={consultationId ?? ''}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SaveIndicator state={autosave.state} error={autosave.error} />
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => setAttaching(true)}>
            <PaperclipIcon />
            Attach report
          </Button>
          {status === 'checked_in' ? (
            <Button onClick={() => start.mutate()} disabled={start.isPending}>
              {start.isPending ? <Loader2Icon className="animate-spin" /> : <PlayIcon />}
              Start consultation
            </Button>
          ) : (
            <Button onClick={() => setConfirming(true)} disabled={complete.isPending}>
              <CheckCheckIcon />
              Complete consultation
            </Button>
          )}
        </div>
      </div>

      <Card>
        <CardContent className="grid gap-4 pt-4 lg:grid-cols-2">
          {TEXT_FIELDS.map(({ key, label, rows }) => (
            <div key={key} className="space-y-1.5">
              <Label htmlFor={`field-${key}`}>{label}</Label>
              <Textarea
                id={`field-${key}`}
                rows={rows}
                value={draft.text[key]}
                onChange={(e) => setText(key, e.target.value)}
              />
            </div>
          ))}
          <div className="space-y-1.5">
            <Label htmlFor="field-follow-up">Follow-up date</Label>
            <Input
              id="field-follow-up"
              type="date"
              className="w-48"
              value={draft.follow_up_date}
              onChange={(e) => setDraft((d) => ({ ...d, follow_up_date: e.target.value }))}
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Vitals</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {VITAL_FIELDS.map(({ key, label, unit, decimal }) => (
            <div key={key} className="space-y-1">
              <Label htmlFor={`vital-${key}`} className="text-xs">
                {label} {unit && <span className="text-muted-foreground">({unit})</span>}
              </Label>
              <Input
                id={`vital-${key}`}
                inputMode={decimal ? 'decimal' : 'numeric'}
                value={draft.vitals[key] ?? ''}
                onChange={(e) =>
                  setVital(key, e.target.value.replace(decimal ? /[^\d.]/g : /\D/g, ''))
                }
              />
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Prescription</CardTitle>
        </CardHeader>
        <CardContent>
          <PrescriptionBuilder
            items={draft.items}
            onChange={(items) => setDraft((d) => ({ ...d, items }))}
            onRepeatLast={() => repeat.mutate()}
            repeatPending={repeat.isPending}
          />
        </CardContent>
      </Card>

      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Complete this consultation?"
        description={
          isEmpty(payload)
            ? 'No notes, vitals or prescription have been recorded. The visit will be completed without a record.'
            : 'The notes and prescription will be finalized and can no longer be edited (addenda are still possible).'
        }
        confirmLabel={isEmpty(payload) ? 'Complete without notes' : 'Complete'}
        pending={complete.isPending}
        onConfirm={() => complete.mutate()}
      />
      {attaching && (
        <ReportUploadDialog
          patientId={patientId}
          consultationId={consultationId}
          open={attaching}
          onOpenChange={setAttaching}
        />
      )}
    </div>
  )
}

function SaveIndicator({ state, error }: { state: SaveState; error: string | null }) {
  const meta = {
    saved: { icon: CheckIcon, text: 'Saved', className: 'text-emerald-700 dark:text-emerald-400' },
    dirty: { icon: CloudIcon, text: 'Unsaved changes', className: 'text-muted-foreground' },
    saving: { icon: Loader2Icon, text: 'Saving…', className: 'text-muted-foreground' },
    error: { icon: AlertCircleIcon, text: error ?? 'Not saved', className: 'text-destructive' },
  }[state]
  const Icon = meta.icon
  return (
    <span className={`inline-flex items-center gap-1.5 text-sm ${meta.className}`} data-save-state={state}>
      <Icon className={state === 'saving' ? 'size-4 animate-spin' : 'size-4'} />
      {meta.text}
    </span>
  )
}
