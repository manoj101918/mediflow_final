import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2Icon, XIcon } from 'lucide-react'
import { type KeyboardEvent, useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ApiError } from '@/lib/api'
import { recordKeys, saveMedicalProfile } from '@/lib/records'
import type { BloodGroup, MedicalProfile } from '@/types/api'

const BLOOD_GROUPS: BloodGroup[] = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']
const UNKNOWN = 'unknown'

interface Props {
  patientId: string
  profile: MedicalProfile
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function MedicalProfileDialog({ patientId, profile, open, onOpenChange }: Props) {
  const queryClient = useQueryClient()
  const [bloodGroup, setBloodGroup] = useState<string>(profile.blood_group ?? UNKNOWN)
  const [allergies, setAllergies] = useState(profile.allergies)
  const [conditions, setConditions] = useState(profile.chronic_conditions)

  const save = useMutation({
    mutationFn: () =>
      saveMedicalProfile(patientId, {
        blood_group: bloodGroup === UNKNOWN ? null : (bloodGroup as BloodGroup),
        allergies,
        chronic_conditions: conditions,
      }),
    onSuccess: () => {
      toast.success('Medical profile saved')
      void queryClient.invalidateQueries({ queryKey: recordKeys.patient(patientId) })
      onOpenChange(false)
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : 'Could not save.'),
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Allergies &amp; conditions</DialogTitle>
          <DialogDescription>
            Shown on every chart and used by the assistant when medicines are discussed.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="blood-group">Blood group</Label>
            <Select value={bloodGroup} onValueChange={setBloodGroup}>
              <SelectTrigger id="blood-group" className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={UNKNOWN}>Not known</SelectItem>
                {BLOOD_GROUPS.map((g) => (
                  <SelectItem key={g} value={g}>
                    {g}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <ChipInput
            id="allergies"
            label="Allergies"
            placeholder="e.g. Penicillin — press Enter"
            values={allergies}
            onChange={setAllergies}
            danger
          />
          <ChipInput
            id="conditions"
            label="Chronic conditions"
            placeholder="e.g. Type 2 diabetes — press Enter"
            values={conditions}
            onChange={setConditions}
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={save.isPending}>
            Cancel
          </Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending && <Loader2Icon className="animate-spin" />}
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ChipInput({
  id,
  label,
  placeholder,
  values,
  onChange,
  danger,
}: {
  id: string
  label: string
  placeholder: string
  values: string[]
  onChange: (values: string[]) => void
  danger?: boolean
}) {
  const [draft, setDraft] = useState('')

  const add = () => {
    const value = draft.trim().replace(/\s+/g, ' ')
    if (value && !values.some((v) => v.toLowerCase() === value.toLowerCase())) {
      onChange([...values, value])
    }
    setDraft('')
  }
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter' || event.key === ',') {
      event.preventDefault()
      add()
    } else if (event.key === 'Backspace' && !draft && values.length) {
      onChange(values.slice(0, -1))
    }
  }

  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <div className="flex flex-wrap gap-1.5">
        {values.map((value) => (
          <Badge
            key={value}
            variant={danger ? 'destructive' : 'secondary'}
            className="gap-1 pr-1"
          >
            {value}
            <button
              type="button"
              className="rounded-sm p-0.5 hover:bg-black/10"
              onClick={() => onChange(values.filter((v) => v !== value))}
              aria-label={`Remove ${value}`}
            >
              <XIcon className="size-3" />
            </button>
          </Badge>
        ))}
      </div>
      <Input
        id={id}
        value={draft}
        placeholder={placeholder}
        maxLength={100}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={add}
      />
    </div>
  )
}
