import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CheckIcon,
  Loader2Icon,
  PalmtreeIcon,
  SearchIcon,
  UserPlusIcon,
  ZapIcon,
} from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import type { SelectedPatient } from '@/components/appointments/newAppointmentContext'
import { SlotPicker, type SlotChoice } from '@/components/appointments/SlotPicker'
import { PatientForm } from '@/components/patients/PatientForm'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { ApiError } from '@/lib/api'
import {
  SOURCE_META,
  appointmentKeys,
  createAppointment,
  doctorKeys,
  fetchDoctors,
} from '@/lib/appointments'
import {
  clinicDate,
  formatPatientMeta,
  formatPhone,
  formatTime,
  formatWeekdayDate,
} from '@/lib/format'
import { createPatient, patientKeys, searchPatients } from '@/lib/patients'
import { cn } from '@/lib/utils'
import type { PatientInput, StaffSource } from '@/types/api'

type Step = 'patient' | 'slot' | 'details'
const STEPS: { id: Step; label: string }[] = [
  { id: 'patient', label: 'Patient' },
  { id: 'slot', label: 'Doctor & time' },
  { id: 'details', label: 'Confirm' },
]
const SOURCES: StaffSource[] = ['walk_in', 'phone', 'manual']

interface NewAppointmentSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  prefillPatient?: SelectedPatient
  /** Text to search patients for (e.g. a bot caller's phone number). */
  prefillSearch?: string
  /** Changes every time the sheet opens, so each booking starts fresh. */
  session: number
}

export function NewAppointmentSheet({
  open,
  onOpenChange,
  prefillPatient,
  prefillSearch,
  session,
}: NewAppointmentSheetProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full gap-0 overflow-y-auto sm:max-w-xl">
        <SheetHeader className="border-b">
          <SheetTitle>New appointment</SheetTitle>
          <SheetDescription>Find or add the patient, pick a slot, confirm.</SheetDescription>
        </SheetHeader>
        <BookingFlow
          key={session}
          prefillPatient={prefillPatient}
          prefillSearch={prefillSearch}
          onDone={() => onOpenChange(false)}
        />
      </SheetContent>
    </Sheet>
  )
}

