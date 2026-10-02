import { Loader2Icon, WifiOffIcon } from 'lucide-react'

import { useAuth } from '@/auth/context'
import { Button } from '@/components/ui/button'

export function FullPageLoader() {
  return (
    <div className="flex min-h-svh items-center justify-center" role="status" aria-live="polite">
      <Loader2Icon className="size-6 animate-spin text-muted-foreground" />
      <span className="sr-only">Loading</span>
    </div>
  )
}

export function AuthErrorScreen() {
  const { error, retry, signOut } = useAuth()
  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-4 p-6 text-center">
      <WifiOffIcon className="size-8 text-muted-foreground" />
      <div className="space-y-1">
        <h1 className="text-lg font-semibold">Could not load your account</h1>
        <p className="text-sm text-muted-foreground">
          {error?.message ?? 'Something went wrong.'}
        </p>
      </div>
      <div className="flex gap-2">
        <Button onClick={retry}>Try again</Button>
        <Button variant="outline" onClick={() => void signOut()}>
          Sign out
        </Button>
      </div>
    </div>
  )
}
