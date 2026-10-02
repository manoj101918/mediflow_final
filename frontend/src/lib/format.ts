// All dates/times are shown in clinic time (IST), regardless of the browser's timezone.
export const CLINIC_TIME_ZONE = 'Asia/Kolkata'

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

/** 02 Oct 2026 */
export function formatDate(value: Date | string): string {
  return dateFormat.format(new Date(value))
}

/** Fri, 02 Oct 2026 */
export function formatWeekdayDate(value: Date | string): string {
  return weekdayDateFormat.format(new Date(value))
}

/** 10:30 AM */
export function formatTime(value: Date | string): string {
  return timeFormat.format(new Date(value))
}
