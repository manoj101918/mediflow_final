import type { ReactNode } from 'react'

import { describeItem, describeVitals } from '@/lib/records'
import { formatDate } from '@/lib/format'
import type { PrescriptionItem, Vitals } from '@/types/api'

interface VisitLike {
  chief_complaint: string | null
  history: string | null
  examination: string | null
  diagnosis: string | null
  advice: string | null
  follow_up_date: string | null
  notes: string | null
  vitals: Vitals
  items: PrescriptionItem[]
}

const SECTIONS: { key: keyof VisitLike; label: string }[] = [
  { key: 'chief_complaint', label: 'Complaint' },
  { key: 'history', label: 'History' },
  { key: 'examination', label: 'Examination' },
  { key: 'diagnosis', label: 'Diagnosis' },
  { key: 'advice', label: 'Advice' },
  { key: 'notes', label: 'Notes' },
]

/** Read-only rendering of one visit's notes, vitals and prescription. */
export function VisitDetails({ visit }: { visit: VisitLike }) {
  const vitals = describeVitals(visit.vitals)
  return (
    <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[8rem_1fr]">
      {SECTIONS.map(({ key, label }) => {
        const value = visit[key]
        if (!value || typeof value !== 'string') return null
        return (
          <Row key={key} label={label}>
            <span className="whitespace-pre-wrap">{value}</span>
          </Row>
        )
      })}
      {vitals && <Row label="Vitals">{vitals}</Row>}
      {visit.items.length > 0 && (
        <Row label="Prescription">
          <ol className="list-decimal space-y-0.5 pl-4">
            {visit.items.map((item) => (
              <li key={item.id}>
                {describeItem(item)}
                {item.instructions && (
                  <span className="text-muted-foreground"> — {item.instructions}</span>
                )}
              </li>
            ))}
          </ol>
        </Row>
      )}
      {visit.follow_up_date && <Row label="Follow-up">{formatDate(visit.follow_up_date)}</Row>}
    </dl>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd>{children}</dd>
    </>
  )
}
