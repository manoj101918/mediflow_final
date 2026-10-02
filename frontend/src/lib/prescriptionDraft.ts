import type { PrescriptionItem } from '@/types/api'

/** One editable prescription row; every field is a string while editing. */
export interface ItemDraft {
  key: string
  medicine_name: string
  strength: string
  dosage_form: string
  dose: string
  route: string
  frequency: string
  timing: string
  duration_days: string
  instructions: string
}

let nextKey = 0
const newKey = () => `item-${++nextKey}`

export function emptyItem(): ItemDraft {
  return {
    key: newKey(),
    medicine_name: '',
    strength: '',
    dosage_form: 'tablet',
    dose: '',
    route: '',
    frequency: '1-0-1',
    timing: 'after_food',
    duration_days: '',
    instructions: '',
  }
}

export function itemFromServer(item: PrescriptionItem): ItemDraft {
  return {
    key: newKey(),
    medicine_name: item.medicine_name,
    strength: item.strength ?? '',
    dosage_form: item.dosage_form ?? '',
    dose: item.dose ?? '',
    route: item.route ?? '',
    frequency: item.frequency ?? '',
    timing: item.timing ?? '',
    duration_days: item.duration_days ? String(item.duration_days) : '',
    instructions: item.instructions ?? '',
  }
}
