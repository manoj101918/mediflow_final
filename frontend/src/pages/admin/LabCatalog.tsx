import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { PlusIcon, SearchIcon } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  fetchClinicSettings,
  fetchLabTests,
  labAdminKeys,
  setLabTestActive,
  updateClinicSettings,
} from '@/lib/admin'
import { ApiError } from '@/lib/api'
import { LAB_CATEGORY_LABEL, LAB_SAMPLE_LABEL } from '@/lib/labs'
import type { LabCategory } from '@/types/api'

const ALL = 'all'

function errorToast(e: unknown) {
  toast.error(e instanceof ApiError ? e.message : 'Something went wrong.')
}

function VerificationSetting() {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: labAdminKeys.settings, queryFn: ({ signal }) => fetchClinicSettings(signal) })
  const mutation = useMutation({
    mutationFn: (value: boolean) => updateClinicSettings({ lab_requires_verification: value }),
    onSuccess: (s) =>
      toast.success(
        s.lab_requires_verification
          ? 'Results now need a supervisor before release'
          : 'Technicians can now release results directly',
      ),
    onError: errorToast,
    onSettled: () => queryClient.invalidateQueries({ queryKey: labAdminKeys.settings }),
  })
  return (
    <Card>
      <CardHeader>
        <CardTitle>Release policy</CardTitle>
        <CardDescription>
          When on, a technician enters and submits results and a lab supervisor verifies them before the doctor sees
          them.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex items-center gap-3">
        {query.isPending ? (
          <Skeleton className="h-6 w-60" />
        ) : (
          <>
            <Switch
              id="lab-verification"
              checked={query.data?.lab_requires_verification ?? true}
              disabled={mutation.isPending}
              onCheckedChange={(v) => mutation.mutate(v)}
            />
            <Label htmlFor="lab-verification">Require verification before release</Label>
          </>
        )}
      </CardContent>
    </Card>
  )
}

export function LabCatalogPage() {
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState<LabCategory | typeof ALL>(ALL)
  const query = useQuery({ queryKey: labAdminKeys.tests, queryFn: ({ signal }) => fetchLabTests(signal) })

  const setActive = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) => setLabTestActive(id, active),
    onSuccess: (t) => toast.success(`${t.name} ${t.is_active ? 'can be ordered' : 'is no longer orderable'}`),
    onError: errorToast,
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['labs'] }),
  })

  const tests = useMemo(() => {
    const q = search.trim().toLowerCase()
    return (query.data ?? []).filter(
      (t) =>
        (category === ALL || t.category === category) &&
        (!q || t.name.toLowerCase().includes(q) || t.code.toLowerCase().includes(q)),
    )
  }, [query.data, search, category])

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Lab tests</h1>
          <p className="text-sm text-muted-foreground">
            The tests doctors can order, with their parameters and reference ranges. Changes apply to future results
            only.
          </p>
        </div>
        <Button asChild>
          <Link to="/admin/lab-tests/new">
            <PlusIcon /> New test
          </Link>
        </Button>
      </div>

      <VerificationSetting />

      <Card>
        <CardContent className="space-y-4 pt-6">
          <div className="flex flex-wrap gap-2">
            <div className="relative min-w-60 flex-1">
              <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                aria-label="Search tests"
                placeholder="Search by name or code"
                className="pl-8"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <Select value={category} onValueChange={(v) => setCategory(v as LabCategory | typeof ALL)}>
              <SelectTrigger className="w-44" aria-label="Category">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All categories</SelectItem>
                {Object.entries(LAB_CATEGORY_LABEL).map(([value, label]) => (
                  <SelectItem key={value} value={value}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {query.isPending ? (
            <Skeleton className="h-60" />
          ) : query.isError ? (
            <p className="text-sm text-destructive">Could not load the catalog.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Code</TableHead>
                  <TableHead>Test</TableHead>
                  <TableHead className="hidden md:table-cell">Category</TableHead>
                  <TableHead className="hidden md:table-cell">Sample</TableHead>
                  <TableHead className="hidden sm:table-cell">Parameters</TableHead>
                  <TableHead className="hidden sm:table-cell">TAT</TableHead>
                  <TableHead className="text-right">Orderable</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {tests.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={7} className="py-8 text-center text-muted-foreground">
                      No tests match.
                    </TableCell>
                  </TableRow>
                )}
                {tests.map((t) => (
                  <TableRow key={t.id} data-lab-test-id={t.id}>
                    <TableCell className="font-mono text-xs">{t.code}</TableCell>
                    <TableCell>
                      <Link to={`/admin/lab-tests/${t.id}`} className="font-medium hover:underline">
                        {t.name}
                      </Link>
                      {t.is_panel && (
                        <Badge variant="secondary" className="ml-2">
                          Panel
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="hidden md:table-cell">{LAB_CATEGORY_LABEL[t.category]}</TableCell>
                    <TableCell className="hidden md:table-cell">
                      {LAB_SAMPLE_LABEL[t.sample_type]}
                      {t.container && <span className="text-muted-foreground"> · {t.container}</span>}
                    </TableCell>
                    <TableCell className="hidden sm:table-cell">
                      {t.parameters.filter((p) => p.is_active).length}
                    </TableCell>
                    <TableCell className="hidden sm:table-cell">{t.turnaround_hours} h</TableCell>
                    <TableCell className="text-right">
                      <Switch
                        aria-label={`${t.name} orderable`}
                        checked={t.is_active}
                        disabled={setActive.isPending}
                        onCheckedChange={(active) => setActive.mutate({ id: t.id, active })}
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
