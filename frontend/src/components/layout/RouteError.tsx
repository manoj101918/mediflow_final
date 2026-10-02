import { RefreshCwIcon, TriangleAlertIcon } from 'lucide-react'
import { isRouteErrorResponse, Link, useRouteError } from 'react-router'

import { Button } from '@/components/ui/button'

/** Shown when a page fails to load or crashes, instead of a blank screen. */
export function RouteError() {
  const error = useRouteError()
  // Pages are loaded on demand; after a new deploy the old chunk files no longer exist.
  const staleBuild =
    error instanceof Error && /dynamically imported module|Importing a module script failed/i.test(error.message)
  const notFound = isRouteErrorResponse(error) && error.status === 404

  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-4 p-6 text-center">
      <TriangleAlertIcon className="size-8 text-muted-foreground" />
      <div className="space-y-1">
        <h1 className="text-lg font-semibold">
          {staleBuild ? 'MediFlow was updated' : notFound ? 'Page not found' : 'Something went wrong'}
        </h1>
        <p className="max-w-md text-sm text-muted-foreground">
          {staleBuild
            ? 'Reload to get the latest version. Nothing you saved is lost.'
            : 'Reload the page. If it keeps happening, tell the clinic admin what you were doing.'}
        </p>
      </div>
      <div className="flex gap-2">
        <Button onClick={() => window.location.reload()}>
          <RefreshCwIcon /> Reload
        </Button>
        <Button variant="outline" asChild>
          <Link to="/">Go to my dashboard</Link>
        </Button>
      </div>
    </div>
  )
}
