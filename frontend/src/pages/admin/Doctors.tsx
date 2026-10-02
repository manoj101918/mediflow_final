import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronRightIcon, PlusIcon } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { toast } from 'sonner'

import { DoctorForm } from '@/components/admin/DoctorForm'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { adminKeys, createDoctor, fetchAllDoctors } from '@/lib/admin'
import { cn } from '@/lib/utils'
import type { DoctorInput } from '@/types/api'

export function AdminDoctorsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [adding, setAdding] = useState(false)
  const query = useQuery({ queryKey: adminKeys.doctors, queryFn: ({ signal }) => fetchAllDoctors(signal) })

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Doctors</h1>
          <p className="text-sm text-muted-foreground">Profiles, weekly hours and leave. Inactive doctors cannot be booked.</p>
        </div>
        <Button onClick={() => setAdding(true)}>
          <PlusIcon /> Add doctor
        </Button>
      </div>

      <div className="overflow-hidden rounded-xl border bg-background">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/50 hover:bg-muted/50">
              <TableHead>Name</TableHead>
              <TableHead className="hidden sm:table-cell">Fee</TableHead>
              <TableHead className="hidden sm:table-cell">Slot</TableHead>
              <TableHead className="hidden md:table-cell">Days / week</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {query.isPending
              ? Array.from({ length: 3 }, (_, i) => (
                  <TableRow key={i}>
                    <TableCell colSpan={6}>
                      <Skeleton className="h-6" />
                    </TableCell>
                  </TableRow>
                ))
              : query.data?.map((d) => (
                  <TableRow
                    key={d.id}
                    className={cn('cursor-pointer', !d.is_active && 'text-muted-foreground')}
                    tabIndex={0}
                    onClick={() => navigate(`/admin/doctors/${d.id}`)}
                    onKeyDown={(e) => e.key === 'Enter' && navigate(`/admin/doctors/${d.id}`)}
                  >
                    <TableCell>
                      <div className="font-medium text-foreground">{d.full_name}</div>
                      <div className="text-xs text-muted-foreground">{d.specialization}</div>
                    </TableCell>
                    <TableCell className="hidden sm:table-cell">₹{d.consultation_fee}</TableCell>
                    <TableCell className="hidden sm:table-cell">{d.default_slot_minutes} min</TableCell>
                    <TableCell className="hidden md:table-cell">{new Set(d.schedules.map((s) => s.weekday)).size}</TableCell>
                    <TableCell className="space-x-1">
                      {d.is_active ? (
                        <Badge className="bg-emerald-100 text-emerald-900 dark:bg-emerald-500/20 dark:text-emerald-200">Active</Badge>
                      ) : (
                        <Badge variant="outline">Inactive</Badge>
                      )}
                      {!d.profile_id && (
                        <Badge variant="outline" className="text-muted-foreground">
                          No login
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      <Link to={`/admin/doctors/${d.id}`} aria-label={`Manage ${d.full_name}`} onClick={(e) => e.stopPropagation()}>
                        <ChevronRightIcon className="size-4 text-muted-foreground" />
                      </Link>
                    </TableCell>
                  </TableRow>
                ))}
          </TableBody>
        </Table>
      </div>

      <Dialog open={adding} onOpenChange={setAdding}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Add doctor</DialogTitle>
            <DialogDescription>Set weekly hours on the next screen.</DialogDescription>
          </DialogHeader>
          <DoctorForm
            submitLabel="Add doctor"
            onCancel={() => setAdding(false)}
            onSubmit={async (input) => {
              const doctor = await createDoctor(input as DoctorInput)
              await queryClient.invalidateQueries({ queryKey: ['doctors'] })
              toast.success(`Added ${doctor.full_name}`)
              setAdding(false)
              navigate(`/admin/doctors/${doctor.id}`)
            }}
          />
        </DialogContent>
      </Dialog>
    </div>
  )
}
