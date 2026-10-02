import { createContext, useContext } from 'react'

import type { Patient } from '@/types/api'

export type SelectedPatient = Pick<Patient, 'id' | 'full_name' | 'phone' | 'gender' | 'age'>

export interface NewAppointmentPrefill {
  patient?: SelectedPatient
  search?: string
}

export interface NewAppointmentContextValue {
  /** Open the booking sheet, optionally with the patient chosen or the search prefilled. */
  openNewAppointment: (prefill?: NewAppointmentPrefill) => void
}

export const NewAppointmentContext = createContext<NewAppointmentContextValue | null>(null)

export function useNewAppointment(): NewAppointmentContextValue {
  const value = useContext(NewAppointmentContext)
  if (!value) throw new Error('useNewAppointment must be used inside the reception layout')
  return value
}
