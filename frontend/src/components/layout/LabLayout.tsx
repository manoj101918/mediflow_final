import { FlaskConicalIcon } from 'lucide-react'

import { type NavItem, SidebarShell } from '@/components/layout/SidebarShell'
import { useRealtimeLabOrders } from '@/hooks/useRealtimeLabs'

const NAV: NavItem[] = [{ to: '/lab', label: 'Worklist', icon: FlaskConicalIcon, end: true }]

export function LabLayout() {
  // New orders, cancellations and every status change refresh the worklists live.
  useRealtimeLabOrders()
  return <SidebarShell items={NAV} label="Lab" />
}
