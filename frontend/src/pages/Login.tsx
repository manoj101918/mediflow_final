import { zodResolver } from '@hookform/resolvers/zod'
import { AlertCircleIcon, Loader2Icon, StethoscopeIcon } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Navigate, useLocation, useSearchParams } from 'react-router'
import { z } from 'zod'

import { useAuth } from '@/auth/context'
import { ROLE_HOME, canVisit } from '@/auth/roles'
import { FullPageLoader } from '@/components/layout/StatusScreens'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const loginSchema = z.object({
  email: z.email('Enter a valid email address.'),
  password: z.string().min(1, 'Enter your password.'),
})

type LoginValues = z.infer<typeof loginSchema>

export function LoginPage() {
  const { status, me, notice, signIn } = useAuth()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const [formError, setFormError] = useState<string | null>(null)

  const form = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '' },
  })
  const { errors, isSubmitting } = form.formState

  if (status === 'signed_in' && me) {
    const from = (location.state as { from?: string } | null)?.from
    return <Navigate to={from && canVisit(me.role, from) ? from : ROLE_HOME[me.role]} replace />
  }
  // Credentials accepted: wait for the staff profile before redirecting.
  if (status === 'loading' && !isSubmitting && form.formState.isSubmitSuccessful) {
    return <FullPageLoader />
  }

  const onSubmit = form.handleSubmit(async (values) => {
    setFormError(null)
    try {
      await signIn(values.email.trim(), values.password)
    } catch {
      setFormError('Incorrect email or password.')
      form.setValue('password', '')
      form.setFocus('password')
      throw new Error('sign-in failed') // keeps isSubmitSuccessful false
    }
  })

  const banner =
    notice ??
    (searchParams.get('expired') === '1' ? 'Your session expired. Please sign in again.' : null)

  return (
    <main className="flex min-h-svh items-center justify-center bg-muted/40 p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="space-y-2 text-center">
          <div className="mx-auto flex size-10 items-center justify-center rounded-full bg-primary text-primary-foreground">
            <StethoscopeIcon className="size-5" />
          </div>
          <CardTitle className="text-lg">MediFlow</CardTitle>
          <CardDescription>Sign in with your clinic staff account</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" noValidate onSubmit={(e) => void onSubmit(e).catch(() => {})}>
            {(formError ?? banner) && (
              <div
                role="alert"
                className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
              >
                <AlertCircleIcon className="mt-0.5 size-4 shrink-0" />
                <span>{formError ?? banner}</span>
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="username"
                autoFocus
                aria-invalid={Boolean(errors.email)}
                {...form.register('email')}
              />
              {errors.email && <p className="text-xs text-destructive">{errors.email.message}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                aria-invalid={Boolean(errors.password)}
                {...form.register('password')}
              />
              {errors.password && (
                <p className="text-xs text-destructive">{errors.password.message}</p>
              )}
            </div>
            <Button type="submit" className="w-full" size="lg" disabled={isSubmitting}>
              {isSubmitting && <Loader2Icon className="animate-spin" />}
              Sign in
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  )
}
