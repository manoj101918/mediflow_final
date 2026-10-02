import type { UserRole } from '@/types/api'

export const ROLE_HOME: Record<UserRole, string> = {
  receptionist: '/reception',
  doctor: '/doctor',
  admin: '/admin',
}

export const ROLE_LABEL: Record<UserRole, string> = {
  receptionist: 'Receptionist',
  doctor: 'Doctor',
  admin: 'Admin',
}

/** True when `path` belongs to the area the role is allowed to open. */
export function canVisit(role: UserRole, path: string): boolean {
  const home = ROLE_HOME[role]
  return path === home || path.startsWith(`${home}/`)
}
