import { useCallback, useEffect, useMemo, useState } from 'react'
import Map, {
  Layer,
  Marker,
  NavigationControl,
  Popup,
  Source,
  type MapMouseEvent,
} from 'react-map-gl/mapbox'
import type { FeatureCollection, Point } from 'geojson'
import 'mapbox-gl/dist/mapbox-gl.css'
import { BASE_STYLES, useMapStore } from '@/store/useMapStore'
import { getHeatmap, search } from '@/lib/api'
import { Badge } from '@/components/ui/badge'

const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN ?? ''

const ENTITY_COLORS: Record<string, string> = {
  business: '#7c5cff',
  government_filing: '#34d3a3',
  location: '#f5a623',
  poi: '#f5a623',
  news_mention: '#ff5c7c',
}

// MRLC's public WMS (see apps/api/python/app/search/elasticsearch_setup.py
// note on ENRICH for the polygon-data caveat). {bbox-epsg-3857} is a
// Mapbox GL-specific template var for WMS raster sources.
const NLCD_WMS_TILE_URL =
  'https://www.mrlc.gov/geoserver/mrlc_display/wms?service=WMS&version=1.1.1&request=GetMap' +
  '&layers=NLCD_Land_Cover&bbox={bbox-epsg-3857}&width=256&height=256&srs=EPSG:3857&format=image/png&transparent=true'

// Stable object reference (module scope) so the `terrain` prop below
// doesn't change identity every render when the layer is on -- react-map-gl
// diffs this prop and calls mapbox's setTerrain() on identity change.
const TERRAIN_CONFIG = { source: 'mapbox-dem', exaggeration: 1.5 } as const

export function MapView() {
  const viewport = useMapStore((s) => s.viewport)
  const setViewport = useMapStore((s) => s.setViewport)
  const baseStyle = useMapStore((s) => s.baseStyle)
  const results = useMapStore((s) => s.results)
  const setResults = useMapStore((s) => s.setResults)
  const filters = useMapStore((s) => s.filters)
  const visibleEntityTypes = useMapStore((s) => s.visibleEntityTypes)
  const selectedEntityId = useMapStore((s) => s.selectedEntityId)
  const setSelectedEntityId = useMapStore((s) => s.setSelectedEntityId)
  const layers = useMapStore((s) => s.layers)

  const [heatmapData, setHeatmapData] = useState<FeatureCollection<Point> | null>(null)

  const selected = useMemo(
    () => results.find((r) => r.id === selectedEntityId) ?? null,
    [results, selectedEntityId],
  )

  const visibleResults = useMemo(
    () => results.filter((r) => r.lon != null && r.lat != null && visibleEntityTypes.has(r.entity_type)),
    [results, visibleEntityTypes],
  )

  const terrainConfig = layers.terrain ? TERRAIN_CONFIG : undefined

  useEffect(() => {
    if (!layers.newsHeatmap) {
      setHeatmapData(null)
      return
    }
    let cancelled = false
    getHeatmap('news_mention', 5)
      .then((res) => {
        if (cancelled) return
        setHeatmapData({
          type: 'FeatureCollection',
          features: res.buckets.map((b) => ({
            type: 'Feature',
            properties: { count: b.count },
            geometry: { type: 'Point', coordinates: [b.centroid.lon, b.centroid.lat] },
          })),
        })
      })
      .catch((err) => {
        console.error('failed to load news heatmap', err)
        if (!cancelled) setHeatmapData(null)
      })
    return () => {
      cancelled = true
    }
  }, [layers.newsHeatmap])

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
      mapStyle={BASE_STYLES[baseStyle]}
      terrain={terrainConfig}
      style={{ width: '100%', height: '100%' }}
    >
      <NavigationControl position="top-right" />

      {layers.terrain && (
        <Source
          id="mapbox-dem"
          type="raster-dem"
          url="mapbox://mapbox.mapbox-terrain-dem-v1"
          tileSize={512}
          maxzoom={14}
        />
      )}

      {layers.landCover && (
        <Source id="nlcd-land-cover" type="raster" tiles={[NLCD_WMS_TILE_URL]} tileSize={256}>
          <Layer id="nlcd-land-cover-layer" type="raster" paint={{ 'raster-opacity': 0.55 }} />
        </Source>
      )}

      {layers.newsHeatmap && heatmapData && (
        <Source id="news-heatmap" type="geojson" data={heatmapData}>
          <Layer
            id="news-heatmap-layer"
            type="heatmap"
            paint={{
              'heatmap-weight': ['interpolate', ['linear'], ['get', 'count'], 0, 0, 20, 1],
              'heatmap-intensity': 1,
              'heatmap-radius': 30,
              'heatmap-color': [
                'interpolate',
                ['linear'],
                ['heatmap-density'],
                0,
                'rgba(255,92,124,0)',
                1,
                '#ff5c7c',
              ],
              'heatmap-opacity': 0.7,
            }}
          />
        </Source>
      )}

      {layers.entities &&
        visibleResults.map((r) => (
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