function BookingFlow({
  prefillPatient,
  prefillSearch,
  onDone,
}: {
  prefillPatient?: SelectedPatient
  prefillSearch?: string
  onDone: () => void
}) {
  const queryClient = useQueryClient()
  const [step, setStep] = useState<Step>(prefillPatient ? 'slot' : 'patient')
  const [patient, setPatient] = useState<SelectedPatient | null>(prefillPatient ?? null)
  const [doctorId, setDoctorId] = useState<string | null>(null)
  const [date, setDate] = useState(clinicDate())
  const [choice, setChoice] = useState<SlotChoice | null>(null)
  const [source, setSource] = useState<StaffSource>('walk_in')
  const [reason, setReason] = useState('')
  const [notes, setNotes] = useState('')

  const doctorsQuery = useQuery({
    queryKey: doctorKeys.all,
    queryFn: ({ signal }) => fetchDoctors(signal),
    staleTime: 5 * 60_000,
  })
  const doctor = doctorsQuery.data?.find((d) => d.id === doctorId)

  const book = useMutation({
    mutationFn: () =>
      createAppointment({
        patient_id: patient!.id,
        doctor_id: doctorId!,
        starts_at: choice!.startsAt,
        source,
        reason_for_visit: reason.trim() || null,
        notes: notes.trim() || null,
        squeeze_in: choice!.squeezeIn,
      }),
    onSuccess: (a) => {
      toast.success(`Booked token #${a.token_number} for ${a.patient.full_name}`, {
        description: `${a.doctor.full_name} · ${formatWeekdayDate(a.starts_at)}, ${formatTime(a.starts_at)}`,
      })
      onDone()
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'SLOT_TAKEN') {
        toast.error(error.message)
        setChoice(null)
        setStep('slot')
      }
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: appointmentKeys.all }),
  })

  const choosePatient = (p: SelectedPatient) => {
    setPatient(p)
    setStep('slot')
  }
  const reached = (s: Step) =>
    s === 'patient' || (s === 'slot' && patient !== null) || (s === 'details' && Boolean(choice?.startsAt))

  return (
    <div className="flex flex-1 flex-col">
      <ol className="flex gap-1 border-b px-4 py-2 text-sm">
        {STEPS.map((s, i) => {
          const active = s.id === step
          const done = STEPS.findIndex((x) => x.id === step) > i
          return (
            <li key={s.id} className="flex-1">
              <button
                type="button"
                disabled={!reached(s.id) || active}
                onClick={() => setStep(s.id)}
                className={cn(
                  'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-muted-foreground disabled:cursor-default',
                  active && 'bg-muted font-medium text-foreground',
                  done && 'text-foreground hover:bg-muted',
                )}
              >
                <span
                  className={cn(
                    'flex size-5 shrink-0 items-center justify-center rounded-full border text-xs',
                    (active || done) && 'border-primary bg-primary text-primary-foreground',
                  )}
                >
                  {done ? <CheckIcon className="size-3" /> : i + 1}
                </span>
                <span className="truncate">{s.label}</span>
              </button>
            </li>
          )
        })}
      </ol>

      <div className="flex-1 space-y-4 p-4">
        {patient && step !== 'patient' && (
          <div className="flex items-center justify-between rounded-lg bg-muted/60 px-3 py-2 text-sm">
            <div>
              <span className="font-medium">{patient.full_name}</span>
              <span className="text-muted-foreground">
                {' '}
                · {[formatPatientMeta(patient.gender, patient.age), formatPhone(patient.phone)].filter(Boolean).join(' · ')}
              </span>
            </div>
            <Button variant="link" size="sm" className="h-auto p-0" onClick={() => setStep('patient')}>
              Change
            </Button>
          </div>
        )}

        {step === 'patient' && <PatientStep initialSearch={prefillSearch} onChoose={choosePatient} />}

        {step === 'slot' && (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Doctor</Label>
              {doctorsQuery.isPending ? (
                <Skeleton className="h-16" />
              ) : (
                <div className="grid gap-2 sm:grid-cols-2">
                  {doctorsQuery.data?.map((d) => (
                    <button
                      key={d.id}
                      type="button"
                      aria-pressed={d.id === doctorId}
                      onClick={() => {
                        setDoctorId(d.id)
                        setChoice(null)
                      }}
                      className={cn(
                        'rounded-lg border p-3 text-left text-sm transition-colors hover:bg-muted',
                        d.id === doctorId && 'border-primary bg-muted ring-1 ring-primary',
                      )}
                    >
                      <div className="font-medium">{d.full_name}</div>
                      <div className="text-xs text-muted-foreground">
                        {d.specialization} · {d.default_slot_minutes} min · ₹{d.consultation_fee}
                      </div>
                      {d.on_leave_today && (
                        <div className="mt-1 flex items-center gap-1 text-xs text-amber-700 dark:text-amber-300">
                          <PalmtreeIcon className="size-3" /> On leave today
                        </div>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
            {doctorId && (
              <div className="space-y-2">
                <Label>Time</Label>
                <SlotPicker doctorId={doctorId} date={date} onDateChange={setDate} value={choice} onChange={setChoice} />
              </div>
            )}
            <div className="flex justify-end">
              <Button disabled={!choice?.startsAt} onClick={() => setStep('details')}>
                Continue
              </Button>
            </div>
          </div>
        )}

        {step === 'details' && patient && doctor && choice?.startsAt && (
          <div className="space-y-4">
            <dl className="grid grid-cols-[6rem_1fr] gap-y-1.5 rounded-lg border p-3 text-sm">
              <dt className="text-muted-foreground">Doctor</dt>
              <dd>{doctor.full_name}</dd>
              <dt className="text-muted-foreground">When</dt>
              <dd className="flex flex-wrap items-center gap-2">
                {formatWeekdayDate(choice.startsAt)}, {formatTime(choice.startsAt)}
                {choice.squeezeIn && (
                  <span className="inline-flex items-center gap-1 rounded bg-amber-100 px-1.5 text-xs text-amber-900 dark:bg-amber-500/20 dark:text-amber-200">
                    <ZapIcon className="size-3" /> Squeeze-in
                  </span>
                )}
              </dd>
            </dl>

            <div className="space-y-1.5">
              <Label>How did they book?</Label>
              <div className="flex gap-1.5" role="radiogroup" aria-label="Booking source">
                {SOURCES.map((s) => {
                  const { label, icon: Icon } = SOURCE_META[s]
                  return (
                    <Button
                      key={s}
                      type="button"
                      role="radio"
                      aria-checked={source === s}
                      variant={source === s ? 'default' : 'outline'}
                      className="flex-1"
                      onClick={() => setSource(s)}
                    >
                      <Icon /> {label}
                    </Button>
                  )
                })}
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="reason">Reason for visit</Label>
              <Input
                id="reason"
                value={reason}
                maxLength={200}
                onChange={(e) => setReason(e.target.value)}
                placeholder="e.g. Fever since 2 days"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="notes">Notes for the front desk</Label>
              <Textarea id="notes" rows={2} value={notes} maxLength={1000} onChange={(e) => setNotes(e.target.value)} />
            </div>
            {book.isError && !(book.error instanceof ApiError && book.error.code === 'SLOT_TAKEN') && (
              <p role="alert" className="rounded-lg bg-destructive/5 p-3 text-sm text-destructive">
                {book.error instanceof ApiError ? book.error.message : 'Could not book the appointment.'}
              </p>
            )}
            <Button className="w-full" size="lg" disabled={book.isPending} onClick={() => book.mutate()}>
              {book.isPending && <Loader2Icon className="animate-spin" />}
              Book appointment
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}

function PatientStep({
  initialSearch = '',
  onChoose,
}: {
  initialSearch?: string
  onChoose: (p: SelectedPatient) => void
}) {
  const queryClient = useQueryClient()
  const [search, setSearch] = useState(initialSearch)
  const [adding, setAdding] = useState(false)
  const q = useDebouncedValue(search.trim(), 250)

  const results = useQuery({
    queryKey: patientKeys.search(q, 1, 8),
    queryFn: ({ signal }) => searchPatients(q, 1, 8, signal),
    enabled: q.length >= 2,
  })

  if (adding) {
    return (
      <div className="space-y-3">
        <h3 className="flex items-center gap-2 font-medium">
          <UserPlusIcon className="size-4" /> New patient
        </h3>
        <PatientForm
          compact
          initialName={search}
          submitLabel="Save and continue"
          onCancel={() => setAdding(false)}
          onUseExisting={onChoose}
          onSubmit={async (input) => {
            const created = await createPatient(input as PatientInput)
            void queryClient.invalidateQueries({ queryKey: patientKeys.all })
            toast.success(`Added ${created.full_name}`)
            onChoose(created)
          }}
        />
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="relative">
        <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          autoFocus
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by name or phone number"
          aria-label="Search patients"
          className="pl-8"
        />
      </div>

      {q.length >= 2 && (
        <div className="rounded-lg border">
          {results.isPending ? (
            <div className="space-y-2 p-3">
              <Skeleton className="h-9" />
              <Skeleton className="h-9" />
            </div>
          ) : results.data?.items.length ? (
            <ul className="divide-y" aria-label="Matching patients">
              {results.data.items.map((p) => (
                <li key={p.id}>
                  <button
                    type="button"
                    onClick={() => onChoose(p)}
                    className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-muted focus-visible:bg-muted focus-visible:outline-none"
                  >
                    <span>
                      <span className="font-medium">{p.full_name}</span>
                      <span className="block text-xs text-muted-foreground">
                        {[formatPhone(p.phone), formatPatientMeta(p.gender, p.age)].filter(Boolean).join(' · ')}
                      </span>
                    </span>
                    <span className="text-xs text-muted-foreground">Select</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="p-3 text-sm text-muted-foreground">No patient found for “{q}”.</p>
          )}
        </div>
      )}

      <Button variant={q.length >= 2 && !results.data?.items.length ? 'default' : 'outline'} className="w-full" onClick={() => setAdding(true)}>
        <UserPlusIcon /> Add new patient
      </Button>
    </div>
  )
}
