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
 * nested menus) since it's five flat routes. */
export function DashboardNav() {
  const location = useLocation()
  return (
    <nav className="flex items-center gap-1 text-sm">
      {LINKS.map((link) => {
        const active = location.pathname === link.to
        return (
          <Link
            key={link.to}
            to={link.to}
            className={`rounded-md px-2.5 py-1.5 ${
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
