// All dates/times are shown in clinic time (IST), regardless of the browser's timezone.
export const CLINIC_TIME_ZONE = 'Asia/Kolkata'
/** IST has no DST, so a fixed offset is safe for building timestamps from clinic wall time. */
export const CLINIC_UTC_OFFSET = '+05:30'

const dateFormat = new Intl.DateTimeFormat('en-GB', {
  timeZone: CLINIC_TIME_ZONE,
  day: '2-digit',
  month: 'short',
  year: 'numeric',
})

const weekdayDateFormat = new Intl.DateTimeFormat('en-GB', {
  timeZone: CLINIC_TIME_ZONE,
  weekday: 'short',
  day: '2-digit',
  month: 'short',
  year: 'numeric',
})

const timeFormat = new Intl.DateTimeFormat('en-US', {
  timeZone: CLINIC_TIME_ZONE,
  hour: 'numeric',
  minute: '2-digit',
  hour12: true,
})

// en-CA formats as YYYY-MM-DD.
const isoDateFormat = new Intl.DateTimeFormat('en-CA', {
  timeZone: CLINIC_TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

/** A YYYY-MM-DD string at noon UTC, so formatting it in IST never shifts the day. */
function fromIsoDate(value: string): Date {
  return new Date(`${value}T12:00:00Z`)
}

function toDate(value: Date | string): Date {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)
    ? fromIsoDate(value)
    : new Date(value)
}

/** 02 Oct 2026 */
export function formatDate(value: Date | string): string {
  return dateFormat.format(toDate(value))
}

/** Fri, 02 Oct 2026 */
export function formatWeekdayDate(value: Date | string): string {
  return weekdayDateFormat.format(toDate(value))
}

/** 10:30 AM */
export function formatTime(value: Date | string): string {
  return timeFormat.format(new Date(value))
}

/** Clinic-local calendar date (YYYY-MM-DD) of an instant. */
export function clinicDate(value: Date | string = new Date()): string {
  return isoDateFormat.format(new Date(value))
}

/** YYYY-MM-DD shifted by whole days. */
export function addDays(isoDate: string, days: number): string {
  const d = fromIsoDate(isoDate)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

/** ISO timestamp for a clinic wall-clock time, e.g. ('2026-10-02', '10:30') -> ...T10:30:00+05:30 */
export function clinicDateTime(isoDate: string, hhmm: string): string {
  return `${isoDate}T${hhmm}:00${CLINIC_UTC_OFFSET}`
}

/** "Male, 42" / "42 y" / "" */
export function formatPatientMeta(gender: string | null, age: number | null): string {
  const parts = [gender ? gender[0]!.toUpperCase() + gender.slice(1) : null, age != null ? `${age} y` : null]
  return parts.filter(Boolean).join(' · ')
}

/** +919848012345 -> +91 98480 12345 */
export function formatPhone(phone: string | null): string {
  if (!phone) return ''
  const m = /^\+91(\d{5})(\d{5})$/.exec(phone)
  return m ? `+91 ${m[1]} ${m[2]}` : phone
}

/** Wall-clock "HH:MM[:SS]" (schedule times) -> "9:00 AM" */
export function formatClock(hhmmss: string): string {
  const [h = 0, m = 0] = hhmmss.split(':').map(Number)
  const suffix = h >= 12 ? 'PM' : 'AM'
  return `${h % 12 || 12}:${String(m).padStart(2, '0')} ${suffix}`
}

export const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

/** Clinic weekday index (0 = Monday, matching the backend) of a YYYY-MM-DD date. */
export function clinicWeekday(isoDate: string): number {
  return (new Date(`${isoDate}T12:00:00Z`).getUTCDay() + 6) % 7
}
