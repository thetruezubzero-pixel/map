import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { MapAction, SearchResult } from '@/lib/api'
import { applyMapActions, plotLocatedRecords, type LocatableRecord } from './mapActions'
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
    createResearchJob: vi.fn(),
  }
})

const { geocode, search, createResearchJob } = await import('@/lib/api')

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
    vi.mocked(createResearchJob).mockReset()
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

  it('research action launches the swarm and returns the job id (Combine B)', async () => {
    vi.mocked(createResearchJob).mockResolvedValue({ job_id: 'job-123', status: 'queued' })
    const res = await applyMapActions([{ type: 'research', q: 'Acme Corp' }])
    expect(createResearchJob).toHaveBeenCalledWith('Acme Corp')
    expect(res.researchJobId).toBe('job-123')
  })

  it('research with an empty subject does not launch a job', async () => {
    const res = await applyMapActions([{ type: 'research', q: '  ' }])
    expect(createResearchJob).not.toHaveBeenCalled()
    expect(res.researchJobId).toBeNull()
    expect(res.notes.join(' ')).toContain('Nothing specified')
  })

  it('notes when the research launch fails (e.g. rate-limited)', async () => {
    vi.mocked(createResearchJob).mockRejectedValue(new Error('429'))
    const res = await applyMapActions([{ type: 'research', q: 'Acme' }])
    expect(res.researchJobId).toBeNull()
    expect(res.notes.join(' ').toLowerCase()).toContain('rate-limited')
  })
})

describe('plotLocatedRecords (Combine A/B)', () => {
  beforeEach(() => {
    useMapStore.getState().setResults([])
    useMapStore.getState().setSelectedEntityId(null)
    useMapStore.getState().setVisibleEntityTypes(new Set(ENTITY_TYPES))
  })

  const located: LocatableRecord = {
    id: 'g1', name: 'Grounded Co', entity_type: 'business', source: 'opencorporates', lon: -97.7, lat: 30.3,
  }
  const coordless: LocatableRecord = {
    id: 'g2', name: 'No Geo Co', entity_type: 'business', source: 'sec_edgar', lon: null, lat: null,
  }

  it('plots only records that carry coordinates', () => {
    const n = plotLocatedRecords([located, coordless], 'grounding')
    expect(n).toBe(1)
    const results = useMapStore.getState().results
    expect(results).toHaveLength(1)
    expect(results[0].name).toBe('Grounded Co')
    expect(results[0].id).toBe('g1')
  })

  it('synthesizes ids for records that lack one', () => {
    const noId: LocatableRecord = { name: 'Report Row', entity_type: 'location', source: 'osm', lon: 1, lat: 2 }
    plotLocatedRecords([noId], 'research:job-9')
    expect(useMapStore.getState().results[0].id).toBe('research:job-9:0')
  })

  it('returns 0 and leaves results untouched when nothing has coordinates', () => {
    useMapStore.getState().setResults([{ ...located, id: 'existing' } as SearchResult])
    const n = plotLocatedRecords([coordless], 'grounding')
    expect(n).toBe(0)
    expect(useMapStore.getState().results[0].id).toBe('existing') // unchanged
  })
})
