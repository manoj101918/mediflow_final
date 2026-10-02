import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircleIcon, KeyRoundIcon, Loader2Icon, PencilIcon, UserPlusIcon } from 'lucide-react'
import { useState } from 'react'
import { Controller, useForm, useWatch } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import { useAuth } from '@/auth/context'
import { ROLE_LABEL } from '@/auth/roles'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { adminKeys, createUser, fetchAllDoctors, fetchUsers, updateUser } from '@/lib/admin'
import { ApiError } from '@/lib/api'
import { formatDate, formatPhone } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { Doctor, StaffUser, UserRole } from '@/types/api'

const ROLE_TONE: Record<UserRole, string> = {
  admin: 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900',
  receptionist: 'bg-sky-100 text-sky-900 dark:bg-sky-500/20 dark:text-sky-200',
  doctor: 'bg-violet-100 text-violet-900 dark:bg-violet-500/20 dark:text-violet-200',
  lab_technician: 'bg-teal-100 text-teal-900 dark:bg-teal-500/20 dark:text-teal-200',
  lab_supervisor: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-500/20 dark:text-emerald-200',
}

function useStaffMutation<TVars>(fn: (vars: TVars) => Promise<StaffUser>, message: (u: StaffUser) => string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (u) => toast.success(message(u)),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : 'Something went wrong.'),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: adminKeys.users })
      void queryClient.invalidateQueries({ queryKey: adminKeys.doctors })
    },
  })
}

export function UsersPage() {
  const { me } = useAuth()
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<StaffUser | null>(null)
  const [deactivating, setDeactivating] = useState<StaffUser | null>(null)

  const users = useQuery({ queryKey: adminKeys.users, queryFn: ({ signal }) => fetchUsers(signal) })
  const doctors = useQuery({ queryKey: adminKeys.doctors, queryFn: ({ signal }) => fetchAllDoctors(signal) })
  const doctorName = (id: string | null) => doctors.data?.find((d) => d.id === id)?.full_name

  const setActive = useStaffMutation(
    ({ id, active }: { id: string; active: boolean }) => updateUser(id, { is_active: active }),
    (u) => `${u.full_name} ${u.is_active ? 'can sign in again' : 'has been deactivated'}`,
  )

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Staff</h1>
          <p className="text-sm text-muted-foreground">Everyone who can sign in to the clinic. Deactivated accounts cannot sign in.</p>
        </div>
        <Button onClick={() => setAdding(true)}>
          <UserPlusIcon /> Add staff
        </Button>
      </div>

      <div className="overflow-hidden rounded-xl border bg-background">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/50 hover:bg-muted/50">
              <TableHead>Name</TableHead>
              <TableHead className="hidden md:table-cell">Email</TableHead>
              <TableHead>Role</TableHead>
              <TableHead className="hidden lg:table-cell">Phone</TableHead>
              <TableHead className="hidden lg:table-cell">Added</TableHead>
              <TableHead>Active</TableHead>
              <TableHead className="w-12" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {users.isPending
              ? Array.from({ length: 4 }, (_, i) => (
                  <TableRow key={i}>
                    <TableCell colSpan={7}>
                      <Skeleton className="h-6" />
                    </TableCell>
                  </TableRow>
                ))
              : users.data?.map((u) => {
                  const self = u.id === me?.id
                  return (
                    <TableRow key={u.id} data-user-id={u.id} className={cn(!u.is_active && 'text-muted-foreground')}>
                      <TableCell>
                        <div className="font-medium text-foreground">
                          {u.full_name} {self && <span className="text-xs font-normal text-muted-foreground">(you)</span>}
                        </div>
                        {u.role === 'doctor' && (
                          <div className="text-xs text-muted-foreground">
                            {u.doctor_id ? `Doctor profile: ${doctorName(u.doctor_id) ?? '…'}` : 'Not linked to a doctor profile'}
                          </div>
                        )}
                      </TableCell>
                      <TableCell className="hidden md:table-cell">{u.email}</TableCell>
                      <TableCell>
                        <Badge className={ROLE_TONE[u.role]}>{ROLE_LABEL[u.role]}</Badge>
                      </TableCell>
                      <TableCell className="hidden tabular-nums lg:table-cell">{formatPhone(u.phone) || '—'}</TableCell>
                      <TableCell className="hidden lg:table-cell">{formatDate(u.created_at)}</TableCell>
                      <TableCell>
                        <Switch
                          checked={u.is_active}
                          disabled={self || (setActive.isPending && setActive.variables?.id === u.id)}
                          aria-label={`${u.full_name} active`}
                          title={self ? 'You cannot deactivate your own account' : undefined}
                          onCheckedChange={(active) =>
                            active ? setActive.mutate({ id: u.id, active: true }) : setDeactivating(u)
                          }
                        />
                      </TableCell>
                      <TableCell>
                        <Button size="icon-sm" variant="ghost" aria-label={`Edit ${u.full_name}`} onClick={() => setEditing(u)}>
                          <PencilIcon />
                        </Button>
                      </TableCell>
                    </TableRow>
                  )
                })}
          </TableBody>
        </Table>
      </div>

      {adding && (
        <AddStaffDialog
          doctors={doctors.data ?? []}
          onClose={() => setAdding(false)}
        />
      )}
      {editing && <EditStaffDialog user={editing} onClose={() => setEditing(null)} />}
      <ConfirmDialog
        open={deactivating !== null}
        onOpenChange={(open) => !open && setDeactivating(null)}
        title={`Deactivate ${deactivating?.full_name}?`}
        description="They will be signed out and cannot sign in until you reactivate the account. Their history is kept."
        confirmLabel="Deactivate"
        destructive
        pending={setActive.isPending}
        onConfirm={() =>
          deactivating &&
          setActive.mutate({ id: deactivating.id, active: false }, { onSettled: () => setDeactivating(null) })
        }
      />
    </div>
  )
}

