import { useQuery } from '@tanstack/react-query'
import { type PointerEvent, useMemo, useState } from 'react'

import { FlaggedValue } from '@/components/labs/LabBadges'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatDate } from '@/lib/format'
import { LAB_FLAG_LABEL, fetchLabTrends, labKeys } from '@/lib/labs'
import type { LabTrend } from '@/types/api'

// Categorical slot 1 of the reference palette (same as the vitals charts), light / dark.
const LINE = 'stroke-[#2a78d6] dark:stroke-[#3987e5]'
const DOT = 'fill-[#2a78d6] dark:fill-[#3987e5]'
const PREFERRED = ['HBA1C', 'TSH', 'LDL', 'FBS', 'CREAT', 'HB']

/** Released numeric results over time for one parameter, reference range shaded. */
export function LabTrends({ patientId }: { patientId: string }) {
  const trends = useQuery({ queryKey: labKeys.trends(patientId), queryFn: ({ signal }) => fetchLabTrends(patientId, signal) })
  const [picked, setPicked] = useState<string | null>(null)
  const [asTable, setAsTable] = useState(false)

  if (trends.isPending) return <Skeleton className="h-64" />
  if (trends.isError) return <p className="text-sm text-destructive">{trends.error.message}</p>
  const series = trends.data
  if (series.length === 0) {
    return <p className="rounded-xl border bg-background p-6 text-sm text-muted-foreground">No released lab values yet.</p>
  }
  const fallback = PREFERRED.map((c) => series.find((s) => s.code === c)).find(Boolean) ?? series[0]!
  const current = series.find((s) => s.code === picked) ?? fallback

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Select value={current.code} onValueChange={setPicked}>
          <SelectTrigger className="w-64" aria-label="Lab parameter">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {series.map((s) => (
              <SelectItem key={s.code} value={s.code}>
                {s.name} ({s.points.length})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button variant="ghost" size="sm" className="ml-auto" onClick={() => setAsTable((t) => !t)}>
          {asTable ? 'Show chart' : 'Show as table'}
        </Button>
      </div>
      {asTable ? <TrendTable trend={current} /> : <TrendChart key={current.code} trend={current} />}
    </div>
  )
}

const W = 640
const H = 220
const PAD = { top: 16, right: 56, bottom: 26, left: 44 }

function niceTicks(min: number, max: number, count = 4): number[] {
  const span = max - min || 1
  const step = 10 ** Math.floor(Math.log10(span / count))
  const nice = [1, 2, 5, 10].map((m) => m * step).find((s) => span / s <= count) ?? step * 10
  const start = Math.ceil(min / nice) * nice
  const ticks: number[] = []
  for (let v = start; v <= max + 1e-9; v += nice) ticks.push(Number(v.toFixed(6)))
  return ticks
}

function TrendChart({ trend }: { trend: LabTrend }) {
  const [hover, setHover] = useState<number | null>(null)
  const points = trend.points
  const latest = points.at(-1)!

  const model = useMemo(() => {
    // The band is the latest result's range (the patient's current reference).
    const end = points.at(-1)!
    const band = { low: end.ref_low, high: end.ref_high }
    const times = points.map((p) => new Date(p.released_at).getTime())
    const values = points.map((p) => p.value)
    const bounds = [...values, ...(band.low !== null ? [band.low] : []), ...(band.high !== null ? [band.high] : [])]
    const [lo, hi] = [Math.min(...bounds), Math.max(...bounds)]
    const padY = (hi - lo || Math.abs(hi) || 1) * 0.15
    const yMin = Math.max(0, lo - padY)
    const yMax = hi + padY
    const [t0, t1] = [Math.min(...times), Math.max(...times)]
    const x = (t: number) =>
      t1 === t0 ? PAD.left + (W - PAD.left - PAD.right) / 2 : PAD.left + ((t - t0) / (t1 - t0)) * (W - PAD.left - PAD.right)
    const y = (v: number) => PAD.top + (1 - (v - yMin) / (yMax - yMin)) * (H - PAD.top - PAD.bottom)
    return { xs: times.map(x), y, ticks: niceTicks(yMin, yMax), yMin, yMax, band }
  }, [points])

  const { xs, y, ticks, yMin, yMax, band } = model
  const bandTop = y(Math.min(band.high ?? yMax, yMax))
  const bandBottom = y(Math.max(band.low ?? yMin, yMin))
  const d = points.map((p, i) => `${i ? 'L' : 'M'}${xs[i]},${y(p.value)}`).join(' ')
  const last = points.length - 1
  const rangeText =
    band.low !== null && band.high !== null
      ? `${band.low} - ${band.high}`
      : band.high !== null
        ? `< ${band.high}`
        : band.low !== null
          ? `> ${band.low}`
          : null

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
    <figure className="relative rounded-xl border bg-background p-3" data-lab-trend={trend.code}>
      <figcaption className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm font-medium">
          {trend.name} {trend.unit && <span className="font-normal text-muted-foreground">({trend.unit})</span>}
        </span>
        {rangeText && (
          <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            <span className="inline-block h-3 w-4 rounded-sm bg-emerald-500/15 ring-1 ring-emerald-600/30" />
            Reference {rangeText}
          </span>
        )}
      </figcaption>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="mt-1 w-full overflow-visible"
        role="img"
        aria-label={`${trend.name}: ${points.map((p) => `${p.value} on ${formatDate(p.released_at)}`).join(', ')}`}
      >
        {(band.low !== null || band.high !== null) && bandBottom > bandTop && (
          <rect
            x={PAD.left}
            width={W - PAD.left - PAD.right}
            y={bandTop}
            height={bandBottom - bandTop}
            className="fill-emerald-500/10 dark:fill-emerald-400/10"
          />
        )}
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className="stroke-border" strokeWidth={1} />
            <text x={PAD.left - 6} y={y(t)} dy="0.32em" textAnchor="end" className="fill-muted-foreground text-[10px] tabular-nums">
              {t}
            </text>
          </g>
        ))}
        <text x={xs[0]} y={H - 6} textAnchor={points.length > 1 ? 'start' : 'middle'} className="fill-muted-foreground text-[10px]">
          {formatDate(points[0]!.released_at)}
        </text>
        {points.length > 1 && (
          <text x={xs[last]} y={H - 6} textAnchor="end" className="fill-muted-foreground text-[10px]">
            {formatDate(latest.released_at)}
          </text>
        )}
        {hover != null && (
          <line x1={xs[hover]} x2={xs[hover]} y1={PAD.top} y2={H - PAD.bottom} className="stroke-muted-foreground/60" strokeWidth={1} />
        )}
        <path d={d} fill="none" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" className={LINE} />
        {points.map((p, i) => (
          <circle key={p.order_item_id} cx={xs[i]} cy={y(p.value)} r={4.5} strokeWidth={2} className={`stroke-background ${DOT}`} data-flag={p.flag ?? ''} />
        ))}
        <text x={xs[last]! + 9} y={y(latest.value)} dy="0.32em" className="fill-foreground text-[11px] font-medium tabular-nums">
          {latest.value}
        </text>
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
          className="pointer-events-none absolute top-10 z-10 rounded-md border bg-popover px-2 py-1 text-xs shadow-md"
          style={{
            left: `calc(${(xs[hover]! / W) * 100}% + 12px)`,
            transform: xs[hover]! > W / 2 ? 'translateX(calc(-100% - 24px))' : undefined,
          }}
        >
          <div className="font-medium">{formatDate(points[hover]!.released_at)}</div>
          <div className="tabular-nums">
            {points[hover]!.value} {trend.unit}
            {points[hover]!.flag && points[hover]!.flag !== 'normal' && ` · ${LAB_FLAG_LABEL[points[hover]!.flag!]}`}
          </div>
          <div className="text-muted-foreground">{points[hover]!.order_number}</div>
        </div>
      )}
    </figure>
  )
}

function TrendTable({ trend }: { trend: LabTrend }) {
  return (
    <div className="rounded-xl border bg-background">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Date</TableHead>
            <TableHead>{trend.name}</TableHead>
            <TableHead>Reference</TableHead>
            <TableHead>Order</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {[...trend.points].reverse().map((p) => (
            <TableRow key={p.order_item_id}>
              <TableCell>{formatDate(p.released_at)}</TableCell>
              <TableCell>
                <FlaggedValue value={String(p.value)} flag={p.flag} /> {trend.unit}
              </TableCell>
              <TableCell className="text-muted-foreground">
                {p.ref_low ?? ''}
                {p.ref_low !== null && p.ref_high !== null ? ' - ' : ''}
                {p.ref_high ?? ''}
              </TableCell>
              <TableCell className="font-mono text-xs">{p.order_number}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
