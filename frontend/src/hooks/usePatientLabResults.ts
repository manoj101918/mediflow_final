import { useQuery } from '@tanstack/react-query'

import { fetchPatientLabResults, labKeys } from '@/lib/labs'

/** All of a patient's lab orders (released values only), shared by the chart tabs. */
export function usePatientLabResults(patientId: string) {
  return useQuery({
    queryKey: labKeys.patientResults(patientId),
    queryFn: ({ signal }) => fetchPatientLabResults(patientId, signal),
  })
}
