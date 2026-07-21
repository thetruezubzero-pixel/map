import { lazy, Suspense } from 'react'
import { SearchBar } from '@/components/SearchBar'
import { FilterPanel, DateRangeInputs } from '@/components/FilterPanel'
import { TimelineScrubber } from '@/components/TimelineScrubber'
import { ResearchPanel } from '@/components/ResearchPanel'
import { EntityDetailPanel } from '@/components/EntityDetailPanel'
import { AlertPanel } from '@/components/AlertPanel'
import { SystemHealthPanel } from '@/components/SystemHealthPanel'
import { useMapStore } from '@/store/useMapStore'
import { useAlertStore } from '@/store/useAlertStore'

// mapbox-gl is a ~1.8MB chunk (dominates initial load -- see audit: it
// alone accounted for most of the ~3.6s TTI measured on throttled 3G).
// Deferring it behind React.lazy lets the rest of the shell (search,
// filters, header) become interactive without waiting on it.
const MapView = lazy(() => import('@/components/MapView').then((m) => ({ default: m.MapView })))

function App() {
  const results = useMapStore((s) => s.results)
  const selectedEntityId = useMapStore((s) => s.selectedEntityId)
  const setSelectedEntityId = useMapStore((s) => s.setSelectedEntityId)
  const unreadAlertCount = useAlertStore((s) => s.unreadCount)

  return (
    <div className="flex h-screen flex-col bg-background text-text">
      <header className="flex items-center gap-4 border-b border-border px-4 py-3 print:hidden">
        <h1 className="whitespace-nowrap text-lg font-semibold text-text">Aether Sovereign OS</h1>
        <div className="w-full max-w-xl">
          <SearchBar />
        </div>
        {unreadAlertCount > 0 && (
          <span
            className="ml-auto shrink-0 rounded-full bg-accent px-2 py-0.5 text-xs font-medium text-white"
            title={`${unreadAlertCount} unread alert${unreadAlertCount === 1 ? '' : 's'}`}
          >
            {unreadAlertCount} alert{unreadAlertCount === 1 ? '' : 's'}
          </span>
        )}
      </header>

      <div className="flex min-h-0 flex-1 print:block">
        <aside className="w-72 shrink-0 overflow-y-auto border-r border-border p-4 print:hidden">
          <FilterPanel />
          <div className="mt-5">
            <DateRangeInputs />
          </div>
          <div className="mt-5">
            <ResearchPanel />
          </div>
          <div className="mt-5 border-t border-border pt-5">
            <AlertPanel />
          </div>
          <div className="mt-5 border-t border-border pt-5">
            <SystemHealthPanel />
          </div>
        </aside>

        <main className="relative flex-1 print:hidden">
          <Suspense
            fallback={
              <div className="flex h-full w-full items-center justify-center bg-surface text-sm text-text-muted">
                Loading map…
              </div>
            }
          >
            <MapView />
          </Suspense>
        </main>

        <aside className="w-80 shrink-0 overflow-y-auto border-l border-border p-4 print:w-full print:border-0 print:p-0">
          {selectedEntityId ? (
            <EntityDetailPanel />
          ) : (
            <>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
                Results ({results.length})
              </h3>
              <ul className="space-y-2">
                {results.map((r) => (
                  <li key={r.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedEntityId(r.id)}
                      className="w-full rounded-md border border-border bg-surface px-3 py-2 text-left text-sm hover:bg-surface-2"
                    >
                      <p className="truncate font-medium text-text">{r.name}</p>
                      <p className="text-xs text-text-muted">
                        {r.entity_type} · {r.source}
                      </p>
                    </button>
                  </li>
                ))}
                {results.length === 0 && (
                  <p className="text-sm text-text-muted">Search an address or click the map to look up records.</p>
                )}
              </ul>
            </>
          )}
        </aside>
      </div>

      <footer className="border-t border-border p-3 print:hidden">
        <TimelineScrubber />
      </footer>
    </div>
  )
}

export default App
