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
  const debouncedQuery = useDebounced(filters.query, 300)
  const requestId = useRef(0)

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
      .catch(() => {
        if (id === requestId.current) setSuggestions([])
      })

    search({
      q,
      source: filters.source ?? undefined,
      entity_type: filters.entityType ?? undefined,
      date_from: filters.dateFrom ?? undefined,
      date_to: filters.dateTo ?? undefined,
      limit: 50,
    })
      .then((res) => setResults(res.results))
      .catch(() => setResults([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQuery, filters.source, filters.entityType, filters.dateFrom, filters.dateTo])

  return (
    <div className="relative">
      <div className="flex items-center gap-2 rounded-md border border-border bg-surface px-3">
        <Search className="h-4 w-4 text-text-muted" aria-hidden="true" />
        <Input
          className="border-0 bg-transparent px-0 focus-visible:ring-0"
          placeholder="Search an address or public record..."
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
            aria-label="Clear search"
            onClick={() => {
              setQuery('')
              setSuggestions([])
            }}
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </Button>
        )}
      </div>

      {open && suggestions.length > 0 && (
        <ul id="search-suggestions" role="listbox" className="absolute z-10 mt-1 w-full rounded-md border border-border bg-surface shadow-lg">
          {suggestions.map((hit) => (
            <li key={hit.place_id} role="option" aria-selected="false">
              <button
                type="button"
                className="w-full truncate px-3 py-2 text-left text-sm hover:bg-surface-2"
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
    </div>
  )
}
