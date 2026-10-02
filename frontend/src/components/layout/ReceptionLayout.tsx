import { useQueryClient } from '@tanstack/react-query'
import { CalendarDaysIcon, LayoutDashboardIcon, StethoscopeIcon, UsersIcon } from 'lucide-react'
import { useCallback, useMemo, useState } from 'react'
import { toast } from 'sonner'

import { NewAppointmentSheet } from '@/components/appointments/NewAppointmentSheet'
import {
  NewAppointmentContext,
  type NewAppointmentPrefill,
} from '@/components/appointments/newAppointmentContext'
import { type NavItem, SidebarShell } from '@/components/layout/SidebarShell'
import { useHotkeys } from '@/hooks/useHotkeys'
import { type AppointmentRow, useRealtimeAppointments } from '@/hooks/useRealtimeAppointments'
import { doctorKeys } from '@/lib/appointments'
import { clinicDate, formatTime, formatWeekdayDate } from '@/lib/format'
import type { Doctor } from '@/types/api'

const NAV: NavItem[] = [
  { to: '/reception', label: 'Today', icon: LayoutDashboardIcon, end: true },
  { to: '/reception/appointments', label: 'Appointments', icon: CalendarDaysIcon },
  { to: '/reception/patients', label: 'Patients', icon: UsersIcon },
  { to: '/reception/doctors', label: 'Doctors', icon: StethoscopeIcon },
]

export function ReceptionLayout() {
  const queryClient = useQueryClient()

  const announce = useCallback(
    (row: AppointmentRow) => {
      const doctors = queryClient.getQueryData<Doctor[]>(doctorKeys.all)
      const doctor = doctors?.find((d) => d.id === row.doctor_id)?.full_name ?? 'a doctor'
      const when =
        clinicDate(row.starts_at) === clinicDate()
          ? formatTime(row.starts_at)
          : `${formatWeekdayDate(row.starts_at)}, ${formatTime(row.starts_at)}`
      if (row.status === 'pending_confirmation') {
        toast.info('New bot booking needs confirmation', { description: `${doctor} · ${when}` })
      } else {
        toast(`New booking: token #${row.token_number}`, { description: `${doctor} · ${when}` })
      }
    },
    [queryClient],
  )
  useRealtimeAppointments({ onInsertByOthers: announce })

  const [booking, setBooking] = useState<{ open: boolean; session: number; prefill?: NewAppointmentPrefill }>({
    open: false,
    session: 0,
  })
  const newAppointment = useMemo(
    () => ({
      openNewAppointment: (prefill?: NewAppointmentPrefill) =>
        setBooking((b) => ({ open: true, session: b.session + 1, prefill })),
    }),
    [],
  )
  useHotkeys({ n: () => newAppointment.openNewAppointment() })

  return (
    <NewAppointmentContext value={newAppointment}>
      <SidebarShell items={NAV} label="Reception">
        <NewAppointmentSheet
          open={booking.open}
          session={booking.session}
          prefillPatient={booking.prefill?.patient}
          prefillSearch={booking.prefill?.search}
          onOpenChange={(open) => setBooking((b) => ({ ...b, open }))}
        />
      </SidebarShell>
    </NewAppointmentContext>
  )
}
