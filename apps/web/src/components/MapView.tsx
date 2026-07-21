import { useCallback, useMemo } from 'react'
import Map, { Marker, NavigationControl, Popup, type MapMouseEvent } from 'react-map-gl/mapbox'
import 'mapbox-gl/dist/mapbox-gl.css'
import { useMapStore } from '@/store/useMapStore'
import { search } from '@/lib/api'
import { Badge } from '@/components/ui/badge'

const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN ?? ''

const ENTITY_COLORS: Record<string, string> = {
  business: '#7c5cff',
  government_filing: '#34d3a3',
  location: '#f5a623',
  poi: '#f5a623',
  news_mention: '#ff5c7c',
}

export function MapView() {
  const viewport = useMapStore((s) => s.viewport)
  const setViewport = useMapStore((s) => s.setViewport)
  const results = useMapStore((s) => s.results)
  const setResults = useMapStore((s) => s.setResults)
  const filters = useMapStore((s) => s.filters)
  const selectedEntityId = useMapStore((s) => s.selectedEntityId)
  const setSelectedEntityId = useMapStore((s) => s.setSelectedEntityId)
  const layers = useMapStore((s) => s.layers)

  const selected = useMemo(
    () => results.find((r) => r.id === selectedEntityId) ?? null,
    [results, selectedEntityId],
  )

  // Click-to-lookup: run a radius search around the clicked point.
  const handleClick = useCallback(
    async (event: MapMouseEvent) => {
      const { lng, lat } = event.lngLat
      try {
        const res = await search({
          lat,
          lon: lng,
          radius_m: 2000,
          entity_type: filters.entityType ?? undefined,
          source: filters.source ?? undefined,
          date_from: filters.dateFrom ?? undefined,
          date_to: filters.dateTo ?? undefined,
          limit: 50,
        })
        setResults(res.results)
        if (res.results[0]) setSelectedEntityId(res.results[0].id)
      } catch (err) {
        console.error('click-to-lookup failed', err)
      }
    },
    [filters, setResults, setSelectedEntityId],
  )

  if (!MAPBOX_TOKEN) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-surface text-center text-sm text-text-muted p-8">
        Set <code className="mx-1 rounded bg-surface-2 px-1 py-0.5">VITE_MAPBOX_ACCESS_TOKEN</code>
        in apps/web/.env to enable the map.
      </div>
    )
  }

  return (
    <Map
      mapboxAccessToken={MAPBOX_TOKEN}
      initialViewState={viewport}
      onMoveEnd={(evt) =>
        setViewport({
          longitude: evt.viewState.longitude,
          latitude: evt.viewState.latitude,
          zoom: evt.viewState.zoom,
        })
      }
      onClick={handleClick}
      mapStyle="mapbox://styles/mapbox/dark-v11"
      style={{ width: '100%', height: '100%' }}
    >
      <NavigationControl position="top-right" />

      {layers.entities &&
        results
          .filter((r) => r.lon != null && r.lat != null)
          .map((r) => (
            <Marker
              key={r.id}
              longitude={r.lon as number}
              latitude={r.lat as number}
              onClick={(e) => {
                e.originalEvent.stopPropagation()
                setSelectedEntityId(r.id)
              }}
            >
              <div
                className="h-3 w-3 cursor-pointer rounded-full border-2 border-white"
                style={{ background: ENTITY_COLORS[r.entity_type] ?? '#7c5cff' }}
              />
            </Marker>
          ))}

      {selected && selected.lon != null && selected.lat != null && (
        <Popup
          longitude={selected.lon}
          latitude={selected.lat}
          onClose={() => setSelectedEntityId(null)}
          closeOnClick={false}
          anchor="bottom"
        >
          <div className="space-y-1 p-1">
            <p className="font-medium text-text-h">{selected.name}</p>
            <Badge variant="outline">{selected.entity_type}</Badge>
            <p className="text-xs text-text-muted">
              source: {selected.source}
              {selected.license ? ` · ${selected.license}` : ''}
            </p>
          </div>
        </Popup>
      )}
    </Map>
  )
}
