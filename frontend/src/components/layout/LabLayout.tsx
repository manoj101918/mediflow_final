import { FlaskConicalIcon } from 'lucide-react'

import { type NavItem, SidebarShell } from '@/components/layout/SidebarShell'

const NAV: NavItem[] = [{ to: '/lab', label: 'Worklist', icon: FlaskConicalIcon, end: true }]

export function LabLayout() {
  return <SidebarShell items={NAV} label="Lab" />
}
