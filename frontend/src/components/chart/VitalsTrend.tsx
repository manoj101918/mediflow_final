import { useQuery } from '@tanstack/react-query'
import { type PointerEvent, useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatDate } from '@/lib/format'
import { fetchVitals, recordKeys } from '@/lib/records'
import { cn } from '@/lib/utils'
import type { Vitals, VitalsPoint } from '@/types/api'

// Categorical slots 1-2 of the reference palette, light / dark steps (validated together).
const SERIES_STYLE = [
  { stroke: 'stroke-[#2a78d6] dark:stroke-[#3987e5]', fill: 'fill-[#2a78d6] dark:fill-[#3987e5]', bg: 'bg-[#2a78d6] dark:bg-[#3987e5]' },
  { stroke: 'stroke-[#eb6834] dark:stroke-[#d95926]', fill: 'fill-[#eb6834] dark:fill-[#d95926]', bg: 'bg-[#eb6834] dark:bg-[#d95926]' },
] as const

interface SeriesDef {
  key: keyof Vitals
  label: string
}

interface ChartDef {
  title: string
  unit: string
  series: SeriesDef[]
}

const CHARTS: ChartDef[] = [
  {
    title: 'Blood pressure',
    unit: 'mmHg',
    series: [
      { key: 'bp_systolic', label: 'Systolic' },
      { key: 'bp_diastolic', label: 'Diastolic' },
    ],
  },
  { title: 'Weight', unit: 'kg', series: [{ key: 'weight_kg', label: 'Weight' }] },
  { title: 'Blood sugar', unit: 'mg/dL', series: [{ key: 'blood_sugar', label: 'Blood sugar' }] },
]

export function VitalsTrend({ patientId }: { patientId: string }) {
  const vitals = useQuery({
    queryKey: recordKeys.vitals(patientId),
    queryFn: ({ signal }) => fetchVitals(patientId, signal),
  })
  const [asTable, setAsTable] = useState(false)

  if (vitals.isPending) return <Skeleton className="h-48" />
  if (vitals.isError) return <p className="text-sm text-destructive">{vitals.error.message}</p>
  if (vitals.data.length === 0) {
    return <p className="rounded-xl border bg-background p-6 text-sm text-muted-foreground">No vitals recorded at previous visits.</p>
  }

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <Button variant="ghost" size="sm" onClick={() => setAsTable((t) => !t)}>
          {asTable ? 'Show charts' : 'Show as table'}
        </Button>
      </div>
      {asTable ? (
        <VitalsTable points={vitals.data} />
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {CHARTS.map((chart) => (
            <TrendChart key={chart.title} chart={chart} points={vitals.data} />
          ))}
        </div>
      )}
    </div>
  )
}

// --- One small chart ---------------------------------------------------------------------------

const W = 320
const H = 150
const PAD = { top: 12, right: 44, bottom: 22, left: 36 }

function niceTicks(min: number, max: number, count = 3): number[] {
  const span = max - min || 1
  const step = 10 ** Math.floor(Math.log10(span / count))
  const nice = [1, 2, 5, 10].map((m) => m * step).find((s) => span / s <= count) ?? step * 10
  const start = Math.ceil(min / nice) * nice
  const ticks: number[] = []
  for (let v = start; v <= max + 1e-9; v += nice) ticks.push(Number(v.toFixed(6)))
  return ticks
}

