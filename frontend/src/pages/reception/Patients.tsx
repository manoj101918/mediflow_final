import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { SearchIcon, UserPlusIcon } from 'lucide-react'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { toast } from 'sonner'

import { Pager } from '@/components/common/Pager'
import { PatientForm } from '@/components/patients/PatientForm'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { formatDate, formatPatientMeta, formatPhone } from '@/lib/format'
import { createPatient, patientKeys, searchPatients } from '@/lib/patients'
import type { PatientInput } from '@/types/api'

const PAGE_SIZE = 20

export function PatientsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState(params.get('q') ?? '')
  const [adding, setAdding] = useState(false)
  const q = useDebouncedValue(search.trim(), 300)
  const page = Number(params.get('page') ?? '1') || 1

  const setPage = (next: number) =>
    setParams((p) => {
      p.set('page', String(next))
      return p
    })

  const query = useQuery({
    queryKey: patientKeys.search(q, page, PAGE_SIZE),
    queryFn: ({ signal }) => searchPatients(q, page, PAGE_SIZE, signal),
    placeholderData: keepPreviousData,
  })

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Patients</h1>
          <p className="text-sm text-muted-foreground">Search by name (typos are fine) or any part of the phone number.</p>
        </div>
        <Button onClick={() => setAdding(true)}>
          <UserPlusIcon /> Add patient
        </Button>
      </div>

      <div className="relative max-w-md">
        <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          type="search"
          autoFocus
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            setParams((p) => {
              if (e.target.value) p.set('q', e.target.value)
              else p.delete('q')
              p.delete('page')
              return p
            }, { replace: true })
          }}
          placeholder="Name or phone"
          aria-label="Search patients"
          className="pl-8"
        />
      </div>

      <div className="overflow-hidden rounded-xl border bg-background">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/50 hover:bg-muted/50">
              <TableHead>Name</TableHead>
              <TableHead>Phone</TableHead>
              <TableHead className="hidden sm:table-cell">Gender · age</TableHead>
              <TableHead className="hidden md:table-cell">Area</TableHead>
              <TableHead className="hidden lg:table-cell">Registered</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {query.isPending ? (
              Array.from({ length: 6 }, (_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={5}>
                    <Skeleton className="h-6" />
                  </TableCell>
                </TableRow>
              ))
            ) : query.data?.items.length ? (
              query.data.items.map((p) => (
                <TableRow
                  key={p.id}
                  className="cursor-pointer"
                  tabIndex={0}
                  onClick={() => navigate(`/reception/patients/${p.id}`)}
                  onKeyDown={(e) => e.key === 'Enter' && navigate(`/reception/patients/${p.id}`)}
                >
                  <TableCell className="font-medium">{p.full_name}</TableCell>
                  <TableCell className="tabular-nums">{formatPhone(p.phone)}</TableCell>
                  <TableCell className="hidden sm:table-cell">{formatPatientMeta(p.gender, p.age) || '—'}</TableCell>
                  <TableCell className="hidden max-w-56 truncate md:table-cell">{p.address ?? '—'}</TableCell>
                  <TableCell className="hidden lg:table-cell">{formatDate(p.created_at)}</TableCell>
                </TableRow>
              ))
            ) : (
              <TableRow className="hover:bg-transparent">
                <TableCell colSpan={5} className="py-12 text-center text-muted-foreground">
                  {q ? `No patient matches “${q}”.` : 'No patients yet.'}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
      {query.data && <Pager page={page} pageSize={PAGE_SIZE} total={query.data.total} onPageChange={setPage} />}

      <Dialog open={adding} onOpenChange={setAdding}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Add patient</DialogTitle>
            <DialogDescription>Phone numbers are saved in +91 format automatically.</DialogDescription>
          </DialogHeader>
          <PatientForm
            initialName={search}
            submitLabel="Save patient"
            onCancel={() => setAdding(false)}
            onSubmit={async (input) => {
              const created = await createPatient(input as PatientInput)
              await queryClient.invalidateQueries({ queryKey: patientKeys.all })
              toast.success(`Added ${created.full_name}`)
              setAdding(false)
              navigate(`/reception/patients/${created.id}`)
            }}
          />
        </DialogContent>
      </Dialog>
    </div>
  )
}
