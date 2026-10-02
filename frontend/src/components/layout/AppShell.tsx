import { Outlet } from 'react-router'

import { TopBar } from '@/components/layout/TopBar'

export function AppShell() {
  return (
    <div className="flex min-h-svh flex-col bg-muted/30">
      <TopBar />
      <main className="flex-1 p-4 md:p-6">
        <Outlet />
      </main>
    </div>
  )
}
