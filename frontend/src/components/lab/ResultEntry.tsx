import { useMutation } from '@tanstack/react-query'
import { AlertTriangleIcon, CheckCheckIcon, Loader2Icon, PencilIcon, SaveIcon, SendIcon, Undo2Icon } from 'lucide-react'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'

import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { FlaggedValue, LabItemStatusBadge } from '@/components/labs/LabBadges'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { ApiError } from '@/lib/api'
import { formatDate } from '@/lib/format'
import {
  LAB_FLAG_LABEL,
  amendLabItem,
  flagValue,
  formatResultValue,
  isCritical,
  labItemAction,
  saveLabResults,
  sendBackLabItem,
} from '@/lib/labs'
import { cn } from '@/lib/utils'
import type { LabFlag, LabItemDetail, LabOrderDetail, LabParameterEntry, LabValueInput } from '@/types/api'

const NONE = '__none__'

interface Props {
  item: LabItemDetail
  supervisor: boolean
  requiresVerification: boolean
  onUpdated: (detail: LabOrderDetail) => void
}

function errorText(e: unknown) {
  return e instanceof ApiError ? e.message : 'Something went wrong.'
}

function initialValues(item: LabItemDetail): Record<string, string> {
  const out: Record<string, string> = {}
  for (const r of item.results) out[r.parameter_id] = formatResultValue(r)
  return out
}

function deltaWarning(p: LabParameterEntry, raw: string): boolean {
  if (p.value_type !== 'numeric' || !p.previous || p.previous.value_numeric === null || !p.delta_percent) return false
  const value = Number(raw)
  if (!raw.trim() || !Number.isFinite(value)) return false
  const prev = p.previous.value_numeric
  if (prev === 0) return value !== 0
  return (Math.abs(value - prev) / Math.abs(prev)) * 100 > p.delta_percent
}

