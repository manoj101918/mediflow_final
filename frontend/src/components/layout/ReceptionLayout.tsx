import { useQueryClient } from '@tanstack/react-query'
import {
  CalendarDaysIcon,
  LayoutDashboardIcon,
  type LucideIcon,
  MenuIcon,
  StethoscopeIcon,
  UsersIcon,
} from 'lucide-react'
import { useCallback, useMemo, useState } from 'react'
import { NavLink, Outlet } from 'react-router'
import { toast } from 'sonner'

import { NewAppointmentSheet } from '@/components/appointments/NewAppointmentSheet'
import {
  NewAppointmentContext,
  type SelectedPatient,
} from '@/components/appointments/newAppointmentContext'
import { TopBar } from '@/components/layout/TopBar'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { useHotkeys } from '@/hooks/useHotkeys'
import { useRealtimeAppointments } from '@/hooks/useRealtimeAppointments'
import { doctorKeys } from '@/lib/appointments'
import { formatTime, formatWeekdayDate, clinicDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { Doctor } from '@/types/api'

const NAV: { to: string; label: string; icon: LucideIcon; end?: boolean }[] = [
  { to: '/reception', label: 'Today', icon: LayoutDashboardIcon, end: true },
  { to: '/reception/appointments', label: 'Appointments', icon: CalendarDaysIcon },
  { to: '/reception/patients', label: 'Patients', icon: UsersIcon },
  { to: '/reception/doctors', label: 'Doctors', icon: StethoscopeIcon },
]

function Nav({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="flex flex-col gap-1 p-3" aria-label="Reception">
      {NAV.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              'flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground',
              isActive && 'bg-muted text-foreground',
            )
          }
        >
          <Icon className="size-4" />
          {label}
        </NavLink>
      ))}
    </nav>
  )
}

export function ReceptionLayout() {
  const [menuOpen, setMenuOpen] = useState(false)
  const queryClient = useQueryClient()

  const announce = useCallback(
    (row: { token_number: number; doctor_id: string; starts_at: string; status: string }) => {
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
  useRealtimeAppointments(announce)

  const [booking, setBooking] = useState<{ open: boolean; session: number; patient?: SelectedPatient }>({
    open: false,
    session: 0,
  })
  const newAppointment = useMemo(
    () => ({
      openNewAppointment: (prefill?: { patient?: SelectedPatient }) =>
        setBooking((b) => ({ open: true, session: b.session + 1, patient: prefill?.patient })),
    }),
    [],
  )
  useHotkeys({ n: () => newAppointment.openNewAppointment() })

  return (
    <NewAppointmentContext value={newAppointment}>
    <div className="flex min-h-svh flex-col bg-muted/30">
      <TopBar>
        <Button
          variant="ghost"
          size="icon"
          className="md:hidden"
          aria-label="Open menu"
          onClick={() => setMenuOpen(true)}
        >
          <MenuIcon />
        </Button>
      </TopBar>
      <div className="flex flex-1">
        <aside className="hidden w-52 shrink-0 border-r bg-background md:block">
          <Nav />
        </aside>
        <main className="min-w-0 flex-1 p-4 md:p-6">
          <Outlet />
        </main>
      </div>
      <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
        <SheetContent side="left" className="w-64 p-0">
          <SheetHeader>
            <SheetTitle>Menu</SheetTitle>
          </SheetHeader>
          <Nav onNavigate={() => setMenuOpen(false)} />
        </SheetContent>
      </Sheet>
      <NewAppointmentSheet
        open={booking.open}
        session={booking.session}
        prefillPatient={booking.patient}
        onOpenChange={(open) => setBooking((b) => ({ ...b, open }))}
      />
    </div>
    </NewAppointmentContext>
  )
}
