// Hand-written mirrors of the FastAPI response models (backend/app/schemas).
import type { Database } from '@/types/database'

export type UserRole = Database['public']['Enums']['user_role']

export interface Clinic {
  id: string
  name: string
  timezone: string
}

export interface Me {
  id: string
  email: string | null
  full_name: string
  role: UserRole
  clinic: Clinic
  doctor_id: string | null
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: unknown }
}
