import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDownIcon, ArrowLeftIcon, ArrowUpIcon, PlusIcon, Trash2Icon } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { createLabTest, fetchLabTests, labAdminKeys, updateLabTest } from '@/lib/admin'
import { ApiError } from '@/lib/api'
import { LAB_CATEGORY_LABEL, LAB_SAMPLE_LABEL, LAB_SEX_LABEL, LAB_VALUE_TYPE_LABEL } from '@/lib/labs'
import type {
  LabCategory,
  LabParameterInput,
  LabRangeSex,
  LabReferenceRangeInput,
  LabSampleType,
  LabTest,
  LabTestInput,
  LabValueType,
} from '@/types/api'

// Form state keeps numbers as strings so half-typed values ("4.", "") survive re-renders.
interface RangeDraft {
  key: number
  sex: LabRangeSex
  age_min_years: string
  age_max_years: string
  low: string
  high: string
  critical_low: string
  critical_high: string
  text_normal: string
}

interface ParamDraft {
  key: number
  id: string | null
  code: string
  name: string
  unit: string
  value_type: LabValueType
  choices: string
  decimals: string
  delta_percent: string
  is_active: boolean
  ranges: RangeDraft[]
}

interface TestDraft {
  code: string
  name: string
  category: LabCategory
  sample_type: LabSampleType
  container: string
  turnaround_hours: string
  is_panel: boolean
  is_active: boolean
  sort_order: string
  parameters: ParamDraft[]
}

let nextKey = 1
const key = () => nextKey++
const str = (v: number | null | undefined) => (v === null || v === undefined ? '' : String(v))

function emptyRange(): RangeDraft {
  return {
    key: key(),
    sex: 'any',
    age_min_years: '',
    age_max_years: '',
    low: '',
    high: '',
    critical_low: '',
    critical_high: '',
    text_normal: '',
  }
}

function emptyParam(): ParamDraft {
  return {
    key: key(),
    id: null,
    code: '',
    name: '',
    unit: '',
    value_type: 'numeric',
    choices: '',
    decimals: '1',
    delta_percent: '',
    is_active: true,
    ranges: [emptyRange()],
  }
}

function toDraft(t: LabTest | undefined): TestDraft {
  if (!t) {
    return {
      code: '',
      name: '',
      category: 'biochemistry',
      sample_type: 'blood',
      container: '',
      turnaround_hours: '24',
      is_panel: false,
      is_active: true,
      sort_order: '0',
      parameters: [emptyParam()],
    }
  }
  return {
    code: t.code,
    name: t.name,
    category: t.category,
    sample_type: t.sample_type,
    container: t.container ?? '',
    turnaround_hours: String(t.turnaround_hours),
    is_panel: t.is_panel,
    is_active: t.is_active,
    sort_order: String(t.sort_order),
    parameters: t.parameters.map((p) => ({
      key: key(),
      id: p.id,
      code: p.code,
      name: p.name,
      unit: p.unit ?? '',
      value_type: p.value_type,
      choices: p.choices.join(', '),
      decimals: String(p.decimals),
      delta_percent: str(p.delta_percent),
      is_active: p.is_active,
      ranges: p.ranges.map((r) => ({
        key: key(),
        sex: r.sex,
        age_min_years: str(r.age_min_years),
        age_max_years: str(r.age_max_years),
        low: str(r.low),
        high: str(r.high),
        critical_low: str(r.critical_low),
        critical_high: str(r.critical_high),
        text_normal: r.text_normal ?? '',
      })),
    })),
  }
}

const num = (v: string) => (v.trim() === '' ? null : Number(v))

