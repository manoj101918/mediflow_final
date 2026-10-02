import { ArrowDownIcon, ArrowUpIcon, Loader2Icon, PlusIcon, RepeatIcon, Trash2Icon } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { type ItemDraft, emptyItem } from '@/lib/prescriptionDraft'
import { FREQUENCY_PRESETS, TIMING_LABEL } from '@/lib/records'
import { cn } from '@/lib/utils'

const NO_TIMING = 'none'
const FORMS = ['tablet', 'capsule', 'syrup', 'injection', 'ointment', 'drops', 'inhaler', 'sachet']

interface Props {
  items: ItemDraft[]
  onChange: (items: ItemDraft[]) => void
  disabled?: boolean
  onRepeatLast?: () => void
  repeatPending?: boolean
}

export function PrescriptionBuilder({ items, onChange, disabled, onRepeatLast, repeatPending }: Props) {
  const update = (key: string, patch: Partial<ItemDraft>) =>
    onChange(items.map((item) => (item.key === key ? { ...item, ...patch } : item)))
  const move = (index: number, delta: number) => {
    const next = [...items]
    const [moved] = next.splice(index, 1)
    next.splice(index + delta, 0, moved!)
    onChange(next)
  }

  return (
    <div className="space-y-2" data-testid="prescription">
      {items.length === 0 && (
        <p className="rounded-lg border border-dashed p-4 text-center text-sm text-muted-foreground">
          No medicines yet.
        </p>
      )}
      {items.map((item, index) => (
        <div
          key={item.key}
          className="grid gap-2 rounded-lg border bg-muted/20 p-2 md:grid-cols-[2fr_1fr_1fr_auto]"
          data-prescription-row={index}
        >
          <div className="grid gap-2 sm:grid-cols-[2fr_1fr_1fr]">
            <Input
              aria-label="Medicine"
              placeholder="Medicine"
              value={item.medicine_name}
              disabled={disabled}
              onChange={(e) => update(item.key, { medicine_name: e.target.value })}
            />
            <Input
              aria-label="Strength"
              placeholder="500 mg"
              value={item.strength}
              disabled={disabled}
              onChange={(e) => update(item.key, { strength: e.target.value })}
            />
            <Input
              aria-label="Form"
              placeholder="tablet"
              list="dosage-forms"
              value={item.dosage_form}
              disabled={disabled}
              onChange={(e) => update(item.key, { dosage_form: e.target.value })}
            />
          </div>
          <div className="space-y-1">
            <Input
              aria-label="Frequency"
              placeholder="1-0-1"
              value={item.frequency}
              disabled={disabled}
              onChange={(e) => update(item.key, { frequency: e.target.value })}
            />
            <div className="flex flex-wrap gap-1">
              {FREQUENCY_PRESETS.map((preset) => (
                <button
                  key={preset}
                  type="button"
                  disabled={disabled}
                  onClick={() => update(item.key, { frequency: preset })}
                  className={cn(
                    'rounded border px-1.5 text-[11px] tabular-nums hover:bg-muted',
                    item.frequency === preset && 'border-primary bg-primary/10',
                  )}
                >
                  {preset}
                </button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Select
              value={item.timing || NO_TIMING}
              disabled={disabled}
              onValueChange={(v) => update(item.key, { timing: v === NO_TIMING ? '' : v })}
            >
              <SelectTrigger aria-label="Timing" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_TIMING}>Timing…</SelectItem>
                {Object.entries(TIMING_LABEL).map(([value, label]) => (
                  <SelectItem key={value} value={value}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              aria-label="Days"
              placeholder="Days"
              inputMode="numeric"
              value={item.duration_days}
              disabled={disabled}
              onChange={(e) => update(item.key, { duration_days: e.target.value.replace(/\D/g, '') })}
            />
            <Input
              aria-label="Instructions"
              className="col-span-2"
              placeholder="Instructions (optional)"
              value={item.instructions}
              disabled={disabled}
              onChange={(e) => update(item.key, { instructions: e.target.value })}
            />
          </div>
          <div className="flex items-start gap-0.5 md:flex-col">
            <Button
              variant="ghost"
              size="icon"
              aria-label="Move up"
              disabled={disabled || index === 0}
              onClick={() => move(index, -1)}
            >
              <ArrowUpIcon />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Move down"
              disabled={disabled || index === items.length - 1}
              onClick={() => move(index, 1)}
            >
              <ArrowDownIcon />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Remove medicine"
              disabled={disabled}
              onClick={() => onChange(items.filter((i) => i.key !== item.key))}
            >
              <Trash2Icon />
            </Button>
          </div>
        </div>
      ))}
      <datalist id="dosage-forms">
        {FORMS.map((form) => (
          <option key={form} value={form} />
        ))}
      </datalist>
      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={disabled}
          onClick={() => onChange([...items, emptyItem()])}
        >
          <PlusIcon />
          Add medicine
        </Button>
        {onRepeatLast && (
          <Button variant="ghost" size="sm" disabled={disabled || repeatPending} onClick={onRepeatLast}>
            {repeatPending ? <Loader2Icon className="animate-spin" /> : <RepeatIcon />}
            Repeat last prescription
          </Button>
        )}
      </div>
    </div>
  )
}
