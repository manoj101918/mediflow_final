import { StethoscopeIcon, UsersIcon } from 'lucide-react'

import { type NavItem, SidebarShell } from '@/components/layout/SidebarShell'

const NAV: NavItem[] = [
  { to: '/admin', label: 'Staff', icon: UsersIcon, end: true },
  { to: '/admin/doctors', label: 'Doctors', icon: StethoscopeIcon },
]

export function AdminLayout() {
  return <SidebarShell items={NAV} label="Admin" />
}
