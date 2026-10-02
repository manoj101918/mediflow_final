import { zodResolver } from '@hookform/resolvers/zod'
import { AlertCircleIcon, Loader2Icon } from 'lucide-react'
import { useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { z } from 'zod'

import { DuplicateWarning } from '@/components/patients/DuplicateWarning'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { ApiError } from '@/lib/api'
import { clinicDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { Gender, Patient, PatientInput } from '@/types/api'

const PHONE = /^\+?[\d\s-]{10,17}$/

const schema = z.object({
  full_name: z.string().trim().min(1, "Enter the patient's name.").max(120),
  phone: z.string().trim().regex(PHONE, 'Enter a valid mobile number (10 digits).'),
  alternate_phone: z
    .string()
    .trim()
    .refine((v) => v === '' || PHONE.test(v), 'Enter a valid phone number.'),
  gender: z.enum(['male', 'female', 'other', '']),
  age_years: z
    .string()
    .trim()
    .refine((v) => v === '' || (/^\d{1,3}$/.test(v) && Number(v) <= 130), 'Age must be 0–130.'),
  date_of_birth: z
    .string()
    .refine((v) => v === '' || v <= clinicDate(), 'Date of birth cannot be in the future.'),
  address: z.string().trim().max(200),
  notes: z.string().trim().max(1000),
})

type FormValues = z.infer<typeof schema>

function toValues(p?: Patient): FormValues {
  return {
    full_name: p?.full_name ?? '',
    phone: p?.phone ?? '',
    alternate_phone: p?.alternate_phone ?? '',
    gender: p?.gender ?? '',
    age_years: p?.age_years != null ? String(p.age_years) : '',
    date_of_birth: p?.date_of_birth ?? '',
    address: p?.address ?? '',
    notes: p?.notes ?? '',
  }
}

function toInput(v: FormValues): PatientInput {
  const orNull = (s: string) => (s.trim() === '' ? null : s.trim())
  return {
    full_name: v.full_name.trim(),
    phone: v.phone.trim(),
    alternate_phone: orNull(v.alternate_phone),
    gender: v.gender === '' ? null : v.gender,
    age_years: v.age_years === '' ? null : Number(v.age_years),
    date_of_birth: orNull(v.date_of_birth),
    address: orNull(v.address),
    notes: orNull(v.notes),
  }
}

const GENDERS: { value: Gender; label: string }[] = [
  { value: 'male', label: 'Male' },
  { value: 'female', label: 'Female' },
  { value: 'other', label: 'Other' },
]

interface PatientFormProps {
  patient?: Patient
  /** Name / phone / gender / age only (inline in the booking flow). */
  compact?: boolean
  submitLabel: string
  /** Receives the full input on create; only changed fields when editing. */
  onSubmit: (input: Partial<PatientInput>) => Promise<unknown>
  onCancel?: () => void
  onUseExisting?: (patient: Patient) => void
  initialName?: string
}

export function PatientForm({
  patient,
  compact,
  submitLabel,
  onSubmit,
  onCancel,
  onUseExisting,
  initialName,
}: PatientFormProps) {
  const [serverError, setServerError] = useState<string | null>(null)
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { ...toValues(patient), ...(initialName ? looksLikePhoneOrName(initialName) : {}) },
  })
  const { errors, isSubmitting, dirtyFields } = form.formState
  const [phone, fullName, gender] = useWatch({
    control: form.control,
    name: ['phone', 'full_name', 'gender'],
  })

  const submit = form.handleSubmit(async (values) => {
    setServerError(null)
    const input = toInput(values)
    const payload = patient
      ? Object.fromEntries(
          Object.entries(input).filter(([key]) => dirtyFields[key as keyof FormValues]),
        )
      : input
    try {
      await onSubmit(payload)
    } catch (error) {
      setServerError(error instanceof ApiError ? error.message : 'Could not save the patient.')
    }
  })

  const field = (name: keyof FormValues, label: string, props: React.ComponentProps<'input'> = {}) => (
    <div className="space-y-1.5">
      <Label htmlFor={`patient-${name}`}>{label}</Label>
      <Input id={`patient-${name}`} aria-invalid={Boolean(errors[name])} {...props} {...form.register(name)} />
      {errors[name] && <p className="text-xs text-destructive">{errors[name]?.message}</p>}
    </div>
  )

  return (
    <form className="space-y-4" noValidate onSubmit={(e) => void submit(e)}>
      {serverError && (
        <p role="alert" className="flex items-center gap-2 rounded-lg bg-destructive/5 p-3 text-sm text-destructive">
          <AlertCircleIcon className="size-4" /> {serverError}
        </p>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        {field('full_name', 'Full name *', { autoComplete: 'off', autoFocus: !patient })}
        {field('phone', 'Mobile number *', { inputMode: 'tel', autoComplete: 'off', placeholder: '98480 12345' })}
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label>Gender</Label>
          <div className="flex gap-1.5" role="radiogroup" aria-label="Gender">
            {GENDERS.map((g) => (
              <Button
                key={g.value}
                type="button"
                role="radio"
                aria-checked={gender === g.value}
                size="sm"
                variant={gender === g.value ? 'default' : 'outline'}
                className="flex-1"
                onClick={() =>
                  form.setValue('gender', gender === g.value ? '' : g.value, { shouldDirty: true })
                }
              >
                {g.label}
              </Button>
            ))}
          </div>
        </div>
        <div className="grid grid-cols-[5rem_1fr] gap-2">
          {field('age_years', 'Age', { inputMode: 'numeric', placeholder: 'yrs' })}
          {!compact && field('date_of_birth', 'or date of birth', { type: 'date', max: clinicDate() })}
        </div>
      </div>

      {!compact && (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            {field('alternate_phone', 'Alternate phone', { inputMode: 'tel', autoComplete: 'off' })}
            {field('address', 'Address / area', { autoComplete: 'off' })}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="patient-notes">Notes</Label>
            <Textarea id="patient-notes" rows={2} placeholder="Allergies, chronic conditions…" {...form.register('notes')} />
          </div>
        </>
      )}

      <DuplicateWarning
        phone={phone}
        fullName={fullName}
        excludeId={patient?.id}
        onUseExisting={onUseExisting}
      />

      <div className={cn('flex gap-2', onCancel ? 'justify-end' : '')}>
        {onCancel && (
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancel
          </Button>
        )}
        <Button type="submit" disabled={isSubmitting || (Boolean(patient) && !form.formState.isDirty)}>
          {isSubmitting && <Loader2Icon className="animate-spin" />}
          {submitLabel}
        </Button>
      </div>
    </form>
  )
}

/** Prefill from what was typed into the search box: digits go to phone, text to name. */
function looksLikePhoneOrName(text: string): Partial<FormValues> {
  const trimmed = text.trim()
  return /^[+\d\s-]+$/.test(trimmed) ? { phone: trimmed } : { full_name: trimmed }
}
