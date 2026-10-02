import { useQuery } from '@tanstack/react-query'
import { TriangleAlertIcon } from 'lucide-react'
import { Link } from 'react-router'

import { Button } from '@/components/ui/button'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { formatPatientMeta, formatPhone } from '@/lib/format'
import { DUPLICATE_LABEL, findDuplicates, patientKeys } from '@/lib/patients'
import type { Patient } from '@/types/api'

interface DuplicateWarningProps {
  phone: string
  fullName: string
  /** The patient being edited (never reported as its own duplicate). */
  excludeId?: string
  /** Offer "Use this patient" (booking flow) instead of a link to the record. */
  onUseExisting?: (patient: Patient) => void
}

/** Live "this patient may already exist" check while typing a name / phone. */
export function DuplicateWarning({ phone, fullName, excludeId, onUseExisting }: DuplicateWarningProps) {
  const debouncedPhone = useDebouncedValue(phone.replace(/\D/g, '').length >= 10 ? phone.trim() : '', 400)
  const debouncedName = useDebouncedValue(fullName.trim().length >= 3 ? fullName.trim() : '', 400)
  const enabled = Boolean(debouncedPhone || debouncedName)

  const query = useQuery({
    queryKey: patientKeys.duplicates(debouncedPhone, debouncedName, excludeId),
    queryFn: ({ signal }) => findDuplicates(debouncedPhone, debouncedName, excludeId, signal),
    enabled,
    staleTime: 30_000,
  })
  const matches = enabled ? (query.data ?? []) : []
  if (matches.length === 0) return null

  return (
    <div
      role="status"
      className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-800 dark:bg-amber-500/10"
    >
      <p className="flex items-center gap-2 font-medium text-amber-900 dark:text-amber-200">
        <TriangleAlertIcon className="size-4" />
        {matches.length === 1 ? 'This patient may already exist' : 'These patients may already exist'}
      </p>
      <ul className="space-y-1.5">
        {matches.map(({ patient, reason }) => (
          <li key={patient.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-background/80 px-2.5 py-1.5">
            <div className="min-w-0 flex-1">
              <div className="font-medium">{patient.full_name}</div>
              <div className="text-xs text-muted-foreground">
                {[formatPhone(patient.phone), formatPatientMeta(patient.gender, patient.age), DUPLICATE_LABEL[reason]]
                  .filter(Boolean)
                  .join(' · ')}
              </div>
            </div>
            {onUseExisting ? (
              <Button type="button" size="sm" variant="outline" onClick={() => onUseExisting(patient)}>
                Use this patient
              </Button>
            ) : (
              <Button type="button" size="sm" variant="ghost" asChild>
                <Link to={`/reception/patients/${patient.id}`}>View</Link>
              </Button>
            )}
          </li>
        ))}
      </ul>
      <p className="text-xs text-amber-900/80 dark:text-amber-200/80">
        Family members can share a phone number. Continue if this is a different person.
      </p>
    </div>
  )
}