function TrendChart({ chart, points }: { chart: ChartDef; points: VitalsPoint[] }) {
  const [hover, setHover] = useState<number | null>(null)

  const model = useMemo(() => {
    const rows = points.filter((p) => chart.series.some((s) => p.vitals[s.key] != null))
    const values = rows.flatMap((p) =>
      chart.series.map((s) => p.vitals[s.key]).filter((v): v is number => v != null),
    )
    if (rows.length === 0) return null
    const times = rows.map((p) => new Date(`${p.visit_date}T12:00:00Z`).getTime())
    const [t0, t1] = [Math.min(...times), Math.max(...times)]
    const [lo, hi] = [Math.min(...values), Math.max(...values)]
    const padY = (hi - lo || Math.abs(hi) || 1) * 0.15
    const yMin = lo - padY
    const yMax = hi + padY
    const x = (t: number) =>
      t1 === t0
        ? PAD.left + (W - PAD.left - PAD.right) / 2
        : PAD.left + ((t - t0) / (t1 - t0)) * (W - PAD.left - PAD.right)
    const y = (v: number) => PAD.top + (1 - (v - yMin) / (yMax - yMin)) * (H - PAD.top - PAD.bottom)
    return { rows, xs: times.map(x), y, ticks: niceTicks(yMin, yMax) }
  }, [chart, points])

  if (!model) {
    return (
      <figure className="rounded-xl border bg-background p-3">
        <figcaption className="text-sm font-medium">{chart.title}</figcaption>
        <p className="py-8 text-center text-sm text-muted-foreground">Not recorded</p>
      </figure>
    )
  }
  const { rows, xs, y, ticks } = model
  const last = rows.length - 1

  const onMove = (event: PointerEvent<SVGRectElement>) => {
    const rect = event.currentTarget.ownerSVGElement!.getBoundingClientRect()
    const px = ((event.clientX - rect.left) / rect.width) * W
    let best = 0
    xs.forEach((x, i) => {
      if (Math.abs(x - px) < Math.abs(xs[best]! - px)) best = i
    })
    setHover(best)
  }

  return (
    <figure className="relative rounded-xl border bg-background p-3" data-vitals-chart={chart.title}>
      <figcaption className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm font-medium">
          {chart.title} <span className="font-normal text-muted-foreground">({chart.unit})</span>
        </span>
        {chart.series.length > 1 && (
          <span className="flex gap-3 text-xs text-muted-foreground">
            {chart.series.map((s, i) => (
              <span key={s.key} className="inline-flex items-center gap-1">
                <span className={cn('h-0.5 w-3 rounded-full', SERIES_STYLE[i]!.bg)} />
                {s.label}
              </span>
            ))}
          </span>
        )}
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} className="mt-1 w-full overflow-visible" role="img" aria-label={`${chart.title} over ${rows.length} visits`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className="stroke-border" strokeWidth={1} />
            <text x={PAD.left - 6} y={y(t)} dy="0.32em" textAnchor="end" className="fill-muted-foreground text-[10px] tabular-nums">
              {t}
            </text>
          </g>
        ))}
        <text x={xs[0]} y={H - 4} textAnchor={rows.length > 1 ? 'start' : 'middle'} className="fill-muted-foreground text-[10px]">
          {formatDate(rows[0]!.visit_date)}
        </text>
        {rows.length > 1 && (
          <text x={xs[last]} y={H - 4} textAnchor="end" className="fill-muted-foreground text-[10px]">
            {formatDate(rows[last]!.visit_date)}
          </text>
        )}
        {hover != null && (
          <line x1={xs[hover]} x2={xs[hover]} y1={PAD.top} y2={H - PAD.bottom} className="stroke-muted-foreground/60" strokeWidth={1} />
        )}
        {chart.series.map((s, si) => {
          const pts = rows
            .map((p, i) => [xs[i]!, p.vitals[s.key]] as const)
            .filter((pt): pt is readonly [number, number] => pt[1] != null)
          const d = pts.map(([px, v], i) => `${i ? 'L' : 'M'}${px},${y(v)}`).join(' ')
          const end = pts.at(-1)
          return (
            <g key={s.key}>
              <path d={d} fill="none" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" className={SERIES_STYLE[si]!.stroke} />
              {pts.map(([px, v], i) => (
                <circle key={i} cx={px} cy={y(v)} r={4} strokeWidth={2} className={cn('stroke-background', SERIES_STYLE[si]!.fill)} />
              ))}
              {end && (
                <text x={end[0] + 8} y={y(end[1])} dy="0.32em" className="fill-foreground text-[11px] font-medium tabular-nums">
                  {end[1]}
                </text>
              )}
            </g>
          )
        })}
        <rect
          x={PAD.left - 8}
          y={0}
          width={W - PAD.left - PAD.right + 16}
          height={H}
          fill="transparent"
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
        />
      </svg>
      {hover != null && (
        <div
          className="pointer-events-none absolute top-8 z-10 rounded-md border bg-popover px-2 py-1 text-xs shadow-md"
          style={{
            left: `calc(${(xs[hover]! / W) * 100}% + 12px)`,
            transform: xs[hover]! > W / 2 ? 'translateX(calc(-100% - 24px))' : undefined,
          }}
        >
          <div className="font-medium">{formatDate(rows[hover]!.visit_date)}</div>
          {chart.series.map((s, i) => (
            <div key={s.key} className="flex items-center gap-1.5 tabular-nums">
              <span className={cn('h-0.5 w-3 rounded-full', SERIES_STYLE[i]!.bg)} />
              {s.label}: {rows[hover]!.vitals[s.key] ?? '—'}
            </div>
          ))}
        </div>
      )}
    </figure>
  )
}

function VitalsTable({ points }: { points: VitalsPoint[] }) {
  const cols: { key: keyof Vitals; label: string }[] = [
    { key: 'bp_systolic', label: 'BP sys' },
    { key: 'bp_diastolic', label: 'BP dia' },
    { key: 'pulse', label: 'Pulse' },
    { key: 'temperature_c', label: 'Temp °C' },
    { key: 'spo2', label: 'SpO₂ %' },
    { key: 'weight_kg', label: 'Weight kg' },
    { key: 'blood_sugar', label: 'Sugar mg/dL' },
  ]
  return (
    <div className="rounded-xl border bg-background">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Visit</TableHead>
            {cols.map((c) => (
              <TableHead key={c.key} className="text-right">
                {c.label}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {[...points].reverse().map((p) => (
            <TableRow key={p.consultation_id}>
              <TableCell>{formatDate(p.visit_date)}</TableCell>
              {cols.map((c) => (
                <TableCell key={c.key} className="text-right tabular-nums">
                  {p.vitals[c.key] ?? '—'}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
