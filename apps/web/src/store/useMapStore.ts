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

// Open-source tile layer definitions (no credentials required)
export const BASE_STYLES = {
  streets: {
    name: 'OpenStreetMap',
    attribution: '© OpenStreetMap contributors',
    tiles: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  },
  satellite: {
    name: 'USGS Satellite',
    attribution: '© USGS',
    tiles: 'https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}',
  },
  outdoors: {
    name: 'OpenTopoMap',
    attribution: '© OpenStreetMap contributors, © OpenTopoMap',
    tiles: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
  },
  light: {
    name: 'CartoDB Positron',
    attribution: '© OpenStreetMap contributors, © CartoDB',
    tiles: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
  },
  satelliteOnly: {
    name: 'GEBCO Elevation',
    attribution: '© GEBCO',
    tiles: 'https://www.gebco.net/data_and_products/gridded_bathymetry_data/',
  },
  navigationDay: {
    name: 'CartoDB Voyager',
    attribution: '© OpenStreetMap contributors, © CartoDB',
    tiles: 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',
  },
  navigationNight: {
    name: 'CartoDB Dark',
    attribution: '© OpenStreetMap contributors, © CartoDB',
    tiles: 'https://{s}.basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}{r}.png',
  },
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
  /** Phase 6 choropleth: research_entity_boundaries polygons, fetched
   * bbox-scoped from GET /boundaries as the map moves. */
  censusTracts: boolean
  zoningDistricts: boolean
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
  /** Replace the whole visible-types set at once -- used by the agent's
   * "show only businesses" style action (see lib/mapActions.ts). */
  setVisibleEntityTypes: (entityTypes: Set<EntityType>) => void

  selectedEntityId: string | null
  setSelectedEntityId: (id: string | null) => void

  layers: Layers
  toggleLayer: (layer: keyof Layers) => void
  /** Set a layer to an explicit on/off state (vs. toggle) -- used by the
   * agent's "show/hide the <layer>" action so the outcome is deterministic
   * regardless of the layer's current state. */
  setLayer: (layer: keyof Layers, enabled: boolean) => void
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
  setVisibleEntityTypes: (visibleEntityTypes) => set({ visibleEntityTypes }),

  selectedEntityId: null,
  setSelectedEntityId: (selectedEntityId) => set({ selectedEntityId }),

  layers: {
    entities: true,
    newsHeatmap: false,
    terrain: false,
    landCover: false,
    alerts: true,
    censusTracts: false,
    zoningDistricts: false,
  },
  toggleLayer: (layer) => set((s) => ({ layers: { ...s.layers, [layer]: !s.layers[layer] } })),
  setLayer: (layer, enabled) => set((s) => ({ layers: { ...s.layers, [layer]: enabled } })),
}))
