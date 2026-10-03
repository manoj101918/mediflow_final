import { AudioLinesIcon, FlaskConicalIcon, MessageCircleIcon, StethoscopeIcon, UsersIcon } from 'lucide-react'

import { type NavItem, SidebarShell } from '@/components/layout/SidebarShell'

const NAV: NavItem[] = [
  { to: '/admin', label: 'Staff', icon: UsersIcon, end: true },
  { to: '/admin/doctors', label: 'Doctors', icon: StethoscopeIcon },
  { to: '/admin/lab-tests', label: 'Lab tests', icon: FlaskConicalIcon },
  { to: '/admin/whatsapp', label: 'WhatsApp bot', icon: MessageCircleIcon },
  { to: '/admin/voice-simulator', label: 'Voice simulator', icon: AudioLinesIcon },
]

export function AdminLayout() {
  return <SidebarShell items={NAV} label="Admin" />
}
