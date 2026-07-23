import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { SlidersHorizontal, List, X } from 'lucide-react'
import { SearchBar } from '@/components/SearchBar'
import { FilterPanel, DateRangeInputs } from '@/components/FilterPanel'
import { TimelineScrubber } from '@/components/TimelineScrubber'
import { ResearchPanel } from '@/components/ResearchPanel'
import { EntityDetailPanel } from '@/components/EntityDetailPanel'
import { AlertPanel } from '@/components/AlertPanel'
import { SystemHealthPanel } from '@/components/SystemHealthPanel'
import { DashboardNav } from '@/components/DashboardNav'
import { AgentCommandBar } from '@/components/AgentCommandBar'
import { Button } from '@/components/ui/button'
import { useMapStore } from '@/store/useMapStore'
import { useAlertStore } from '@/store/useAlertStore'

// Defer map rendering with React.lazy to prioritize search/filters/header
// interactivity (leaflet bundle with GeoJSON rendering can be deferred)
const MapView = lazy(() => import('@/components/MapView').then((m) => ({ default: m.MapView })))

// Below `lg`, the two always-visible desktop sidebars (w-72 + w-80) don't
// fit next to the map on a phone-width screen -- confirmed live at a
// 390px viewport: 626px of horizontal overflow, search bar and most nav
// links pushed off-screen entirely. Below `lg` they're hidden by default
// and shown one at a time as a full-screen overlay via these toggles;
// `lg:` and up is completely unchanged from the previous fixed 3-column
// layout.
type MobilePanel = 'filters' | 'results' | null

function App() {
  const results = useMapStore((s) => s.results)
  const selectedEntityId = useMapStore((s) => s.selectedEntityId)
  const setSelectedEntityId = useMapStore((s) => s.setSelectedEntityId)
  const unreadAlertCount = useAlertStore((s) => s.unreadCount)
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>(null)
  const dialogCloseButtonRef = useRef<HTMLButtonElement>(null)
  const lastFocusedElementRef = useRef<HTMLElement | null>(null)

  // Register service worker for PWA: offline caching + installable app
  useEffect(() => {
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js').catch((e) => {
        console.log('[PWA] Service Worker registration skipped (not critical)', e)
      })
    }
  }, [])

  // The mobile filters/results overlay is `role="dialog" aria-modal="true"`,
  // but confirmed live it wasn't actually behaving like one: opening it
  // never moved focus in (so a keyboard/screen-reader user stayed on
  // whichever header control they'd just activated), closing it never
  // restored focus to that trigger, and the header/main behind the
  // backdrop stayed in the Tab order the whole time (a `fixed inset-0`
  // backdrop only blocks clicks/visuals, not Tab, which follows DOM order
  // rather than z-index) -- so `aria-modal="true"` was not actually true.
  useEffect(() => {
    if (mobilePanel) {
      lastFocusedElementRef.current = document.activeElement as HTMLElement | null
      dialogCloseButtonRef.current?.focus()
    } else {
      lastFocusedElementRef.current?.focus()
      lastFocusedElementRef.current = null
    }
  }, [mobilePanel])

  return (
    <div className="flex h-screen flex-col bg-background text-text">
      <header
        inert={mobilePanel !== null}
        className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3 print:hidden lg:flex-nowrap lg:gap-4"
      >
        <div className="flex min-w-0 items-center gap-3 lg:gap-4">
          <h1 className="shrink-0 whitespace-nowrap text-lg font-semibold text-text">Aether Sovereign OS</h1>
          <DashboardNav />
        </div>
        <div className="order-last w-full lg:order-none lg:w-full lg:max-w-xl">
          <SearchBar />
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-2 lg:ml-auto">
          {unreadAlertCount > 0 && (
            <span
              className="shrink-0 rounded-full bg-accent px-2 py-0.5 text-xs font-medium text-white"
              title={`${unreadAlertCount} unread alert${unreadAlertCount === 1 ? '' : 's'}`}
            >
              {unreadAlertCount} alert{unreadAlertCount === 1 ? '' : 's'}
            </span>
          )}
          <Button
            variant="outline"
            size="icon"
            className="lg:hidden"
            aria-label="Open filters and research panel"
            aria-expanded={mobilePanel === 'filters'}
            aria-controls="mobile-filters-panel"
            onClick={() => setMobilePanel((p) => (p === 'filters' ? null : 'filters'))}
          >
            <SlidersHorizontal className="h-4 w-4" aria-hidden="true" />
          </Button>
          <Button
            variant="outline"
            size="icon"
            className="lg:hidden"
            aria-label={`Open results (${results.length})`}
            aria-expanded={mobilePanel === 'results'}
            aria-controls="mobile-results-panel"
            onClick={() => setMobilePanel((p) => (p === 'results' ? null : 'results'))}
          >
            <List className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 print:block">
        <aside
          id="mobile-filters-panel"
          aria-label="Filters and research"
          className="hidden w-72 shrink-0 overflow-y-auto border-r border-border p-4 print:hidden lg:block"
        >
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

        <main inert={mobilePanel !== null} className="relative min-w-0 flex-1 print:hidden">
          <Suspense
            fallback={
              <div className="flex h-full w-full items-center justify-center bg-surface text-sm text-text-muted">
                Loading map…
              </div>
            }
          >
            <MapView />
          </Suspense>
          {/* The conversational control: talk to the map, the agent drives
              it. Overlaid on the map so it's the primary interaction, not
              another panel to hunt for. */}
          <AgentCommandBar />
        </main>

        <aside
          id="mobile-results-panel"
          aria-label="Search results"
          className="hidden w-80 shrink-0 overflow-y-auto border-l border-border p-4 print:block print:w-full print:border-0 print:p-0 lg:block"
        >
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

        {mobilePanel && (
          <div
            role="dialog"
            aria-modal="true"
            aria-label={mobilePanel === 'filters' ? 'Filters and research' : 'Search results'}
            /* z-[2000]: a modal must cover everything, including the
               AgentCommandBar (z-1000) overlaid on the map -- at the old
               z-40 the floating command bar painted through the dialog.
               See the z-index scale in index.css. */
            className="fixed inset-0 z-[2000] flex lg:hidden"
          >
            <button
              type="button"
              aria-label="Close panel"
              className="absolute inset-0 bg-black/60"
              onClick={() => setMobilePanel(null)}
            />
            <div className="relative ml-auto flex h-full w-[85vw] max-w-sm flex-col overflow-y-auto bg-background p-4 shadow-xl">
              <Button
                ref={dialogCloseButtonRef}
                variant="ghost"
                size="icon"
                aria-label="Close panel"
                className="mb-2 self-end"
                onClick={() => setMobilePanel(null)}
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </Button>
              {mobilePanel === 'filters' ? (
                <>
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
                </>
              ) : selectedEntityId ? (
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
                          onClick={() => {
                            setSelectedEntityId(r.id)
                          }}
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
            </div>
          </div>
        )}
      </div>

      {/* A readiness review found this left out of the mobile dialog's
          focus trap -- header/main both get `inert` when the mobile
          overlay opens, but this footer (containing TimelineScrubber's
          range input) didn't, so Tab/Shift+Tab from the dialog could
          still reach and operate a control hidden underneath the
          backdrop, violating aria-modal semantics the same way the
          already-fixed header/main leak did. */}
      <footer inert={mobilePanel !== null} className="border-t border-border p-3 print:hidden">
        <TimelineScrubber />
      </footer>
    </div>
  )
}

export default App
