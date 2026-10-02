import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckIcon, FlaskConicalIcon, Loader2Icon } from 'lucide-react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { LabOrderStatusBadge } from '@/components/labs/LabBadges'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError } from '@/lib/api'
import { formatDate, formatTime } from '@/lib/format'
import { fetchLabInbox, labKeys, markLabReviewed } from '@/lib/labs'

/** Released results of the doctor's own orders, until marked reviewed. */
export function LabResultsInbox() {
  const queryClient = useQueryClient()
  const inbox = useQuery({ queryKey: labKeys.inbox, queryFn: ({ signal }) => fetchLabInbox(signal) })
  const review = useMutation({
    mutationFn: (orderId: string) => markLabReviewed(orderId),
    onSuccess: () => toast.success('Marked as reviewed'),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : 'Something went wrong.'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: labKeys.inbox }),
  })

  const rows = inbox.data ?? []
  return (
    <Card data-testid="lab-inbox">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FlaskConicalIcon className="size-4" />
          Lab results ({rows.length})
        </CardTitle>
        <CardDescription>New results for tests you ordered.</CardDescription>
      </CardHeader>
      <CardContent>
        {inbox.isPending ? (
          <Skeleton className="h-16" />
        ) : rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">No new results.</p>
        ) : (
          <ul className="divide-y">
            {rows.map(({ order, abnormal, critical }) => {
              const released = order.items.filter((i) => i.status === 'released')
              return (
                <li key={order.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-sm" data-lab-order-id={order.id}>
                  <Link
                    to={`/doctor/patients/${order.patient_id}?labs=${order.id}`}
                    className="font-medium hover:underline"
                  >
                    {order.patient_name}
                  </Link>
                  <span className="text-muted-foreground">
                    {order.order_number} · {released.map((i) => i.test_name).join(', ')}
                  </span>
                  <LabOrderStatusBadge status={order.status} />
                  {critical > 0 && (
                    <Badge className="bg-red-600 text-white dark:bg-red-500">{critical} critical</Badge>
                  )}
                  {abnormal > critical && (
                    <Badge className="bg-amber-100 text-amber-900 dark:bg-amber-500/20 dark:text-amber-200">
                      {abnormal - critical} abnormal
                    </Badge>
                  )}
                  <span className="ml-auto text-xs text-muted-foreground">
                    {formatDate(order.updated_at)}, {formatTime(order.updated_at)}
                  </span>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={review.isPending && review.variables === order.id}
                    onClick={() => review.mutate(order.id)}
                  >
                    {review.isPending && review.variables === order.id ? (
                      <Loader2Icon className="animate-spin" />
                    ) : (
                      <CheckIcon />
                    )}
                    Mark reviewed
                  </Button>
                </li>
              )
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
