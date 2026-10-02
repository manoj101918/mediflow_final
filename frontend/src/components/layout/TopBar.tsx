import { LogOutIcon, StethoscopeIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { useAuth } from '@/auth/context'
import { ROLE_LABEL } from '@/auth/roles'
import { Button } from '@/components/ui/button'
import { useNow } from '@/hooks/useNow'
import { formatWeekdayDate } from '@/lib/format'

export function TopBar({ children }: { children?: ReactNode }) {
  const { me, signOut } = useAuth()
  const now = useNow()
  if (!me) return null

  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b bg-background px-4">
      {children}
      <div className="flex min-w-0 items-center gap-2">
        <StethoscopeIcon className="size-5 shrink-0 text-primary" />
        <span className="truncate font-semibold">{me.clinic.name}</span>
      </div>
      <span className="hidden text-sm text-muted-foreground sm:inline">
        {formatWeekdayDate(now)}
      </span>
      <div className="ml-auto flex items-center gap-3">
        <div className="hidden text-right leading-tight md:block">
          <div className="text-sm font-medium">{me.full_name}</div>
          <div className="text-xs text-muted-foreground">{ROLE_LABEL[me.role]}</div>
        </div>
        <Button variant="outline" size="sm" onClick={() => void signOut()}>
          <LogOutIcon />
          Log out
        </Button>
      </div>
    </header>
  )
}
