import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Map, {
  Layer,
  Marker,
  NavigationControl,
  Popup,
  Source,
  type MapMouseEvent,
  type MapRef,
} from 'react-map-gl/mapbox'
import type { Feature, FeatureCollection, Geometry, Point } from 'geojson'
import 'mapbox-gl/dist/mapbox-gl.css'
import { BASE_STYLES, useMapStore } from '@/store/useMapStore'
import { useAlertStore } from '@/store/useAlertStore'
import { getBoundaries, getHeatmap, search, type AlertSeverity, type BoundaryType } from '@/lib/api'
import { Badge } from '@/components/ui/badge'

const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN ?? ''

const ENTITY_COLORS: Record<string, string> = {
  business: '#7c5cff',
  government_filing: '#34d3a3',
  location: '#f5a623',
  poi: '#f5a623',
  news_mention: '#ff5c7c',
}

const ALERT_SEVERITY_COLORS: Record<AlertSeverity, string> = {
  INFO: '#5cb8ff',
  WARNING: '#f5a623',
  CRITICAL: '#ff3b3b',
}

// MRLC's public WMS (see apps/api/python/app/search/elasticsearch_setup.py
// note on ENRICH for the polygon-data caveat). {bbox-epsg-3857} is a
// Mapbox GL-specific template var for WMS raster sources.
const NLCD_WMS_TILE_URL =
  'https://www.mrlc.gov/geoserver/mrlc_display/wms?service=WMS&version=1.1.1&request=GetMap' +
  '&layers=NLCD_Land_Cover&bbox={bbox-epsg-3857}&width=256&height=256&srs=EPSG:3857&format=image/png&transparent=true'

