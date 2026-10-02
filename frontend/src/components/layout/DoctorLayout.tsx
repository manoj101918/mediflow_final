import { Outlet } from 'react-router'

import { CriticalAlertBanner } from '@/components/labs/CriticalAlertBanner'
import { TopBar } from '@/components/layout/TopBar'
import { useRealtimeLabOrders } from '@/hooks/useRealtimeLabs'

/** Doctor area: top bar, critical lab alerts on every screen, live lab statuses. */
export function DoctorLayout() {
  useRealtimeLabOrders()
  return (
    <div className="flex min-h-svh flex-col bg-muted/30">
      <TopBar />
      <CriticalAlertBanner />
      <main className="flex-1 p-4 md:p-6">
        <Outlet />
      </main>
    </div>
  )
}