function toInput(d: TestDraft): LabTestInput {
  return {
    code: d.code.trim(),
    name: d.name.trim(),
    category: d.category,
    sample_type: d.sample_type,
    container: d.container.trim() || null,
    turnaround_hours: Number(d.turnaround_hours) || 24,
    is_panel: d.is_panel,
    is_active: d.is_active,
    sort_order: Number(d.sort_order) || 0,
    parameters: d.parameters.map(
      (p): LabParameterInput => ({
        id: p.id,
        code: p.code.trim(),
        name: p.name.trim(),
        unit: p.unit.trim() || null,
        value_type: p.value_type,
        choices:
          p.value_type === 'choice'
            ? p.choices
                .split(',')
                .map((c) => c.trim())
                .filter(Boolean)
            : [],
        decimals: Number(p.decimals) || 0,
        delta_percent: num(p.delta_percent),
        is_active: p.is_active,
        ranges: p.ranges.map(
          (r): LabReferenceRangeInput => ({
            sex: r.sex,
            age_min_years: num(r.age_min_years),
            age_max_years: num(r.age_max_years),
            low: num(r.low),
            high: num(r.high),
            critical_low: num(r.critical_low),
            critical_high: num(r.critical_high),
            text_normal: r.text_normal.trim() || null,
          }),
        ),
      }),
    ),
  }
}

function errorMessage(e: unknown): string {
  if (!(e instanceof ApiError)) return 'Something went wrong.'
  const details = (e.details ?? []) as { loc?: (string | number)[]; msg?: string }[]
  const first = Array.isArray(details) ? details[0] : undefined
  if (first) {
    const where = (first.loc ?? []).filter((x) => x !== 'body').join(' › ')
    return `${first.msg ?? e.message}${where ? ` (${where})` : ''}`
  }
  return e.message
}

