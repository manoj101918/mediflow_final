import type { LabCategory, LabRangeSex, LabSampleType, LabValueType } from '@/types/api'

export const LAB_CATEGORY_LABEL: Record<LabCategory, string> = {
  haematology: 'Haematology',
  biochemistry: 'Biochemistry',
  hormones: 'Hormones',
  urine: 'Urine',
  serology: 'Serology',
  other: 'Other',
}

export const LAB_SAMPLE_LABEL: Record<LabSampleType, string> = {
  blood: 'Blood',
  urine: 'Urine',
  stool: 'Stool',
  swab: 'Swab',
  other: 'Other',
}

export const LAB_VALUE_TYPE_LABEL: Record<LabValueType, string> = {
  numeric: 'Number',
  text: 'Text',
  choice: 'Choice',
}

export const LAB_SEX_LABEL: Record<LabRangeSex, string> = {
  any: 'Any',
  male: 'Male',
  female: 'Female',
}
