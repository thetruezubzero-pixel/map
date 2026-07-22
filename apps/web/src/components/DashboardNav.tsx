import { Link, useLocation } from 'react-router-dom'

const LINKS = [
  { to: '/', label: 'Map' },
  { to: '/agents', label: 'Agents' },
  { to: '/swarm', label: 'Swarm' },
  { to: '/training', label: 'Training' },
  { to: '/heirlooms', label: 'Heirlooms' },
]

/** Phase 5 nav -- switches between the map and the agent-swarm dashboard
 * pages. Kept deliberately tiny (no active-route styling library, no
 * nested menus) since it's five flat routes.
 *
 * `overflow-x-auto` + `flex-nowrap`: five labelled links don't fit next
 * to the title in the header on a phone-width screen -- rather than
 * truncate/hide links silently, they scroll horizontally, which stays
 * fully reachable (confirmed against the same 390px-viewport overflow
 * issue found in App.tsx's sidebar layout). */
export function DashboardNav() {
  const location = useLocation()
  return (
    <nav aria-label="Primary" className="flex min-w-0 flex-nowrap items-center gap-1 overflow-x-auto text-sm">
      {LINKS.map((link) => {
        const active = location.pathname === link.to
        return (
          <Link
            key={link.to}
            to={link.to}
            aria-current={active ? 'page' : undefined}
            className={`shrink-0 rounded-md px-2.5 py-1.5 ${
              active ? 'bg-accent text-white' : 'text-text-muted hover:bg-surface-2 hover:text-text'
            }`}
          >
            {link.label}
          </Link>
        )
      })}
    </nav>
  )
}
