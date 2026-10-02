import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FileUpIcon, Loader2Icon } from 'lucide-react'
import { type DragEvent, useRef, useState } from 'react'
import { toast } from 'sonner'

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
import { clinicDate } from '@/lib/format'
import {
  ACCEPTED_REPORT_TYPES,
  MAX_REPORT_MB,
  REPORT_TYPE_LABEL,
  REPORT_TYPES,
  reportKeys,
  uploadReport,
} from '@/lib/reports'
import { cn } from '@/lib/utils'
import type { ReportType } from '@/types/api'

const ACCEPTED = ACCEPTED_REPORT_TYPES.split(',')

interface Props {
  patientId: string
  patientName?: string
  /** Attach to the visit being written (doctor's "Attach report"). */
  consultationId?: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

function titleFrom(fileName: string): string {
  return fileName.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ').trim().slice(0, 200)
}

export function ReportUploadDialog({ patientId, patientName, consultationId, open, onOpenChange }: Props) {
  const queryClient = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [type, setType] = useState<ReportType>('lab')
  const [reportDate, setReportDate] = useState(clinicDate())
  const [dragging, setDragging] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  const choose = (picked: File | undefined) => {
    if (!picked) return
    if (!ACCEPTED.includes(picked.type)) {
      setProblem('Choose a PDF, JPEG or PNG file.')
      return
    }
    if (picked.size > MAX_REPORT_MB * 1024 * 1024) {
      setProblem(`The file is larger than ${MAX_REPORT_MB} MB.`)
      return
    }
    setProblem(null)
    setFile(picked)
    if (!title) setTitle(titleFrom(picked.name))
  }

  const upload = useMutation({
    mutationFn: () =>
      uploadReport(patientId, {
        file: file!,
        title: title.trim(),
        report_type: type,
        report_date: reportDate || null,
        consultation_id: consultationId,
      }),
    onSuccess: (report) => {
      toast.success(`Uploaded “${report.title}”`, {
        description: 'It will be searchable by the assistant in a moment.',
      })
      void queryClient.invalidateQueries({ queryKey: reportKeys.list(patientId) })
      onOpenChange(false)
    },
    onError: (error) => setProblem(error instanceof ApiError ? error.message : 'Upload failed.'),
  })

  const onDrop = (event: DragEvent<HTMLButtonElement>) => {
    event.preventDefault()
    setDragging(false)
    choose(event.dataTransfer.files[0])
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Upload report{patientName ? ` for ${patientName}` : ''}</DialogTitle>
          <DialogDescription>PDF, JPEG or PNG up to {MAX_REPORT_MB} MB.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <button
            type="button"
            className={cn(
              'flex w-full flex-col items-center gap-2 rounded-lg border-2 border-dashed p-6 text-sm',
              'text-muted-foreground transition-colors hover:bg-muted/50',
              dragging && 'border-primary bg-primary/5',
            )}
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            data-testid="report-dropzone"
          >
            <FileUpIcon className="size-6" />
            {file ? (
              <span className="font-medium text-foreground">{file.name}</span>
            ) : (
              <span>Drop a file here or click to choose</span>
            )}
          </button>
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPTED_REPORT_TYPES}
            className="hidden"
            data-testid="report-file"
            onChange={(e) => choose(e.target.files?.[0])}
          />
          <div className="space-y-1.5">
            <Label htmlFor="report-title">Title</Label>
            <Input
              id="report-title"
              value={title}
              maxLength={200}
              placeholder="e.g. HbA1c, CBC, Chest X-ray"
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="report-type">Type</Label>
              <Select value={type} onValueChange={(v) => setType(v as ReportType)}>
                <SelectTrigger id="report-type" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {REPORT_TYPES.map((t) => (
                    <SelectItem key={t} value={t}>
                      {REPORT_TYPE_LABEL[t]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="report-date">Report date</Label>
              <Input
                id="report-date"
                type="date"
                value={reportDate}
                max={clinicDate()}
                onChange={(e) => setReportDate(e.target.value)}
              />
            </div>
          </div>
          {problem && <p className="text-sm text-destructive">{problem}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={upload.isPending}>
            Cancel
          </Button>
          <Button
            onClick={() => upload.mutate()}
            disabled={!file || !title.trim() || upload.isPending}
          >
            {upload.isPending && <Loader2Icon className="animate-spin" />}
            Upload
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
