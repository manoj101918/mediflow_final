import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { ApiError } from '@/lib/api'
import { appointmentKeys } from '@/lib/appointments'
import type { Appointment } from '@/types/api'

/**
 * A write against one appointment. Success shows `describe(result)` as a toast; failures
 * (e.g. another receptionist changed it first) show the server's message. Either way the
 * appointment lists are refetched so the screen matches the database.
 */
export function useAppointmentMutation<TVars, TResult extends Appointment = Appointment>(
  mutationFn: (vars: TVars) => Promise<TResult>,
  describe: (appointment: TResult, vars: TVars) => string,
  after?: (appointment: TResult) => void,
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: (appointment, vars) => {
      toast.success(describe(appointment, vars))
      after?.(appointment)
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Something went wrong.')
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: appointmentKeys.all }),
  })
}

export function who(appointment: Appointment): string {
  return `#${appointment.token_number} ${appointment.patient.full_name}`
}