function RangeRow({
  range,
  numeric,
  onChange,
  onRemove,
}: {
  range: RangeDraft
  numeric: boolean
  onChange: (r: RangeDraft) => void
  onRemove: () => void
}) {
  const field = (name: keyof RangeDraft, label: string) => (
    <Input
      aria-label={label}
      placeholder={label}
      inputMode="decimal"
      className="h-8 w-20 text-xs"
      value={range[name] as string}
      onChange={(e) => onChange({ ...range, [name]: e.target.value })}
    />
  )
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Select value={range.sex} onValueChange={(v) => onChange({ ...range, sex: v as LabRangeSex })}>
        <SelectTrigger className="h-8 w-24 text-xs" aria-label="Sex">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {Object.entries(LAB_SEX_LABEL).map(([value, label]) => (
            <SelectItem key={value} value={value}>
              {label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {field('age_min_years', 'Age from')}
      {field('age_max_years', 'Age to')}
      {numeric ? (
        <>
          {field('low', 'Low')}
          {field('high', 'High')}
          {field('critical_low', 'Crit. low')}
          {field('critical_high', 'Crit. high')}
        </>
      ) : (
        <Input
          aria-label="Normal value"
          placeholder="Normal value"
          className="h-8 w-40 text-xs"
          value={range.text_normal}
          onChange={(e) => onChange({ ...range, text_normal: e.target.value })}
        />
      )}
      <Button variant="ghost" size="icon" className="size-8" aria-label="Remove range" onClick={onRemove}>
        <Trash2Icon />
      </Button>
    </div>
  )
}

function ParameterCard({
  param,
  index,
  count,
  onChange,
  onMove,
  onRemove,
}: {
  param: ParamDraft
  index: number
  count: number
  onChange: (p: ParamDraft) => void
  onMove: (delta: number) => void
  onRemove: () => void
}) {
  const id = `param-${param.key}`
  const set = <K extends keyof ParamDraft>(name: K, value: ParamDraft[K]) => onChange({ ...param, [name]: value })
  return (
    <div className="space-y-3 rounded-lg border p-3" data-parameter-code={param.code}>
      <div className="grid gap-2 sm:grid-cols-[7rem_1fr_7rem_8rem]">
        <div className="space-y-1">
          <Label htmlFor={`${id}-code`} className="text-xs">
            Code
          </Label>
          <Input id={`${id}-code`} value={param.code} onChange={(e) => set('code', e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor={`${id}-name`} className="text-xs">
            Name
          </Label>
          <Input id={`${id}-name`} value={param.name} onChange={(e) => set('name', e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor={`${id}-unit`} className="text-xs">
            Unit
          </Label>
          <Input id={`${id}-unit`} value={param.unit} onChange={(e) => set('unit', e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor={`${id}-type`} className="text-xs">
            Value type
          </Label>
          <Select value={param.value_type} onValueChange={(v) => set('value_type', v as LabValueType)}>
            <SelectTrigger id={`${id}-type`} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(LAB_VALUE_TYPE_LABEL).map(([value, label]) => (
                <SelectItem key={value} value={value}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        {param.value_type === 'choice' ? (
          <div className="min-w-64 flex-1 space-y-1">
            <Label htmlFor={`${id}-choices`} className="text-xs">
              Choices (comma separated)
            </Label>
            <Input id={`${id}-choices`} value={param.choices} onChange={(e) => set('choices', e.target.value)} />
          </div>
        ) : param.value_type === 'numeric' ? (
          <>
            <div className="w-24 space-y-1">
              <Label htmlFor={`${id}-decimals`} className="text-xs">
                Decimals
              </Label>
              <Input
                id={`${id}-decimals`}
                inputMode="numeric"
                value={param.decimals}
                onChange={(e) => set('decimals', e.target.value)}
              />
            </div>
            <div className="w-32 space-y-1">
              <Label htmlFor={`${id}-delta`} className="text-xs">
                Delta warning %
              </Label>
              <Input
                id={`${id}-delta`}
                inputMode="decimal"
                value={param.delta_percent}
                onChange={(e) => set('delta_percent', e.target.value)}
              />
            </div>
          </>
        ) : null}
        <div className="ml-auto flex items-center gap-1">
          <Checkbox
            id={`${id}-active`}
            checked={param.is_active}
            onCheckedChange={(v) => set('is_active', v === true)}
          />
          <Label htmlFor={`${id}-active`} className="mr-2 text-xs">
            Active
          </Label>
          <Button variant="ghost" size="icon" className="size-8" aria-label="Move up" disabled={index === 0} onClick={() => onMove(-1)}>
            <ArrowUpIcon />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="size-8"
            aria-label="Move down"
            disabled={index === count - 1}
            onClick={() => onMove(1)}
          >
            <ArrowDownIcon />
          </Button>
          {param.id === null && (
            <Button variant="ghost" size="icon" className="size-8" aria-label="Remove parameter" onClick={onRemove}>
              <Trash2Icon />
            </Button>
          )}
        </div>
      </div>
      <div className="space-y-1.5">
        <p className="text-xs font-medium text-muted-foreground">
          Reference ranges (the most specific sex and age match is used)
        </p>
        {param.ranges.map((r, i) => (
          <RangeRow
            key={r.key}
            range={r}
            numeric={param.value_type === 'numeric'}
            onChange={(next) => set('ranges', param.ranges.map((x, j) => (j === i ? next : x)))}
            onRemove={() =>
              set(
                'ranges',
                param.ranges.filter((_, j) => j !== i),
              )
            }
          />
        ))}
        <Button variant="outline" size="sm" onClick={() => set('ranges', [...param.ranges, emptyRange()])}>
          <PlusIcon /> Add range
        </Button>
      </div>
    </div>
  )
}

function Editor({ test }: { test: LabTest | undefined }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<TestDraft>(() => toDraft(test))
  const set = <K extends keyof TestDraft>(name: K, value: TestDraft[K]) => setDraft((d) => ({ ...d, [name]: value }))

  const save = useMutation({
    mutationFn: () => (test ? updateLabTest(test.id, toInput(draft)) : createLabTest(toInput(draft))),
    onSuccess: (saved) => {
      toast.success(`${saved.name} saved`)
      queryClient.setQueryData<LabTest[]>(labAdminKeys.tests, (old) =>
        old ? [...old.filter((t) => t.id !== saved.id), saved] : old,
      )
      void queryClient.invalidateQueries({ queryKey: ['labs'] })
      if (!test) void navigate(`/admin/lab-tests/${saved.id}`, { replace: true })
      else setDraft(toDraft(saved))
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  const params = draft.parameters
  const updateParam = (i: number, next: ParamDraft) => set('parameters', params.map((p, j) => (j === i ? next : p)))
  const moveParam = (i: number, delta: number) => {
    const next = [...params]
    const [moved] = next.splice(i, 1)
    if (moved) next.splice(i + delta, 0, moved)
    set('parameters', next)
  }

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader>
          <CardTitle>Test</CardTitle>
          <CardDescription>Editing ranges or parameters never changes results that were already entered.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="space-y-1.5">
            <Label htmlFor="test-code">Code</Label>
            <Input id="test-code" value={draft.code} onChange={(e) => set('code', e.target.value)} />
          </div>
          <div className="space-y-1.5 sm:col-span-1 lg:col-span-3">
            <Label htmlFor="test-name">Name</Label>
            <Input id="test-name" value={draft.name} onChange={(e) => set('name', e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="test-category">Category</Label>
            <Select value={draft.category} onValueChange={(v) => set('category', v as LabCategory)}>
              <SelectTrigger id="test-category" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(LAB_CATEGORY_LABEL).map(([value, label]) => (
                  <SelectItem key={value} value={value}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="test-sample">Sample</Label>
            <Select value={draft.sample_type} onValueChange={(v) => set('sample_type', v as LabSampleType)}>
              <SelectTrigger id="test-sample" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(LAB_SAMPLE_LABEL).map(([value, label]) => (
                  <SelectItem key={value} value={value}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="test-container">Container</Label>
            <Input id="test-container" value={draft.container} onChange={(e) => set('container', e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="test-tat">Turnaround (hours)</Label>
            <Input
              id="test-tat"
              inputMode="numeric"
              value={draft.turnaround_hours}
              onChange={(e) => set('turnaround_hours', e.target.value)}
            />
          </div>
          <div className="flex items-center gap-2">
            <Checkbox id="test-panel" checked={draft.is_panel} onCheckedChange={(v) => set('is_panel', v === true)} />
            <Label htmlFor="test-panel">Panel (several parameters)</Label>
          </div>
          <div className="flex items-center gap-2">
            <Checkbox id="test-active" checked={draft.is_active} onCheckedChange={(v) => set('is_active', v === true)} />
            <Label htmlFor="test-active">Orderable</Label>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Parameters</CardTitle>
          <CardDescription>
            Results are entered per parameter. Saved parameters can be deactivated but not removed.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {params.map((p, i) => (
            <ParameterCard
              key={p.key}
              param={p}
              index={i}
              count={params.length}
              onChange={(next) => updateParam(i, next)}
              onMove={(delta) => moveParam(i, delta)}
              onRemove={() => set('parameters', params.filter((_, j) => j !== i))}
            />
          ))}
          <Button variant="outline" onClick={() => set('parameters', [...params, emptyParam()])}>
            <PlusIcon /> Add parameter
          </Button>
        </CardContent>
      </Card>

      <div className="flex justify-end gap-2">
        <Button variant="ghost" asChild>
          <Link to="/admin/lab-tests">Cancel</Link>
        </Button>
        <Button onClick={() => save.mutate()} disabled={save.isPending}>
          {save.isPending ? 'Saving…' : 'Save test'}
        </Button>
      </div>
    </div>
  )
}

export function LabTestManagePage() {
  const { testId = 'new' } = useParams()
  const isNew = testId === 'new'
  const query = useQuery({
    queryKey: labAdminKeys.tests,
    queryFn: ({ signal }) => fetchLabTests(signal),
    enabled: !isNew,
  })
  const test = query.data?.find((t) => t.id === testId)

  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <Button variant="ghost" size="sm" className="-ml-2" asChild>
        <Link to="/admin/lab-tests">
          <ArrowLeftIcon /> Lab tests
        </Link>
      </Button>
      <h1 className="text-2xl font-semibold tracking-tight">{isNew ? 'New lab test' : (test?.name ?? 'Lab test')}</h1>
      {!isNew && query.isPending ? (
        <Skeleton className="h-80" />
      ) : !isNew && !test ? (
        <p className="text-muted-foreground">This test does not exist.</p>
      ) : (
        <Editor key={test?.id ?? 'new'} test={test} />
      )}
    </div>
  )
}