const NONE = 'none'

const createSchema = z
  .object({
    full_name: z.string().trim().min(1, 'Enter a name.').max(120),
    email: z.string().trim().regex(/^[^@\s]+@[^@\s]+\.[^@\s]+$/, 'Enter a valid email address.'),
    phone: z.string().trim().max(20),
    role: z.enum(['receptionist', 'doctor', 'admin', 'lab_technician', 'lab_supervisor']),
    password: z.string().min(8, 'At least 8 characters.').max(72),
    doctor_id: z.string(),
  })
  .refine((v) => v.role === 'doctor' || v.doctor_id === NONE, { path: ['doctor_id'], message: 'Only doctors can be linked.' })

type CreateValues = z.infer<typeof createSchema>

function generatePassword(): string {
  const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789'
  const bytes = crypto.getRandomValues(new Uint8Array(12))
  return Array.from(bytes, (b) => alphabet[b % alphabet.length]).join('')
}

function AddStaffDialog({ doctors, onClose }: { doctors: Doctor[]; onClose: () => void }) {
  const [error, setError] = useState<string | null>(null)
  const form = useForm<CreateValues>({
    resolver: zodResolver(createSchema),
    defaultValues: { full_name: '', email: '', phone: '', role: 'receptionist', password: '', doctor_id: NONE },
  })
  const { errors, isSubmitting } = form.formState
  const role = useWatch({ control: form.control, name: 'role' })
  const unlinked = doctors.filter((d) => d.profile_id === null)
  const create = useStaffMutation(createUser, (u) => `Account created for ${u.full_name}`)

  const submit = form.handleSubmit(async (v) => {
    setError(null)
    try {
      await create.mutateAsync({
        full_name: v.full_name,
        email: v.email,
        phone: v.phone || null,
        role: v.role,
        password: v.password,
        doctor_id: v.role === 'doctor' && v.doctor_id !== NONE ? v.doctor_id : null,
      })
      onClose()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not create the account.')
    }
  })

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Add staff account</DialogTitle>
          <DialogDescription>They sign in with this email and password. Share the password privately.</DialogDescription>
        </DialogHeader>
        <form id="add-staff" className="space-y-4" noValidate onSubmit={(e) => void submit(e)}>
          {error && (
            <p role="alert" className="flex items-center gap-2 rounded-lg bg-destructive/5 p-3 text-sm text-destructive">
              <AlertCircleIcon className="size-4" /> {error}
            </p>
          )}
          <Field htmlFor="staff-full_name" label="Full name" error={errors.full_name?.message}>
            <Input id="staff-full_name" autoFocus {...form.register('full_name')} />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field htmlFor="staff-email" label="Email" error={errors.email?.message}>
              <Input id="staff-email" type="email" autoComplete="off" {...form.register('email')} />
            </Field>
            <Field htmlFor="staff-phone" label="Phone (optional)" error={errors.phone?.message}>
              <Input id="staff-phone" inputMode="tel" {...form.register('phone')} />
            </Field>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field htmlFor="staff-role" label="Role">
              <Controller
                control={form.control}
                name="role"
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger id="staff-role" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="receptionist">Receptionist</SelectItem>
                      <SelectItem value="doctor">Doctor</SelectItem>
                      <SelectItem value="admin">Admin</SelectItem>
                      <SelectItem value="lab_technician">Lab technician</SelectItem>
                      <SelectItem value="lab_supervisor">Lab supervisor</SelectItem>
                    </SelectContent>
                  </Select>
                )}
              />
            </Field>
            {role === 'doctor' && (
              <Field htmlFor="staff-doctor_id" label="Doctor profile" error={errors.doctor_id?.message}>
                <Controller
                  control={form.control}
                  name="doctor_id"
                  render={({ field }) => (
                    <Select value={field.value} onValueChange={field.onChange}>
                      <SelectTrigger id="staff-doctor_id" className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={NONE}>Link later</SelectItem>
                        {unlinked.map((d) => (
                          <SelectItem key={d.id} value={d.id}>
                            {d.full_name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                />
              </Field>
            )}
          </div>
          <Field htmlFor="staff-password" label="Initial password" error={errors.password?.message}>
            <div className="flex gap-2">
              <Input id="staff-password" autoComplete="new-password" className="font-mono" {...form.register('password')} />
              <Button
                type="button"
                variant="outline"
                onClick={() => form.setValue('password', generatePassword(), { shouldValidate: true })}
              >
                <KeyRoundIcon /> Generate
              </Button>
            </div>
          </Field>
          {role === 'doctor' && unlinked.length === 0 && (
            <p className="text-xs text-muted-foreground">Every doctor already has a login. Add the doctor under Doctors first to link it.</p>
          )}
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="add-staff" disabled={isSubmitting}>
            {isSubmitting && <Loader2Icon className="animate-spin" />}
            Create account
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function EditStaffDialog({ user, onClose }: { user: StaffUser; onClose: () => void }) {
  const [fullName, setFullName] = useState(user.full_name)
  const [phone, setPhone] = useState(user.phone ?? '')
  const save = useStaffMutation(
    () => updateUser(user.id, { full_name: fullName.trim(), phone: phone.trim() || null }),
    (u) => `Saved ${u.full_name}`,
  )
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Edit {user.full_name}</DialogTitle>
          <DialogDescription>{user.email}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <Field htmlFor="edit-full_name" label="Full name">
            <Input id="edit-full_name" value={fullName} maxLength={120} onChange={(e) => setFullName(e.target.value)} />
          </Field>
          <Field htmlFor="edit-phone" label="Phone">
            <Input id="edit-phone" value={phone} inputMode="tel" maxLength={20} onChange={(e) => setPhone(e.target.value)} />
          </Field>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={!fullName.trim() || save.isPending}
            onClick={() => save.mutate(undefined, { onSuccess: onClose })}
          >
            {save.isPending && <Loader2Icon className="animate-spin" />}
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Field({
  label,
  htmlFor,
  error,
  children,
}: {
  label: string
  htmlFor: string
  error?: string
  children: React.ReactNode
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  )
}
