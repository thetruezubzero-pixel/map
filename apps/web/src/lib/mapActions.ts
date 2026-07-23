import {
  ENTITY_TYPES,
  geocode,
  search,
  type EntityType,
  type MapAction,
  type SearchParams,
} from '@/lib/api'
import { BASE_STYLES, useMapStore, type BaseStyle, type Filters } from '@/store/useMapStore'

// The frontend half of the "agent operates the map" spine. Each MapAction
// the agent emits (app/agents/map_intent.py) is executed here against
// useMapStore -- this is the single dispatch point where every current and
// future agent capability plugs in. Adding a new action type is: one case
// here + one matcher in the backend parser.
//
// Runs outside React (via useMapStore.getState()) so it's callable from the
// command bar, the chat page, or anywhere else without prop-drilling.

const LAYER_KEYS = [
  'entities',
  'newsHeatmap',
  'terrain',
  'landCover',
  'alerts',
  'censusTracts',
  'zoningDistricts',
] as const
type LayerKey = (typeof LAYER_KEYS)[number]

function isEntityType(v: string | null | undefined): v is EntityType {
  return !!v && (ENTITY_TYPES as readonly string[]).includes(v)
}
function isBaseStyle(v: string | null | undefined): v is BaseStyle {
  return !!v && v in BASE_STYLES
}
function isLayerKey(v: string | null | undefined): v is LayerKey {
  return !!v && (LAYER_KEYS as readonly string[]).includes(v)
}

// A default zoom to settle on when the agent moves us to a named place but
// doesn't specify one -- city-level, the common "show me near X" case.
const PLACE_ZOOM = 12

export interface ApplyActionsResult {
  /** Human-readable notes on what actually happened, for optional display
   * (e.g. "couldn't find that place"). Empty when everything succeeded
   * silently. */
  notes: string[]
  /** Number of search results the actions produced, if a search ran. */
  resultCount: number | null
}

/** Resolve a place name to coordinates via the gateway's Nominatim proxy.
 * Returns null (not throws) on miss or network error so one bad place
 * never aborts the rest of the action batch. */
async function resolvePlace(place: string): Promise<{ lat: number; lon: number } | null> {
  try {
    const hits = await geocode(place, 1)
    const hit = hits[0]
    if (!hit) return null
    return { lat: Number(hit.lat), lon: Number(hit.lon) }
  } catch {
    return null
  }
}

/**
 * Execute an ordered batch of agent map-actions. Search actions are
 * collected and run last (once), so "switch to satellite and show
 * businesses near Austin" moves + styles the map and then populates it in
 * a single search rather than fighting over viewport/results mid-batch.
 */
export async function applyMapActions(actions: MapAction[]): Promise<ApplyActionsResult> {
  const store = useMapStore.getState()
  const notes: string[] = []
  let resultCount: number | null = null

  // Non-search actions apply immediately, in order.
  let pendingSearch: MapAction | null = null

  for (const action of actions) {
    switch (action.type) {
      case 'reset': {
        store.resetFilters()
        store.setResults([])
        store.setSelectedEntityId(null)
        store.setVisibleEntityTypes(new Set(ENTITY_TYPES))
        break
      }
      case 'set_base_style': {
        if (isBaseStyle(action.base_style)) store.setBaseStyle(action.base_style)
        else notes.push(`Unknown map style "${action.base_style}".`)
        break
      }
      case 'toggle_layer': {
        if (isLayerKey(action.layer)) store.setLayer(action.layer, action.enabled ?? true)
        else notes.push(`Unknown layer "${action.layer}".`)
        break
      }
      case 'show_entity_types': {
        const types = (action.entity_types ?? []).filter(isEntityType)
        if (types.length) store.setVisibleEntityTypes(new Set(types))
        break
      }
      case 'set_filter': {
        const patch: Partial<Filters> = {}
        if (action.entity_type !== undefined) patch.entityType = isEntityType(action.entity_type) ? action.entity_type : null
        if (action.source !== undefined) patch.source = action.source
        if (isEntityType(patch.entityType)) store.setEntityType(patch.entityType)
        if (action.source !== undefined) store.setSource(action.source)
        if (action.date_from !== undefined || action.date_to !== undefined) {
          store.setDateRange(action.date_from ?? null, action.date_to ?? null)
        }
        break
      }
      case 'set_viewport': {
        if (action.near_place) {
          const coords = await resolvePlace(action.near_place)
          if (coords) store.setViewport({ longitude: coords.lon, latitude: coords.lat, zoom: action.zoom ?? PLACE_ZOOM })
          else notes.push(`Couldn't locate "${action.near_place}".`)
        } else if (action.lat != null && action.lon != null) {
          store.setViewport({ longitude: action.lon, latitude: action.lat, zoom: action.zoom ?? PLACE_ZOOM })
        }
        break
      }
      case 'search': {
        pendingSearch = action // run last, once
        break
      }
      default:
        break
    }
  }

  if (pendingSearch) {
    resultCount = await runSearch(pendingSearch, notes)
  }

  return { notes, resultCount }
}

async function runSearch(action: MapAction, notes: string[]): Promise<number> {
  const store = useMapStore.getState()
  const params: SearchParams = { limit: 100 }

  if (action.q) params.q = action.q
  if (isEntityType(action.entity_type)) params.entity_type = action.entity_type
  if (action.source) params.source = action.source
  if (action.date_from) params.date_from = action.date_from
  if (action.date_to) params.date_to = action.date_to

  // A named place becomes a center + radius, and moves the map there so the
  // results are actually in view.
  if (action.near_place) {
    const coords = await resolvePlace(action.near_place)
    if (coords) {
      params.lat = coords.lat
      params.lon = coords.lon
      params.radius_m = action.radius_m ?? 5000
      store.setViewport({ longitude: coords.lon, latitude: coords.lat, zoom: PLACE_ZOOM })
    } else {
      notes.push(`Couldn't locate "${action.near_place}"; searched without a location filter.`)
    }
  } else if (action.lat != null && action.lon != null) {
    params.lat = action.lat
    params.lon = action.lon
    params.radius_m = action.radius_m ?? 5000
  }

  try {
    const res = await search(params)
    store.setResults(res.results)
    // Make sure whatever type we searched for is actually visible.
    if (isEntityType(action.entity_type)) {
      const visible = new Set(store.visibleEntityTypes)
      visible.add(action.entity_type)
      store.setVisibleEntityTypes(visible)
    }
    if (res.results[0]) store.setSelectedEntityId(res.results[0].id)
    if (res.results.length === 0) notes.push('No matching records found.')
    return res.results.length
  } catch (err) {
    notes.push('Search failed. Please try again.')
    console.error('applyMapActions search failed', err)
    return 0
  }
}
