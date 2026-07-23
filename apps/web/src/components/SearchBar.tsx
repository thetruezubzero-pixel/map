import { useEffect, useRef, useState } from 'react'
import { Search, X } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { useMapStore } from '@/store/useMapStore'
import { geocode, search, type GeocodeHit } from '@/lib/api'

function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(t)
  }, [value, delayMs])
  return debounced
}

export function SearchBar() {
  const filters = useMapStore((s) => s.filters)
  const setQuery = useMapStore((s) => s.setQuery)
  const setViewport = useMapStore((s) => s.setViewport)
  const setResults = useMapStore((s) => s.setResults)

  const [suggestions, setSuggestions] = useState<GeocodeHit[]>([])
  const [open, setOpen] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const debouncedQuery = useDebounced(filters.query, 300)
  const requestId = useRef(0)
  const searchRequestId = useRef(0)
  const containerRef = useRef<HTMLDivElement>(null)

  // The suggestions dropdown otherwise has no dismiss path besides picking
  // a suggestion -- confirmed live it stayed open (and visually overlapped
  // the results panel below it) indefinitely on outside click or Escape.
  useEffect(() => {
    if (!open) return
    const handlePointerDown = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [open])

  // Geocode address-autocomplete suggestions need a substantive query (a
  // 1-2 char geocode lookup is noise), but entity search results must
  // reflect the current filters even with an empty query -- otherwise
  // toggling a source/entity-type/date filter on a blank search box does
  // nothing (confirmed live: 0 network requests, "Results (0)" never
  // changes) until the user has separately typed 3+ characters.
  useEffect(() => {
    const q = debouncedQuery.trim()
    if (q.length < 3) {
      setSuggestions([])
      return
    }

    const id = ++requestId.current
    geocode(q, 5)
      .then((hits) => {
        if (id === requestId.current) setSuggestions(hits)
      })
      .catch((err) => {
        if (id !== requestId.current) return
        setSuggestions([])
        console.error('geocode suggestions failed', err)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQuery])

  useEffect(() => {
    const id = ++searchRequestId.current
    search({
      q: debouncedQuery.trim() || undefined,
      source: filters.source ?? undefined,
      entity_type: filters.entityType ?? undefined,
      date_from: filters.dateFrom ?? undefined,
      date_to: filters.dateTo ?? undefined,
      limit: 50,
    })
      .then((res) => {
        if (id !== searchRequestId.current) return
        setResults(res.results)
        setSearchError(null)
      })
      .catch((err) => {
        if (id !== searchRequestId.current) return
        setResults([])
        setSearchError(err instanceof Error ? err.message : 'search failed')
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQuery, filters.source, filters.entityType, filters.dateFrom, filters.dateTo])

  return (
    <div className="relative" ref={containerRef}>
      <div className="flex items-center gap-1 rounded-md border border-border bg-surface px-2 sm:gap-2 sm:px-3">
        <Search className="h-4 w-4 shrink-0 text-text-muted" aria-hidden="true" />
        <Input
          className="border-0 bg-transparent px-0 text-xs focus-visible:ring-0 sm:text-sm"
          placeholder="Search…"
          aria-label="Search an address or public record"
          role="combobox"
          aria-expanded={open && suggestions.length > 0}
          aria-controls="search-suggestions"
          aria-autocomplete="list"
          value={filters.query}
          onChange={(e) => {
            setQuery(e.target.value)
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
        />
        {filters.query && (
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 shrink-0"
            aria-label="Clear search"
            onClick={() => {
              setQuery('')
              setSuggestions([])
            }}
          >
            <X className="h-3 w-3" aria-hidden="true" />
          </Button>
        )}
      </div>

      {open && suggestions.length > 0 && (
        <ul id="search-suggestions" role="listbox" className="absolute left-0 right-0 top-full z-10 mt-1 max-h-[40vh] overflow-y-auto rounded-md border border-border bg-surface shadow-lg sm:max-h-none">
          {suggestions.map((hit) => (
            <li key={hit.place_id} role="option" aria-selected="false">
              <button
                type="button"
                className="w-full truncate px-2 py-1.5 text-left text-xs hover:bg-surface-2 sm:px-3 sm:py-2 sm:text-sm"
                onClick={() => {
                  setViewport({ longitude: Number(hit.lon), latitude: Number(hit.lat), zoom: 14 })
                  setQuery(hit.display_name)
                  setOpen(false)
                }}
              >
                {hit.display_name}
              </button>
            </li>
          ))}
        </ul>
      )}

      {searchError && (
        <p className="mt-1 text-xs text-red-400" role="alert">
          Search failed: {searchError}
        </p>
      )}
    </div>
  )
}
