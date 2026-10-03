import { type LucideIcon, MenuIcon } from 'lucide-react'
import { type ReactNode, useState } from 'react'
import { NavLink, Outlet } from 'react-router'

import { TopBar } from '@/components/layout/TopBar'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { cn } from '@/lib/utils'

export interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  end?: boolean
}

function Nav({ items, label, onNavigate }: { items: NavItem[]; label: string; onNavigate?: () => void }) {
  return (
    <nav className="flex flex-col gap-1 p-3" aria-label={label}>
      {items.map(({ to, label: text, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              'flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground',
              isActive && 'bg-muted text-foreground',
            )
          }
        >
          <Icon className="size-4" />
          {text}
        </NavLink>
      ))}
    </nav>
  )
}

/** Top bar + sidebar navigation (slide-out on mobile) around the routed page. */
export function SidebarShell({
  items,
  label,
  banner,
  children,
}: {
  items: NavItem[]
  label: string
  /** Shown under the top bar on every page (e.g. emergency alerts). */
  banner?: ReactNode
  children?: ReactNode
}) {
  const [menuOpen, setMenuOpen] = useState(false)
  return (
    <div className="flex min-h-svh flex-col bg-muted/30">
      <TopBar>
        <Button
          variant="ghost"
          size="icon"
          className="md:hidden"
          aria-label="Open menu"
          onClick={() => setMenuOpen(true)}
        >
          <MenuIcon />
        </Button>
      </TopBar>
      {banner}
      <div className="flex flex-1">
        <aside className="hidden w-52 shrink-0 border-r bg-background md:block">
          <Nav items={items} label={label} />
        </aside>
        <main className="min-w-0 flex-1 p-4 md:p-6">
          <Outlet />
        </main>
      </div>
      <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
        <SheetContent side="left" className="w-64 p-0">
          <SheetHeader>
            <SheetTitle>Menu</SheetTitle>
          </SheetHeader>
          <Nav items={items} label={label} onNavigate={() => setMenuOpen(false)} />
        </SheetContent>
      </Sheet>
      {children}
    </div>
  )
}