/** One test's result form: live flags against the patient's range, delta check, workflow buttons. */
export function ResultEntry({ item, supervisor, requiresVerification, onUpdated }: Props) {
  const [values, setValues] = useState<Record<string, string>>(() => initialValues(item))
  const [amending, setAmending] = useState(false)
  const [reason, setReason] = useState('')
  const [sendingBack, setSendingBack] = useState(false)
  const [comment, setComment] = useState('')
  const [confirmCritical, setConfirmCritical] = useState<null | (() => void)>(null)

  const editable = item.status === 'sample_collected' || amending
  const canRelease = supervisor || !requiresVerification
  const flags = useMemo(() => {
    const out: Record<string, LabFlag | null> = {}
    for (const p of item.parameters) out[p.id] = flagValue(p.value_type, values[p.id] ?? '', p.range)
    return out
  }, [item.parameters, values])
  const criticalNames = item.parameters.filter((p) => isCritical(flags[p.id])).map((p) => p.name)

  const payload = (): LabValueInput[] =>
    item.parameters
      .filter((p) => (values[p.id] ?? '') !== '' || item.results.some((r) => r.parameter_id === p.id))
      .map((p) => {
        const raw = (values[p.id] ?? '').trim()
        return { parameter_id: p.id, value: raw === '' ? null : p.value_type === 'numeric' ? Number(raw) : raw }
      })

  const run = useMutation({
    mutationFn: async (step: 'save' | 'submit' | 'release' | 'verify' | 'amend' | 'send-back') => {
      const confirmed = criticalNames.length > 0
      if (step === 'amend') return amendLabItem(item.id, payload().filter((v) => v.value !== null), reason.trim())
      if (step === 'verify') return labItemAction(item.id, 'verify')
      if (step === 'send-back') return sendBackLabItem(item.id, comment.trim())
      if (item.status === 'result_entered' && step === 'release') return labItemAction(item.id, 'release')
      let detail = await saveLabResults(item.id, payload(), confirmed)
      if (step === 'submit' || step === 'release') detail = await labItemAction(item.id, 'submit')
      if (step === 'release') detail = await labItemAction(item.id, 'release')
      return detail
    },
    onSuccess: (detail, step) => {
      const messages = {
        save: 'Draft saved',
        submit: 'Submitted for verification',
        release: 'Results released to the doctor',
        verify: 'Verified and released to the doctor',
        amend: 'Amendment released',
        'send-back': 'Sent back to the technician',
      }
      toast.success(messages[step])
      setAmending(false)
      setReason('')
      setSendingBack(false)
      setComment('')
      onUpdated(detail)
    },
    onError: (e) => toast.error(errorText(e)),
  })

  /** Critical values need an explicit confirmation before they are saved. */
  const guarded = (step: 'save' | 'submit' | 'release' | 'amend') => {
    if (criticalNames.length > 0) setConfirmCritical(() => () => run.mutate(step))
    else run.mutate(step)
  }

  const busy = run.isPending
  return (
    <Card data-lab-item-id={item.id} data-lab-item-status={item.status}>
      <CardHeader className="flex flex-row flex-wrap items-center gap-2 space-y-0">
        <CardTitle className="text-base">{item.test_name}</CardTitle>
        <LabItemStatusBadge status={item.status} />
        {item.sample_code && <span className="font-mono text-xs text-muted-foreground">{item.sample_code}</span>}
      </CardHeader>
      <CardContent className="space-y-3">
        {item.return_comment && item.status === 'sample_collected' && (
          <p className="rounded-md bg-amber-50 p-2 text-sm text-amber-900 dark:bg-amber-500/10 dark:text-amber-200">
            Sent back: {item.return_comment}
          </p>
        )}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr>
                <th className="py-1 pr-2 font-normal">Parameter</th>
                <th className="py-1 pr-2 font-normal">Result</th>
                <th className="py-1 pr-2 font-normal">Unit</th>
                <th className="py-1 pr-2 font-normal">Reference</th>
                <th className="py-1 font-normal">Previous</th>
              </tr>
            </thead>
            <tbody>
              {item.parameters.map((p) => {
                const raw = values[p.id] ?? ''
                const flag = flags[p.id] ?? null
                const delta = deltaWarning(p, raw)
                return (
                  <tr key={p.id} className="border-t align-middle" data-parameter={p.code}>
                    <td className="py-1.5 pr-2">{p.name}</td>
                    <td className="py-1.5 pr-2">
                      {editable ? (
                        <div className="flex items-center gap-2">
                          <ValueInput param={p} value={raw} onChange={(v) => setValues((s) => ({ ...s, [p.id]: v }))} />
                          {flag && flag !== 'normal' && (
                            <span className={cn('text-xs font-semibold', isCritical(flag) ? 'text-red-700 dark:text-red-400' : 'text-amber-700 dark:text-amber-400')} data-live-flag={flag}>
                              {isCritical(flag) && <AlertTriangleIcon className="mr-0.5 inline size-3.5" />}
                              {LAB_FLAG_LABEL[flag]}
                            </span>
                          )}
                        </div>
                      ) : raw ? (
                        <FlaggedValue value={raw} flag={item.results.find((r) => r.parameter_id === p.id)?.flag ?? flag} />
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="py-1.5 pr-2 text-muted-foreground">{p.unit}</td>
                    <td className="py-1.5 pr-2 text-muted-foreground">{p.range?.label ?? ''}</td>
                    <td className="py-1.5 text-xs text-muted-foreground">
                      {p.previous && (
                        <span title={`Order ${p.previous.order_number}`}>
                          {formatResultValue(p.previous)} ({formatDate(p.previous.released_at)})
                        </span>
                      )}
                      {delta && (
                        <span className="ml-1 font-semibold text-amber-700 dark:text-amber-400" data-delta-warning>
                          Large change, please check
                        </span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {amending && (
          <Textarea
            aria-label="Reason for amendment"
            placeholder="Reason for the correction (shown on the amended report)"
            rows={2}
            maxLength={1000}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        )}
        {sendingBack && (
          <Textarea
            aria-label="What should be checked"
            placeholder="What should the technician check?"
            rows={2}
            maxLength={1000}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
        )}

        <div className="flex flex-wrap justify-end gap-2">
          {item.status === 'sample_collected' && (
            <>
              <Button variant="outline" onClick={() => guarded('save')} disabled={busy}>
                <SaveIcon />
                Save draft
              </Button>
              {requiresVerification ? (
                <Button onClick={() => guarded('submit')} disabled={busy}>
                  {busy ? <Loader2Icon className="animate-spin" /> : <SendIcon />}
                  Submit for verification
                </Button>
              ) : (
                <Button onClick={() => guarded('release')} disabled={busy}>
                  {busy ? <Loader2Icon className="animate-spin" /> : <CheckCheckIcon />}
                  Release
                </Button>
              )}
            </>
          )}
          {item.status === 'result_entered' && supervisor && !sendingBack && (
            <>
              <Button variant="outline" onClick={() => setSendingBack(true)} disabled={busy}>
                <Undo2Icon />
                Send back
              </Button>
              <Button onClick={() => run.mutate('verify')} disabled={busy}>
                {busy ? <Loader2Icon className="animate-spin" /> : <CheckCheckIcon />}
                Verify and release
              </Button>
            </>
          )}
          {item.status === 'result_entered' && !supervisor && requiresVerification && (
            <p className="text-sm text-muted-foreground">Waiting for a lab supervisor to verify.</p>
          )}
          {item.status === 'result_entered' && !requiresVerification && !supervisor && (
            <Button onClick={() => run.mutate('release')} disabled={busy}>
              <CheckCheckIcon />
              Release
            </Button>
          )}
          {sendingBack && (
            <>
              <Button variant="ghost" onClick={() => setSendingBack(false)}>
                Cancel
              </Button>
              <Button onClick={() => run.mutate('send-back')} disabled={busy || !comment.trim()}>
                Send back
              </Button>
            </>
          )}
          {item.status === 'released' && canRelease && !amending && (
            <Button variant="outline" onClick={() => setAmending(true)}>
              <PencilIcon />
              Amend
            </Button>
          )}
          {amending && (
            <>
              <Button
                variant="ghost"
                onClick={() => {
                  setAmending(false)
                  setValues(initialValues(item))
                }}
              >
                Cancel
              </Button>
              <Button onClick={() => guarded('amend')} disabled={busy || !reason.trim()}>
                Release amendment
              </Button>
            </>
          )}
        </div>
      </CardContent>
      <ConfirmDialog
        open={confirmCritical !== null}
        onOpenChange={(open) => !open && setConfirmCritical(null)}
        title="Confirm critical values"
        description={`These values are beyond the critical limits: ${criticalNames.join(', ')}. The ordering doctor will be alerted immediately once they are released. Re-check the sample and the entry before continuing.`}
        confirmLabel="Values are correct"
        destructive
        onConfirm={() => {
          confirmCritical?.()
          setConfirmCritical(null)
        }}
      />
    </Card>
  )
}

function ValueInput({ param, value, onChange }: { param: LabParameterEntry; value: string; onChange: (v: string) => void }) {
  if (param.value_type === 'choice') {
    return (
      <Select value={value || NONE} onValueChange={(v) => onChange(v === NONE ? '' : v)}>
        <SelectTrigger className="h-8 w-40" aria-label={param.name}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NONE}>Not reported</SelectItem>
          {param.choices.map((c) => (
            <SelectItem key={c} value={c}>
              {c}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    )
  }
  return (
    <Input
      aria-label={param.name}
      className="h-8 w-28 tabular-nums"
      inputMode={param.value_type === 'numeric' ? 'decimal' : 'text'}
      value={value}
      onChange={(e) => onChange(param.value_type === 'numeric' ? e.target.value.replace(/[^\d.-]/g, '') : e.target.value)}
    />
  )
}
