import { useQuery } from '@tanstack/react-query'

import { fetchReports, isIngesting, reportKeys } from '@/lib/reports'

/** A patient's reports, polled every 3 s while any is still being indexed. */
export function useReports(patientId: string) {
  return useQuery({
    queryKey: reportKeys.list(patientId),
    queryFn: ({ signal }) => fetchReports(patientId, signal),
    refetchInterval: (query) =>
      query.state.data?.some((r) => isIngesting(r.ingestion_status)) ? 3000 : false,
  })
}
