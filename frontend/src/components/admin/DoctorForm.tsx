import { zodResolver } from '@hookform/resolvers/zod'
import { AlertCircleIcon, Loader2Icon } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ApiError } from '@/lib/api'
import type { Doctor, DoctorInput } from '@/types/api'

const schema = z.object({
  full_name: z.string().trim().min(1, "Enter the doctor's name.").max(120),
  specialization: z.string().trim().min(1, 'Enter a specialization.').max(120),
  consultation_fee: z
    .string()
    .trim()
    .regex(/^\d{1,7}(\.\d{1,2})?$/, 'Enter an amount in rupees.'),
  default_slot_minutes: z
    .string()
    .trim()
    .refine((v) => /^\d+$/.test(v) && Number(v) >= 5 && Number(v) <= 240, '5 to 240 minutes.'),
})
type Values = z.infer<typeof schema>

interface DoctorFormProps {
  doctor?: Doctor
  submitLabel: string
  onSubmit: (input: Partial<DoctorInput>) => Promise<unknown>
  onCancel?: () => void
}

export function DoctorForm({ doctor, submitLabel, onSubmit, onCancel }: DoctorFormProps) {
  const [error, setError] = useState<string | null>(null)
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      full_name: doctor?.full_name ?? '',
      specialization: doctor?.specialization ?? '',
      consultation_fee: doctor ? String(doctor.consultation_fee) : '0',
      default_slot_minutes: doctor ? String(doctor.default_slot_minutes) : '15',
    },
  })
  const { errors, isSubmitting, isDirty, dirtyFields } = form.formState

  const submit = form.handleSubmit(async (v) => {
    setError(null)
    const input: DoctorInput = {
      full_name: v.full_name.trim(),
      specialization: v.specialization.trim(),
      consultation_fee: Number(v.consultation_fee),
      default_slot_minutes: Number(v.default_slot_minutes),
    }
    const payload = doctor
      ? Object.fromEntries(Object.entries(input).filter(([k]) => dirtyFields[k as keyof Values]))
      : input
    try {
      await onSubmit(payload)
      if (doctor) form.reset(v)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not save the doctor.')
    }
  })

  const field = (name: keyof Values, label: string, props: React.ComponentProps<'input'> = {}) => (
    <div className="space-y-1.5">
      <Label htmlFor={`doctor-${name}`}>{label}</Label>
      <Input id={`doctor-${name}`} aria-invalid={Boolean(errors[name])} {...props} {...form.register(name)} />
      {errors[name] && <p className="text-xs text-destructive">{errors[name]?.message}</p>}
    </div>
  )

  return (
    <form className="space-y-4" noValidate onSubmit={(e) => void submit(e)}>
      {error && (
        <p role="alert" className="flex items-center gap-2 rounded-lg bg-destructive/5 p-3 text-sm text-destructive">
          <AlertCircleIcon className="size-4" /> {error}
        </p>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        {field('full_name', 'Full name', { placeholder: 'Dr. …', autoFocus: !doctor })}
        {field('specialization', 'Specialization', { placeholder: 'General Physician' })}
        {field('consultation_fee', 'Consultation fee (₹)', { inputMode: 'decimal' })}
        {field('default_slot_minutes', 'Minutes per patient', { inputMode: 'numeric' })}
      </div>
      {doctor && isDirty && dirtyFields.default_slot_minutes && (
        <p className="text-xs text-muted-foreground">
          A new slot length applies to future bookings; existing appointments keep their times.
        </p>
      )}
      <div className="flex justify-end gap-2">
        {onCancel && (
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancel
          </Button>
        )}
        <Button type="submit" disabled={isSubmitting || (Boolean(doctor) && !isDirty)}>
          {isSubmitting && <Loader2Icon className="animate-spin" />}
          {submitLabel}
        </Button>
      </div>
    </form>
  )
}
