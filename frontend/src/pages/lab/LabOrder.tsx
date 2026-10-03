import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeftIcon, Loader2Icon, PaperclipIcon, PrinterIcon, TestTubeIcon, XCircleIcon } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link, useParams } from 'react-router'
import { toast } from 'sonner'

import { useAuth } from '@/auth/context'
import { ResultEntry } from '@/components/lab/ResultEntry'
import { LabItemStatusBadge, LabOrderStatusBadge, LabPriorityBadge } from '@/components/labs/LabBadges'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError } from '@/lib/api'
import { formatDate, formatPatientMeta, formatPhone, formatTime } from '@/lib/format'
import { LAB_SAMPLE_LABEL, attachLabPdf, cancelLabOrder, collectSamples, fetchLabOrder, labKeys, rejectSample } from '@/lib/labs'
import type { LabOrderDetail, LabSample } from '@/types/api'

const REJECT_REASONS = ['Haemolysed', 'Insufficient volume', 'Wrong container', 'Clotted', 'Unlabelled or mislabelled']
const COLLECTABLE = new Set(['ordered', 'sample_rejected'])

function errorText(e: unknown) {
  return e instanceof ApiError ? e.message : 'Something went wrong.'
}

export function LabOrderPage() {
  const { orderId = '' } = useParams()
  const { me } = useAuth()
  const queryClient = useQueryClient()
  const detail = useQuery({ queryKey: labKeys.order(orderId), queryFn: ({ signal }) => fetchLabOrder(orderId, signal) })

  const updated = (next: LabOrderDetail) => {
    queryClient.setQueryData(labKeys.order(orderId), next)
    void queryClient.invalidateQueries({ queryKey: ['labs', 'worklist'] })
  }

  const back = (
    <Button asChild variant="ghost" size="sm" className="-ml-2">
      <Link to="/lab">
        <ArrowLeftIcon />
        Worklist
      </Link>
    </Button>
  )
  if (detail.isPending) {
    return (
      <div className="mx-auto max-w-5xl space-y-4">
        {back}
        <Skeleton className="h-32" />
        <Skeleton className="h-64" />
      </div>
    )
  }
  if (detail.isError) {
    return (
      <div className="mx-auto max-w-5xl space-y-3">
        {back}
        <p className="text-sm text-destructive">{detail.error.message}</p>
      </div>
    )
  }

  const { order, patient, items, requires_verification } = detail.data
  const supervisor = me?.role === 'lab_supervisor'
  const withResults = items.filter((i) => ['sample_collected', 'result_entered', 'verified', 'released'].includes(i.status))

  return (
    <div className="mx-auto max-w-5xl space-y-4" data-lab-order-id={order.id}>
      {back}
      <Card>
        <CardContent className="flex flex-wrap items-start gap-6 pt-6">
          <div className="min-w-60 flex-1">
            <p className="text-xs tracking-wide text-muted-foreground uppercase">Patient</p>
            <p className="text-2xl font-semibold" data-testid="lab-patient-name">
              {patient.full_name}
            </p>
            <p className="text-lg">
              {formatPatientMeta(patient.gender, patient.age) || 'Age/sex not recorded'} ·{' '}
              <span className="tabular-nums">{formatPhone(patient.phone)}</span>
            </p>
          </div>
          <div className="space-y-1 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono">{order.order_number}</span>
              <LabPriorityBadge priority={order.priority} />
              <LabOrderStatusBadge status={order.status} />
            </div>
            <div className="text-muted-foreground">
              Ordered by {order.ordering_doctor_name}, {formatDate(order.created_at)} {formatTime(order.created_at)}
            </div>
            {order.clinical_note && (
              <div className="max-w-md rounded-md bg-muted px-2 py-1">
                <span className="text-xs text-muted-foreground">Doctor&apos;s note: </span>
                {order.clinical_note}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <Collection detail={detail.data} onUpdated={updated} />
      <AttachPdf orderId={order.id} />

      {withResults.map((item) => (
        <ResultEntry
          key={`${item.id}:${item.status}:${item.results.map((r) => r.id).join(',')}`}
          item={item}
          supervisor={supervisor}
          requiresVerification={requires_verification}
          onUpdated={updated}
        />
      ))}
    </div>
  )
}

function Collection({ detail, onUpdated }: { detail: LabOrderDetail; onUpdated: (d: LabOrderDetail) => void }) {
  const queryClient = useQueryClient()
  const { order, items } = detail
  const collectable = items.filter((i) => COLLECTABLE.has(i.status))
  const [chosen, setChosen] = useState<string[]>(() => collectable.map((i) => i.id))
  const [rejecting, setRejecting] = useState<LabSample | null>(null)
  const [cancelling, setCancelling] = useState(false)
  const [cancelReason, setCancelReason] = useState('')

  const collect = useMutation({
    mutationFn: () => collectSamples(order.id, chosen.filter((id) => collectable.some((i) => i.id === id))),
    onSuccess: (next) => {
      toast.success('Samples collected. Print the tube labels.')
      onUpdated(next)
      setChosen([])
    },
    onError: (e) => toast.error(errorText(e)),
  })
  const cancel = useMutation({
    mutationFn: () => cancelLabOrder(order.id, { reason: cancelReason.trim() }),
    onSuccess: () => {
      toast.success('Tests cancelled')
      setCancelling(false)
      void queryClient.invalidateQueries({ queryKey: ['labs'] })
    },
    onError: (e) => toast.error(errorText(e)),
  })

  const liveSamples = order.samples.filter((s) => !s.rejected_at)
  const orderedLeft = items.some((i) => i.status === 'ordered')
  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-2 space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <TestTubeIcon className="size-4" />
            Samples
          </CardTitle>
          <CardDescription>Confirm the patient&apos;s name, age and phone before collecting.</CardDescription>
        </div>
        {liveSamples.length > 0 && (
          <Button asChild variant="outline">
            <a href={`/lab/orders/${order.id}/labels`} target="_blank" rel="noreferrer">
              <PrinterIcon />
              Print labels
            </a>
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        <ul className="space-y-1.5">
          {items.map((item) => (
            <li key={item.id} className="flex flex-wrap items-center gap-2 text-sm" data-lab-item-id={item.id}>
              {COLLECTABLE.has(item.status) ? (
                <Checkbox
                  aria-label={`Collect ${item.test_name}`}
                  checked={chosen.includes(item.id)}
                  onCheckedChange={(v) =>
                    setChosen((c) => (v === true ? [...c, item.id] : c.filter((x) => x !== item.id)))
                  }
                />
              ) : (
                <span className="inline-block size-4" />
              )}
              <span className="flex-1">
                {item.test_name}
                <span className="text-muted-foreground">
                  {' '}
                  · {LAB_SAMPLE_LABEL[item.sample_type]}
                  {item.container ? `, ${item.container}` : ''}
                </span>
                {item.rejection_reason && item.status === 'sample_rejected' && (
                  <span className="ml-2 text-xs text-orange-700 dark:text-orange-300">Rejected: {item.rejection_reason}</span>
                )}
              </span>
              {item.sample_code && <span className="font-mono text-xs">{item.sample_code}</span>}
              <LabItemStatusBadge status={item.status} />
            </li>
          ))}
        </ul>
        <div className="flex flex-wrap gap-2">
          {collectable.length > 0 && (
            <Button onClick={() => collect.mutate()} disabled={collect.isPending || chosen.length === 0}>
              {collect.isPending ? <Loader2Icon className="animate-spin" /> : <TestTubeIcon />}
              Collect {chosen.length || ''} selected
            </Button>
          )}
          {orderedLeft && (
            <Button variant="ghost" onClick={() => setCancelling(true)}>
              <XCircleIcon />
              Cancel uncollected tests
            </Button>
          )}
        </div>

        {order.samples.length > 0 && (
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr>
                <th className="py-1 font-normal">Sample</th>
                <th className="py-1 font-normal">Type</th>
                <th className="py-1 font-normal">Collected</th>
                <th className="py-1" />
              </tr>
            </thead>
            <tbody>
              {order.samples.map((s) => {
                const rejectable = !s.rejected_at && items.some((i) => i.sample_id === s.id && i.status === 'sample_collected')
                return (
                  <tr key={s.id} className="border-t" data-sample-code={s.sample_code}>
                    <td className="py-1.5 font-mono">{s.sample_code}</td>
                    <td className="py-1.5">
                      {LAB_SAMPLE_LABEL[s.sample_type]}
                      {s.container ? `, ${s.container}` : ''}
                    </td>
                    <td className="py-1.5 text-muted-foreground">
                      {formatTime(s.collected_at)}
                      {s.rejected_at && <span className="ml-2 text-orange-700 dark:text-orange-300">Rejected: {s.rejected_reason}</span>}
                    </td>
                    <td className="py-1.5 text-right">
                      {rejectable && (
                        <Button size="sm" variant="ghost" onClick={() => setRejecting(s)}>
                          Reject
                        </Button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </CardContent>
      {rejecting && <RejectDialog sample={rejecting} onClose={() => setRejecting(null)} onUpdated={onUpdated} />}
      <Dialog open={cancelling} onOpenChange={setCancelling}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Cancel uncollected tests</DialogTitle>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="cancel-reason">Reason</Label>
            <Input id="cancel-reason" value={cancelReason} maxLength={200} onChange={(e) => setCancelReason(e.target.value)} />
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setCancelling(false)}>
              Keep
            </Button>
            <Button variant="destructive" disabled={!cancelReason.trim() || cancel.isPending} onClick={() => cancel.mutate()}>
              Cancel tests
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}

function RejectDialog({
  sample,
  onClose,
  onUpdated,
}: {
  sample: LabSample
  onClose: () => void
  onUpdated: (d: LabOrderDetail) => void
}) {
  const [choice, setChoice] = useState(REJECT_REASONS[0]!)
  const [other, setOther] = useState('')
  const reason = choice === 'other' ? other.trim() : choice
  const reject = useMutation({
    mutationFn: () => rejectSample(sample.id, reason),
    onSuccess: (next) => {
      toast.success(`Sample ${sample.sample_code} rejected; recollect the tests.`)
      onUpdated(next)
      onClose()
    },
    onError: (e) => toast.error(errorText(e)),
  })
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Reject sample {sample.sample_code}</DialogTitle>
        </DialogHeader>
        <RadioGroup value={choice} onValueChange={setChoice}>
          {[...REJECT_REASONS, 'other'].map((r) => (
            <div key={r} className="flex items-center gap-2">
              <RadioGroupItem id={`reject-${r}`} value={r} />
              <Label htmlFor={`reject-${r}`}>{r === 'other' ? 'Other' : r}</Label>
            </div>
          ))}
        </RadioGroup>
        {choice === 'other' && (
          <Input aria-label="Other reason" value={other} maxLength={500} onChange={(e) => setOther(e.target.value)} />
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="destructive" disabled={!reason || reject.isPending} onClick={() => reject.mutate()}>
            Reject sample
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function AttachPdf({ orderId }: { orderId: string }) {
  const input = useRef<HTMLInputElement>(null)
  const attach = useMutation({
    mutationFn: (file: File) => attachLabPdf(orderId, file),
    onSuccess: () => toast.success('Machine PDF attached to the order'),
    onError: (e) => toast.error(errorText(e)),
  })
  return (
    <div className="flex justify-end">
      <input
        ref={input}
        type="file"
        accept="application/pdf"
        className="hidden"
        aria-label="Lab machine PDF"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) attach.mutate(file)
          e.target.value = ''
        }}
      />
      <Button variant="ghost" size="sm" disabled={attach.isPending} onClick={() => input.current?.click()}>
        {attach.isPending ? <Loader2Icon className="animate-spin" /> : <PaperclipIcon />}
        Attach lab machine PDF
      </Button>
    </div>
  )
}