const BOUNDARY_COLORS: Record<BoundaryType, string> = {
  census_tract: '#34d3a3',
  zoning: '#7c5cff',
}

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
  const alerts = useAlertStore((s) => s.alerts)

  const [heatmapData, setHeatmapData] = useState<FeatureCollection<Point> | null>(null)
  const [censusTractData, setCensusTractData] = useState<FeatureCollection | null>(null)
  const [zoningData, setZoningData] = useState<FeatureCollection | null>(null)
  const mapRef = useRef<MapRef>(null)
  // Tracks the last viewport the map itself reported (via onMoveEnd), so
  // the external-change effect below can tell an external setViewport
  // (e.g. a SearchBar geocode-suggestion click) apart from the map's own
  // move and avoid a feedback loop. See the effect for the full story.
  const lastMapReportedViewport = useRef(viewport)
  // fetchBoundaryLayer is called both from the toggle-effect and from
  // onMoveEnd, so a quick pan/toggle sequence can have two in-flight
  // requests for the same layer in flight at once -- this guards against
  // an older bbox's response landing after a newer one and clobbering it.
  const boundaryRequestIds = useRef<Record<BoundaryType, number>>({ census_tract: 0, zoning: 0 })

  // `initialViewState` (below) is read only once at mount -- react-map-gl
  // merges live camera transform with its controlled props on every
  // update, never re-reading initialViewState -- so a later setViewport
  // (SearchBar's geocode-suggestion click, an entity-focus action) was
  // silently ignored and the map never panned. A readiness review
  // confirmed this by tracing the library's _updateViewState. Drive the
  // camera imperatively instead: fly to the new viewport, but only when
  // the change came from *outside* the map. The ref comparison skips the
  // echo of the map's own onMoveEnd (which also calls setViewport),
  // preventing an update feedback loop.
  useEffect(() => {
    const last = lastMapReportedViewport.current
    if (
      last.longitude === viewport.longitude &&
      last.latitude === viewport.latitude &&
      last.zoom === viewport.zoom
    ) {
      return // this change is the map's own onMoveEnd echo -- already there
    }
    lastMapReportedViewport.current = viewport
    mapRef.current?.flyTo({
      center: [viewport.longitude, viewport.latitude],
      zoom: viewport.zoom,
      duration: 1000,
    })
  }, [viewport])

  const geolocatedAlerts = useMemo(
    () => alerts.filter((a) => a.lat != null && a.lon != null),
    [alerts],
  )

  const selected = useMemo(
    () => results.find((r) => r.id === selectedEntityId) ?? null,
    [results, selectedEntityId],
  )

  const visibleResults = useMemo(
    () => results.filter((r) => r.lon != null && r.lat != null && visibleEntityTypes.has(r.entity_type)),
    [results, visibleEntityTypes],
  )

  const terrainConfig = layers.terrain ? TERRAIN_CONFIG : undefined

  // Boundary polygons (research_entity_boundaries) are bbox-scoped rather
  // than fetched in full -- a nationwide census-tract layer is
  // enormous, so /boundaries is queried against the current visible map
  // bounds, same as any tile-service-shaped API. Re-fetched on toggle and
  // on every pan/zoom (onMoveEnd below) while the layer is on.
  const fetchBoundaryLayer = useCallback(
    (boundaryType: BoundaryType, setter: (data: FeatureCollection | null) => void) => {
      const bounds = mapRef.current?.getMap().getBounds()
      if (!bounds) {
        setter(null)
        return
      }
      const requestId = ++boundaryRequestIds.current[boundaryType]
      const bbox = [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()].join(',')
      getBoundaries(boundaryType, bbox)
        .then((res) => {
          if (boundaryRequestIds.current[boundaryType] !== requestId) return
          setter({
            type: 'FeatureCollection',
            features: res.results.map(
              (r): Feature<Geometry> => ({
                type: 'Feature',
                properties: { id: r.id, name: r.name, source: r.source },
                geometry: r.geometry,
              }),
            ),
          })
        })
        .catch((err) => {
          if (boundaryRequestIds.current[boundaryType] !== requestId) return
          console.error(`failed to load ${boundaryType} boundaries`, err)
          setter(null)
        })
    },
    [],
  )

  useEffect(() => {
    if (!layers.censusTracts) {
      setCensusTractData(null)
      return
    }
    fetchBoundaryLayer('census_tract', setCensusTractData)
  }, [layers.censusTracts, fetchBoundaryLayer])

  useEffect(() => {
    if (!layers.zoningDistricts) {
      setZoningData(null)
      return
    }
    fetchBoundaryLayer('zoning', setZoningData)
  }, [layers.zoningDistricts, fetchBoundaryLayer])

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
      <div className="flex h-full w-full items-center justify-center bg-surface p-8 text-center text-sm text-text-muted">
        <p className="max-w-full break-words">
          Set <code className="mx-1 break-all rounded bg-surface-2 px-1 py-0.5">VITE_MAPBOX_ACCESS_TOKEN</code>
          in apps/web/.env to enable the map.
        </p>
      </div>
    )
  }

  return (
    <Map
      ref={mapRef}
      mapboxAccessToken={MAPBOX_TOKEN}
      initialViewState={viewport}
      onMoveEnd={(evt) => {
        const next = {
          longitude: evt.viewState.longitude,
          latitude: evt.viewState.latitude,
          zoom: evt.viewState.zoom,
        }
        // Record what the map reported before pushing it to the store, so
        // the external-change effect recognizes the resulting viewport
        // update as its own echo and doesn't fly the camera back.
        lastMapReportedViewport.current = next
        setViewport(next)
        if (layers.censusTracts) fetchBoundaryLayer('census_tract', setCensusTractData)
        if (layers.zoningDistricts) fetchBoundaryLayer('zoning', setZoningData)
      }}
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

      {layers.censusTracts && censusTractData && (
        <Source id="census-tract-boundaries" type="geojson" data={censusTractData}>
          <Layer
            id="census-tract-fill"
            type="fill"
            paint={{ 'fill-color': BOUNDARY_COLORS.census_tract, 'fill-opacity': 0.12 }}
          />
          <Layer
            id="census-tract-outline"
            type="line"
            paint={{ 'line-color': BOUNDARY_COLORS.census_tract, 'line-width': 1, 'line-opacity': 0.6 }}
          />
        </Source>
      )}

      {layers.zoningDistricts && zoningData && (
        <Source id="zoning-district-boundaries" type="geojson" data={zoningData}>
          <Layer
            id="zoning-district-fill"
            type="fill"
            paint={{ 'fill-color': BOUNDARY_COLORS.zoning, 'fill-opacity': 0.12 }}
          />
          <Layer
            id="zoning-district-outline"
            type="line"
            paint={{ 'line-color': BOUNDARY_COLORS.zoning, 'line-width': 1, 'line-opacity': 0.6 }}
          />
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

      {layers.alerts &&
        geolocatedAlerts.map((alert) => (
          <Marker key={alert.id} longitude={alert.lon as number} latitude={alert.lat as number}>
            <div
              title={`${alert.severity}: ${alert.title}`}
              className="h-3.5 w-3.5 animate-pulse cursor-pointer rounded-full border-2 border-white"
              style={{ background: ALERT_SEVERITY_COLORS[alert.severity] }}
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
