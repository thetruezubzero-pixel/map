import { MapView } from '@/components/MapView'
import { SearchBar } from '@/components/SearchBar'
import { FilterPanel, DateRangeInputs } from '@/components/FilterPanel'
import { TimelineScrubber } from '@/components/TimelineScrubber'
import { ResearchPanel } from '@/components/ResearchPanel'
import { useMapStore } from '@/store/useMapStore'

function App() {
  const results = useMapStore((s) => s.results)
  const setSelectedEntityId = useMapStore((s) => s.setSelectedEntityId)

  return (
    <div className="flex h-screen flex-col bg-background text-text">
      <header className="flex items-center gap-4 border-b border-border px-4 py-3">
        <h1 className="whitespace-nowrap text-lg font-semibold text-text">Aether Sovereign OS</h1>
        <div className="w-full max-w-xl">
          <SearchBar />
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="w-72 shrink-0 overflow-y-auto border-r border-border p-4">
          <FilterPanel />
          <div className="mt-5">
            <DateRangeInputs />
          </div>
          <div className="mt-5">
            <ResearchPanel />
          </div>
        </aside>

        <main className="relative flex-1">
          <MapView />
        </main>

        <aside className="w-80 shrink-0 overflow-y-auto border-l border-border p-4">
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
        </aside>
      </div>

      <footer className="border-t border-border p-3">
        <TimelineScrubber />
      </footer>
    </div>
  )
}

export default App
