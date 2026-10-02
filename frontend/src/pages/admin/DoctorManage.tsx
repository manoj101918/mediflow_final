import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeftIcon } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { toast } from 'sonner'

import { DoctorForm } from '@/components/admin/DoctorForm'
import { LeaveManager } from '@/components/admin/LeaveManager'
import { ScheduleEditor } from '@/components/admin/ScheduleEditor'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { adminKeys, fetchAllDoctors, updateDoctor } from '@/lib/admin'
import { ApiError } from '@/lib/api'

export function DoctorManagePage() {
  const { doctorId = '' } = useParams()
  const queryClient = useQueryClient()
  const [confirmDeactivate, setConfirmDeactivate] = useState(false)
  const query = useQuery({ queryKey: adminKeys.doctors, queryFn: ({ signal }) => fetchAllDoctors(signal) })
  const doctor = query.data?.find((d) => d.id === doctorId)

  const setActive = useMutation({
    mutationFn: (active: boolean) => updateDoctor(doctorId, { is_active: active }),
    onSuccess: (d) => toast.success(d.is_active ? `${d.full_name} can be booked again` : `${d.full_name} is now inactive`),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : 'Something went wrong.'),
    onSettled: () => {
      setConfirmDeactivate(false)
      return queryClient.invalidateQueries({ queryKey: ['doctors'] })
    },
  })

  const back = (
    <Button variant="ghost" size="sm" className="-ml-2" asChild>
      <Link to="/admin/doctors">
        <ArrowLeftIcon /> Doctors
      </Link>
    </Button>
  )

  if (query.isPending) {
    return (
      <div className="mx-auto max-w-4xl space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-60" />
      </div>
    )
  }
  if (!doctor) {
    return (
      <div className="mx-auto max-w-4xl space-y-3">
        {back}
        <p className="text-muted-foreground">This doctor does not exist.</p>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      {back}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{doctor.full_name}</h1>
          <p className="text-sm text-muted-foreground">
            {doctor.specialization}
            {doctor.profile_id ? ' · has a login' : ' · no login yet (create one under Staff)'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Switch
            id="doctor-active"
            checked={doctor.is_active}
            disabled={setActive.isPending}
            onCheckedChange={(active) => (active ? setActive.mutate(true) : setConfirmDeactivate(true))}
          />
          <Label htmlFor="doctor-active">{doctor.is_active ? 'Active' : 'Inactive'}</Label>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Profile</CardTitle>
        </CardHeader>
        <CardContent>
          <DoctorForm
            key={doctor.id}
            doctor={doctor}
            submitLabel="Save profile"
            onSubmit={async (changes) => {
              await updateDoctor(doctor.id, changes)
              await queryClient.invalidateQueries({ queryKey: ['doctors'] })
              toast.success('Profile saved')
            }}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Weekly hours</CardTitle>
          <CardDescription>
            Slots of {doctor.default_slot_minutes} minutes are offered inside these shifts.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {/* Re-initialise from the server copy after every save. */}
          <ScheduleEditor key={JSON.stringify(doctor.schedules)} doctor={doctor} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Leave</CardTitle>
          <CardDescription>No slots are offered on leave days, and bookings are blocked.</CardDescription>
        </CardHeader>
        <CardContent>
          <LeaveManager doctor={doctor} />
        </CardContent>
      </Card>

      <ConfirmDialog
        open={confirmDeactivate}
        onOpenChange={setConfirmDeactivate}
        title={`Make ${doctor.full_name} inactive?`}
        description="They disappear from booking screens. Existing appointments stay as they are."
        confirmLabel="Make inactive"
        destructive
        pending={setActive.isPending}
        onConfirm={() => setActive.mutate(false)}
      />
    </div>
  )
}
