import { create } from 'zustand'
import { ENTITY_TYPES, type EntityType, type SearchResult } from '@/lib/api'

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

export const BASE_STYLES = {
  streets: 'mapbox://styles/mapbox/dark-v11',
  satellite: 'mapbox://styles/mapbox/satellite-streets-v12',
  outdoors: 'mapbox://styles/mapbox/outdoors-v12',
} as const
export type BaseStyle = keyof typeof BASE_STYLES

interface Layers {
  /** Entity markers (filtered further by visibleEntityTypes below). */
  entities: boolean
  /** ES geohash-grid density heatmap, scoped to news_mention records. */
  newsHeatmap: boolean
  /** Mapbox native 3D terrain (USGS-derived DEM tiles via Mapbox). */
  terrain: boolean
  /** NLCD land cover raster overlay (MRLC public WMS). */
  landCover: boolean
  /** Phase 4 real-time alert pins (useAlertStore) -- only alerts that
   * carry lat/lon render; most don't yet, see AlertPanel's geofence
   * caveat. */
  alerts: boolean
}

interface MapState {
  viewport: Viewport
  setViewport: (v: Viewport) => void

  baseStyle: BaseStyle
  setBaseStyle: (style: BaseStyle) => void

  filters: Filters
  setQuery: (q: string) => void
  setSource: (source: string | null) => void
  setEntityType: (entityType: EntityType | null) => void
  setDateRange: (from: string | null, to: string | null) => void
  resetFilters: () => void

  results: SearchResult[]
  setResults: (results: SearchResult[]) => void

  /** Which entity types render as markers -- independent of the search
   * query filter, so a user can search broadly then hide a layer. */
  visibleEntityTypes: Set<EntityType>
  toggleEntityTypeVisibility: (entityType: EntityType) => void

  selectedEntityId: string | null
  setSelectedEntityId: (id: string | null) => void

  layers: Layers
  toggleLayer: (layer: keyof Layers) => void
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

  baseStyle: 'streets',
  setBaseStyle: (baseStyle) => set({ baseStyle }),

  filters: defaultFilters,
  setQuery: (query) => set((s) => ({ filters: { ...s.filters, query } })),
  setSource: (source) => set((s) => ({ filters: { ...s.filters, source } })),
  setEntityType: (entityType) => set((s) => ({ filters: { ...s.filters, entityType } })),
  setDateRange: (dateFrom, dateTo) => set((s) => ({ filters: { ...s.filters, dateFrom, dateTo } })),
  resetFilters: () => set({ filters: defaultFilters }),

  results: [],
  setResults: (results) => set({ results }),

  visibleEntityTypes: new Set(ENTITY_TYPES),
  toggleEntityTypeVisibility: (entityType) =>
    set((s) => {
      const next = new Set(s.visibleEntityTypes)
      if (next.has(entityType)) next.delete(entityType)
      else next.add(entityType)
      return { visibleEntityTypes: next }
    }),

  selectedEntityId: null,
  setSelectedEntityId: (selectedEntityId) => set({ selectedEntityId }),

  layers: { entities: true, newsHeatmap: false, terrain: false, landCover: false, alerts: true },
  toggleLayer: (layer) => set((s) => ({ layers: { ...s.layers, [layer]: !s.layers[layer] } })),
}))
