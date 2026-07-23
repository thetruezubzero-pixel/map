import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { MapAction, SearchResult } from '@/lib/api'
import { applyMapActions } from './mapActions'
import { useMapStore } from '@/store/useMapStore'
import { ENTITY_TYPES } from '@/lib/api'

// Mock the network layer -- these tests assert that agent actions drive the
// store correctly, not that Nominatim/Postgres are reachable.
vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    geocode: vi.fn(),
    search: vi.fn(),
  }
})

const { geocode, search } = await import('@/lib/api')

const sampleResult: SearchResult = {
  id: 'e1',
  name: 'Acme Widgets LLC',
  entity_type: 'business',
  source: 'opencorporates',
  license: null,
  lon: -97.74,
  lat: 30.27,
  distance_m: 120,
  retrieved_at: '2026-01-01T00:00:00Z',
}

describe('applyMapActions', () => {
  beforeEach(() => {
    vi.mocked(geocode).mockReset()
    vi.mocked(search).mockReset()
    useMapStore.getState().resetFilters()
    useMapStore.getState().setResults([])
    useMapStore.getState().setSelectedEntityId(null)
    useMapStore.getState().setBaseStyle('streets')
    useMapStore.getState().setVisibleEntityTypes(new Set(ENTITY_TYPES))
    useMapStore.getState().setLayer('newsHeatmap', false)
  })

  it('set_base_style switches the base map', async () => {
    await applyMapActions([{ type: 'set_base_style', base_style: 'satellite' }])
    expect(useMapStore.getState().baseStyle).toBe('satellite')
  })

  it('ignores an unknown base style and notes it', async () => {
    const res = await applyMapActions([{ type: 'set_base_style', base_style: 'hologram' }])
    expect(useMapStore.getState().baseStyle).toBe('streets')
    expect(res.notes.join(' ')).toContain('hologram')
  })

  it('toggle_layer sets a layer to the explicit state', async () => {
    await applyMapActions([{ type: 'toggle_layer', layer: 'newsHeatmap', enabled: true }])
    expect(useMapStore.getState().layers.newsHeatmap).toBe(true)
    await applyMapActions([{ type: 'toggle_layer', layer: 'newsHeatmap', enabled: false }])
    expect(useMapStore.getState().layers.newsHeatmap).toBe(false)
  })

  it('show_entity_types restricts visible types to the allowlisted subset', async () => {
    await applyMapActions([{ type: 'show_entity_types', entity_types: ['business', 'person', 'poi'] }])
    const visible = useMapStore.getState().visibleEntityTypes
    expect(visible.has('business')).toBe(true)
    expect(visible.has('poi')).toBe(true)
    expect(visible.has('news_mention')).toBe(false)
    // 'person' is not a valid EntityType and must be filtered out entirely.
    expect([...visible]).not.toContain('person')
  })

  it('reset clears filters, results, selection, and restores all types', async () => {
    useMapStore.getState().setResults([sampleResult])
    useMapStore.getState().setSelectedEntityId('e1')
    useMapStore.getState().setVisibleEntityTypes(new Set(['business']))

    await applyMapActions([{ type: 'reset' }])

    expect(useMapStore.getState().results).toEqual([])
    expect(useMapStore.getState().selectedEntityId).toBeNull()
    expect(useMapStore.getState().visibleEntityTypes.size).toBe(ENTITY_TYPES.length)
  })

  it('search near a place geocodes, centers the map, and populates results', async () => {
    vi.mocked(geocode).mockResolvedValue([
      { place_id: 1, display_name: 'Austin, TX', lat: '30.2672', lon: '-97.7431', type: 'city' },
    ])
    vi.mocked(search).mockResolvedValue({ results: [sampleResult], count: 1 })

    const action: MapAction = { type: 'search', entity_type: 'business', near_place: 'austin' }
    const res = await applyMapActions([action])

    expect(geocode).toHaveBeenCalledWith('austin', 1)
    // search called with the geocoded center + a radius
    const params = vi.mocked(search).mock.calls[0][0]
    expect(params.lat).toBeCloseTo(30.2672)
    expect(params.lon).toBeCloseTo(-97.7431)
    expect(params.radius_m).toBeGreaterThan(0)
    expect(params.entity_type).toBe('business')

    expect(useMapStore.getState().results).toEqual([sampleResult])
    expect(useMapStore.getState().viewport.latitude).toBeCloseTo(30.2672)
    expect(res.resultCount).toBe(1)
  })

  it('search still runs (without geo filter) when the place cannot be geocoded', async () => {
    vi.mocked(geocode).mockResolvedValue([])
    vi.mocked(search).mockResolvedValue({ results: [], count: 0 })

    const res = await applyMapActions([{ type: 'search', near_place: 'nowheresville', q: 'coffee' }])

    const params = vi.mocked(search).mock.calls[0][0]
    expect(params.lat).toBeUndefined()
    expect(params.q).toBe('coffee')
    expect(res.notes.join(' ').toLowerCase()).toContain("couldn't locate")
  })

  it('batches style + search so both take effect in one call', async () => {
    vi.mocked(geocode).mockResolvedValue([
      { place_id: 1, display_name: 'Austin', lat: '30.27', lon: '-97.74', type: 'city' },
    ])
    vi.mocked(search).mockResolvedValue({ results: [sampleResult], count: 1 })

    await applyMapActions([
      { type: 'set_base_style', base_style: 'navigationNight' },
      { type: 'search', entity_type: 'business', near_place: 'austin' },
    ])

    expect(useMapStore.getState().baseStyle).toBe('navigationNight')
    expect(useMapStore.getState().results).toEqual([sampleResult])
  })

  it('surfaces a note when the search call fails', async () => {
    vi.mocked(search).mockRejectedValue(new Error('boom'))
    const res = await applyMapActions([{ type: 'search', entity_type: 'business' }])
    expect(res.notes.join(' ')).toContain('Search failed')
  })
})
