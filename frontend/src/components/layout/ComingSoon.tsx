import { useAuth } from '@/auth/context'

/** Temporary dashboard body until the role's real pages land. */
export function ComingSoon({ title, milestone }: { title: string; milestone: string }) {
  const { me } = useAuth()
  return (
    <div className="mx-auto max-w-3xl space-y-2">
      <h1 className="text-xl font-semibold">{title}</h1>
      <p className="text-sm text-muted-foreground">
        Signed in as {me?.full_name}. This screen is built in {milestone}.
      </p>
    </div>
  )
}
