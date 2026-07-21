import { create } from 'zustand'
import type { EntityType, SearchResult } from '@/lib/api'

export interface Viewport {
  longitude: number
  latitude: number
  zoom: number
}

export interface Filters {
  query: string
  source: string | null
  entityType: EntityType | null
  dateFrom: string | null
  dateTo: string | null
}

interface MapState {
  viewport: Viewport
  setViewport: (v: Viewport) => void

  filters: Filters
  setQuery: (q: string) => void
  setSource: (source: string | null) => void
  setEntityType: (entityType: EntityType | null) => void
  setDateRange: (from: string | null, to: string | null) => void
  resetFilters: () => void

  results: SearchResult[]
  setResults: (results: SearchResult[]) => void

  selectedEntityId: string | null
  setSelectedEntityId: (id: string | null) => void

  layers: { entities: boolean; heatmap: boolean }
  toggleLayer: (layer: keyof MapState['layers']) => void
}

const defaultFilters: Filters = {
  query: '',
  source: null,
  entityType: null,
  dateFrom: null,
  dateTo: null,
}

export const useMapStore = create<MapState>((set) => ({
  viewport: { longitude: -98.5795, latitude: 39.8283, zoom: 3.5 },
  setViewport: (viewport) => set({ viewport }),

  filters: defaultFilters,
  setQuery: (query) => set((s) => ({ filters: { ...s.filters, query } })),
  setSource: (source) => set((s) => ({ filters: { ...s.filters, source } })),
  setEntityType: (entityType) => set((s) => ({ filters: { ...s.filters, entityType } })),
  setDateRange: (dateFrom, dateTo) => set((s) => ({ filters: { ...s.filters, dateFrom, dateTo } })),
  resetFilters: () => set({ filters: defaultFilters }),

  results: [],
  setResults: (results) => set({ results }),

  selectedEntityId: null,
  setSelectedEntityId: (selectedEntityId) => set({ selectedEntityId }),

  layers: { entities: true, heatmap: false },
  toggleLayer: (layer) =>
    set((s) => ({ layers: { ...s.layers, [layer]: !s.layers[layer] } })),
}))
