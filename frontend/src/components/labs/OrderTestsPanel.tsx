import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FlaskConicalIcon, Loader2Icon, RepeatIcon, SearchIcon, XIcon } from 'lucide-react'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'

import { LabItemStatusBadge, LabOrderStatusBadge, LabPriorityBadge } from '@/components/labs/LabBadges'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { ApiError } from '@/lib/api'
import {
  LAB_CATEGORY_LABEL,
  LAB_PRIORITY_LABEL,
  cancelLabOrder,
  createLabOrder,
  fetchLabCatalog,
  fetchLastLabOrder,
  fetchVisitLabOrders,
  labKeys,
} from '@/lib/labs'
import { cn } from '@/lib/utils'
import type { LabCategory, LabOrder, LabPriority } from '@/types/api'

const QUICK_PICKS = ['CBC', 'LIPID', 'HBA1C', 'THYROID', 'KFT', 'LFT', 'FBS', 'URINE']
const ALL = 'all'

function errorText(e: unknown) {
  return e instanceof ApiError ? e.message : 'Something went wrong.'
}

/** "Order tests" on the current visit: pick tests, set priority and a note for the lab. */
export function OrderTestsPanel({
  patientId,
  appointmentId,
  canOrder,
}: {
  patientId: string
  appointmentId: string
  /** Only while the patient is checked in / in consultation with this doctor. */
  canOrder: boolean
}) {
  const queryClient = useQueryClient()
  const catalog = useQuery({ queryKey: labKeys.catalog, queryFn: ({ signal }) => fetchLabCatalog(signal), staleTime: 300_000 })
  const orders = useQuery({
    queryKey: labKeys.visitOrders(appointmentId),
    queryFn: ({ signal }) => fetchVisitLabOrders(appointmentId, signal),
  })

  const [search, setSearch] = useState('')
  const [category, setCategory] = useState<LabCategory | typeof ALL>(ALL)
  const [selected, setSelected] = useState<string[]>([])
  const [priority, setPriority] = useState<LabPriority>('routine')
  const [note, setNote] = useState('')

  const tests = useMemo(() => catalog.data ?? [], [catalog.data])
  const byId = useMemo(() => new Map(tests.map((t) => [t.id, t])), [tests])
  const quick = useMemo(
    () => QUICK_PICKS.map((code) => tests.find((t) => t.code === code)).filter((t) => t !== undefined),
    [tests],
  )
  const matches = useMemo(() => {
    const q = search.trim().toLowerCase()
    return tests.filter(
      (t) =>
        (category === ALL || t.category === category) &&
        (!q || t.name.toLowerCase().includes(q) || t.code.toLowerCase().includes(q)),
    )
  }, [tests, search, category])

  const toggle = (id: string) =>
    setSelected((current) => (current.includes(id) ? current.filter((x) => x !== id) : [...current, id]))

  const refresh = () => queryClient.invalidateQueries({ predicate: (q) => q.queryKey.includes('labs') || q.queryKey[1] === 'lab-summary' })

  const place = useMutation({
    mutationFn: () => createLabOrder(appointmentId, { test_ids: selected, priority, clinical_note: note.trim() || null }),
    onSuccess: (order) => {
      toast.success(`Ordered ${order.items.length} test${order.items.length === 1 ? '' : 's'} (${order.order_number})`)
      setSelected([])
      setNote('')
      setPriority('routine')
    },
    onError: (e) => toast.error(errorText(e)),
    onSettled: () => refresh(),
  })

  const repeat = useMutation({
    mutationFn: () => fetchLastLabOrder(patientId),
    onSuccess: ({ test_ids }) => {
      if (test_ids.length === 0) toast.info('No earlier lab order for this patient.')
      else setSelected((current) => [...new Set([...current, ...test_ids])])
    },
    onError: (e) => toast.error(errorText(e)),
  })

  return (
    <Card data-testid="order-tests">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FlaskConicalIcon className="size-4" />
          Lab tests
        </CardTitle>
        <CardDescription>Tests ordered here go straight to the clinic lab.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {orders.data && orders.data.length > 0 && (
          <ul className="space-y-2">
            {orders.data.map((order) => (
              <VisitOrder key={order.id} order={order} canCancel={canOrder} onChanged={refresh} />
            ))}
          </ul>
        )}

        {canOrder && (
          <div className="space-y-3 rounded-lg border p-3">
            {catalog.isPending ? (
              <Skeleton className="h-24" />
            ) : (
              <>
                <div className="flex flex-wrap gap-1.5" aria-label="Common tests">
                  {quick.map((t) => (
                    <Button
                      key={t.id}
                      size="sm"
                      variant={selected.includes(t.id) ? 'default' : 'outline'}
                      className="h-7 rounded-full"
                      onClick={() => toggle(t.id)}
                      aria-pressed={selected.includes(t.id)}
                    >
                      {t.code === 'HBA1C' ? 'HbA1c' : t.name.replace(/ \(.*\)$/, '')}
                    </Button>
                  ))}
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7"
                    onClick={() => repeat.mutate()}
                    disabled={repeat.isPending}
                  >
                    {repeat.isPending ? <Loader2Icon className="animate-spin" /> : <RepeatIcon />}
                    Repeat last order
                  </Button>
                </div>
                <div className="flex flex-wrap gap-2">
                  <div className="relative min-w-48 flex-1">
                    <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      aria-label="Search lab tests"
                      placeholder="Search tests by name or code"
                      className="pl-8"
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                    />
                  </div>
                  <Select value={category} onValueChange={(v) => setCategory(v as LabCategory | typeof ALL)}>
                    <SelectTrigger className="w-40" aria-label="Test category">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={ALL}>All categories</SelectItem>
                      {Object.entries(LAB_CATEGORY_LABEL).map(([value, label]) => (
                        <SelectItem key={value} value={value}>
                          {label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                {(search || category !== ALL) && (
                  <ul className="max-h-48 space-y-0.5 overflow-y-auto rounded-md border p-1" aria-label="Matching tests">
                    {matches.length === 0 && <li className="p-2 text-sm text-muted-foreground">No tests match.</li>}
                    {matches.map((t) => (
                      <li key={t.id}>
                        <label className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-sm hover:bg-muted">
                          <Checkbox checked={selected.includes(t.id)} onCheckedChange={() => toggle(t.id)} />
                          <span className="flex-1">{t.name}</span>
                          <span className="font-mono text-xs text-muted-foreground">{t.code}</span>
                        </label>
                      </li>
                    ))}
                  </ul>
                )}
                {selected.length > 0 && (
                  <div className="flex flex-wrap gap-1.5" aria-label="Selected tests">
                    {selected.map((id) => (
                      <Badge key={id} variant="secondary" className="gap-1 pr-1" data-selected-test={byId.get(id)?.code}>
                        {byId.get(id)?.name ?? 'Test'}
                        <button
                          type="button"
                          aria-label={`Remove ${byId.get(id)?.name ?? 'test'}`}
                          className="rounded-full p-0.5 hover:bg-muted-foreground/20"
                          onClick={() => toggle(id)}
                        >
                          <XIcon className="size-3" />
                        </button>
                      </Badge>
                    ))}
                  </div>
                )}
                <div className="grid gap-3 sm:grid-cols-[10rem_1fr]">
                  <div className="space-y-1">
                    <Label htmlFor="lab-priority" className="text-xs">
                      Priority
                    </Label>
                    <Select value={priority} onValueChange={(v) => setPriority(v as LabPriority)}>
                      <SelectTrigger id="lab-priority" className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {(Object.keys(LAB_PRIORITY_LABEL) as LabPriority[]).map((p) => (
                          <SelectItem key={p} value={p}>
                            {LAB_PRIORITY_LABEL[p]}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="lab-note" className="text-xs">
                      Note for the lab (optional)
                    </Label>
                    <Textarea
                      id="lab-note"
                      rows={1}
                      maxLength={1000}
                      placeholder="e.g. diabetic, on metformin"
                      value={note}
                      onChange={(e) => setNote(e.target.value)}
                    />
                  </div>
                </div>
                <div className="flex justify-end">
                  <Button onClick={() => place.mutate()} disabled={selected.length === 0 || place.isPending}>
                    {place.isPending && <Loader2Icon className="animate-spin" />}
                    {selected.length ? `Order ${selected.length} test${selected.length === 1 ? '' : 's'}` : 'Order tests'}
                  </Button>
                </div>
              </>
            )}
          </div>
        )}
        {!canOrder && (orders.data?.length ?? 0) === 0 && (
          <p className="text-sm text-muted-foreground">Start the consultation to order tests.</p>
        )}
      </CardContent>
    </Card>
  )
}

function VisitOrder({ order, canCancel, onChanged }: { order: LabOrder; canCancel: boolean; onChanged: () => void }) {
  const cancel = useMutation({
    mutationFn: (itemId: string) => cancelLabOrder(order.id, { item_ids: [itemId], reason: null }),
    onSuccess: () => toast.success('Test cancelled'),
    onError: (e) => toast.error(errorText(e)),
    onSettled: () => onChanged(),
  })
  return (
    <li className="rounded-lg border p-2" data-lab-order-id={order.id}>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">{order.order_number}</span>
        <LabPriorityBadge priority={order.priority} hideRoutine />
        <LabOrderStatusBadge status={order.status} />
      </div>
      <ul className="mt-1 space-y-1">
        {order.items.map((item) => (
          <li key={item.id} className="flex flex-wrap items-center gap-2 text-sm" data-lab-item-id={item.id}>
            <span className={cn('flex-1', item.status === 'cancelled' && 'text-muted-foreground line-through')}>
              {item.test_name}
            </span>
            <LabItemStatusBadge status={item.status} />
            {canCancel && item.status === 'ordered' && (
              <Button
                size="sm"
                variant="ghost"
                className="h-7"
                disabled={cancel.isPending}
                onClick={() => cancel.mutate(item.id)}
                aria-label={`Cancel ${item.test_name}`}
              >
                Cancel
              </Button>
            )}
          </li>
        ))}
      </ul>
    </li>
  )
}
