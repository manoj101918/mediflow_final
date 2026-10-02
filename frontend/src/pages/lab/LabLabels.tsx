import { useQuery } from '@tanstack/react-query'
import JsBarcode from 'jsbarcode'
import { PrinterIcon } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { useParams } from 'react-router'

import { Button } from '@/components/ui/button'
import { formatDate, formatTime } from '@/lib/format'
import { fetchLabOrder, labKeys } from '@/lib/labs'
import type { LabOrderDetail, LabSample } from '@/types/api'

// Typical thermal tube label: 50 x 25 mm, one label per printed page.
const PRINT_CSS = `
@page { size: 50mm 25mm; margin: 0; }
@media print {
  body { background: #fff !important; }
  .no-print { display: none !important; }
  .label { break-after: page; box-shadow: none !important; border: 0 !important; margin: 0 !important; }
}
`

function Barcode({ code }: { code: string }) {
  const ref = useRef<SVGSVGElement>(null)
  useEffect(() => {
    if (!ref.current) return
    JsBarcode(ref.current, code, {
      format: 'CODE128',
      displayValue: true,
      fontSize: 10,
      height: 28,
      width: 1.2,
      margin: 0,
      textMargin: 1,
      background: '#ffffff',
      lineColor: '#000000',
    })
  }, [code])
  return <svg ref={ref} aria-label={`Barcode ${code}`} />
}

function Label({ detail, sample }: { detail: LabOrderDetail; sample: LabSample }) {
  const { patient } = detail
  const tests = detail.items.filter((i) => i.sample_id === sample.id).map((i) => i.test_code)
  const sex = patient.gender ? patient.gender[0]!.toUpperCase() : '-'
  return (
    <div
      className="label flex h-[25mm] w-[50mm] flex-col justify-between overflow-hidden border bg-white p-[1.5mm] text-[7pt] leading-tight text-black shadow-sm"
      data-sample-code={sample.sample_code}
    >
      <div className="flex justify-between gap-1 font-semibold">
        <span className="truncate">{patient.full_name}</span>
        <span className="shrink-0">
          {patient.age ?? '-'}/{sex}
        </span>
      </div>
      <div className="flex justify-center">
        <Barcode code={sample.sample_code} />
      </div>
      <div className="flex justify-between gap-1">
        <span className="truncate">{tests.join(', ')}</span>
        <span className="shrink-0">
          {formatDate(sample.collected_at)} {formatTime(sample.collected_at)}
        </span>
      </div>
    </div>
  )
}

/** Printable tube labels for an order's collected samples (browser print). */
export function LabLabelsPage() {
  const { orderId = '' } = useParams()
  const detail = useQuery({ queryKey: labKeys.order(orderId), queryFn: ({ signal }) => fetchLabOrder(orderId, signal) })

  if (detail.isPending) return <p className="p-6 text-sm">Loading labels…</p>
  if (detail.isError) return <p className="p-6 text-sm text-destructive">{detail.error.message}</p>
  const samples = detail.data.order.samples.filter((s) => !s.rejected_at)

  return (
    <div className="min-h-svh bg-muted/30 p-6">
      <style>{PRINT_CSS}</style>
      <div className="no-print mb-4 flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">
          Tube labels · {detail.data.order.order_number} · {detail.data.patient.full_name}
        </h1>
        <Button onClick={() => window.print()} disabled={samples.length === 0}>
          <PrinterIcon />
          Print {samples.length} label{samples.length === 1 ? '' : 's'}
        </Button>
      </div>
      {samples.length === 0 ? (
        <p className="no-print text-sm text-muted-foreground">No collected samples yet.</p>
      ) : (
        <div className="flex flex-wrap gap-3">
          {samples.map((s) => (
            <Label key={s.id} detail={detail.data} sample={s} />
          ))}
        </div>
      )}
    </div>
  )
}
