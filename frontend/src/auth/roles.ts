import type { UserRole } from '@/types/api'

export const ROLE_HOME: Record<UserRole, string> = {
  receptionist: '/reception',
  doctor: '/doctor',
  admin: '/admin',
  lab_technician: '/lab',
  lab_supervisor: '/lab',
}

export const ROLE_LABEL: Record<UserRole, string> = {
  receptionist: 'Receptionist',
  doctor: 'Doctor',
  admin: 'Admin',
  lab_technician: 'Lab technician',
  lab_supervisor: 'Lab supervisor',
}

/** True when `path` belongs to the area the role is allowed to open. */
export function canVisit(role: UserRole, path: string): boolean {
  const home = ROLE_HOME[role]
  return path === home || path.startsWith(`${home}/`)
}
