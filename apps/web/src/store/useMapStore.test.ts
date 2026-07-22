import { beforeEach, describe, expect, it } from 'vitest'
import { useMapStore } from './useMapStore'

describe('useMapStore', () => {
  beforeEach(() => {
    useMapStore.getState().resetFilters()
    useMapStore.getState().setResults([])
    useMapStore.getState().setSelectedEntityId(null)
  })

  it('updates the query filter', () => {
    useMapStore.getState().setQuery('acme holdings')
    expect(useMapStore.getState().filters.query).toBe('acme holdings')
  })

  it('resetFilters clears all filter fields', () => {
    useMapStore.getState().setQuery('x')
    useMapStore.getState().setSource('newsapi')
    useMapStore.getState().setEntityType('business')
    useMapStore.getState().resetFilters()

    expect(useMapStore.getState().filters).toEqual({
      query: '',
      source: null,
      entityType: null,
      dateFrom: null,
      dateTo: null,
    })
  })

  it('toggleLayer flips only the targeted layer', () => {
    const before = useMapStore.getState().layers
    useMapStore.getState().toggleLayer('newsHeatmap')
    const after = useMapStore.getState().layers

    expect(after.newsHeatmap).toBe(!before.newsHeatmap)
    expect(after.entities).toBe(before.entities)
  })

  it('toggleEntityTypeVisibility removes and re-adds a type', () => {
    expect(useMapStore.getState().visibleEntityTypes.has('business')).toBe(true)

    useMapStore.getState().toggleEntityTypeVisibility('business')
    expect(useMapStore.getState().visibleEntityTypes.has('business')).toBe(false)

    useMapStore.getState().toggleEntityTypeVisibility('business')
    expect(useMapStore.getState().visibleEntityTypes.has('business')).toBe(true)
  })

  it('setBaseStyle updates the base map style', () => {
    useMapStore.getState().setBaseStyle('satellite')
    expect(useMapStore.getState().baseStyle).toBe('satellite')
  })
})
