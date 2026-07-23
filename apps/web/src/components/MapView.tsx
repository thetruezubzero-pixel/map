import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { MapContainer, TileLayer, GeoJSON, Marker, Popup, ZoomControl, Circle } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { Feature, FeatureCollection, Geometry, Point } from 'geojson'
import { BASE_STYLES, useMapStore } from '@/store/useMapStore'
import { useAlertStore } from '@/store/useAlertStore'
import { getBoundaries, getHeatmap, search, type AlertSeverity, type BoundaryType } from '@/lib/api'
import { Badge } from '@/components/ui/badge'

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

const NLCD_WMS_TILE_URL =
  'https://www.mrlc.gov/geoserver/mrlc_display/wms?service=WMS&version=1.1.1&request=GetMap' +
  '&layers=NLCD_Land_Cover&bbox={bbox}&width=256&height=256&srs=EPSG:3857&format=image/png&transparent=true'

const BOUNDARY_COLORS: Record<BoundaryType, string> = {
  census_tract: '#34d3a3',
  zoning: '#7c5cff',
}

// Fix Leaflet icon paths for marker rendering
delete (L.Icon.Default.prototype as any)._getIconUrl
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
})

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
  const mapRef = useRef<L.Map>(null)
  const boundaryRequestIds = useRef<Record<BoundaryType, number>>({ census_tract: 0, zoning: 0 })

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

  const fetchBoundaryLayer = useCallback(
    (boundaryType: BoundaryType, setter: (data: FeatureCollection | null) => void) => {
      if (!mapRef.current) return
      const bounds = mapRef.current.getBounds()
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

  const handleMapClick = useCallback(
    async (e: L.LeafletMouseEvent) => {
      const { lat, lng } = e.latlng
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

  const handleMove = useCallback(() => {
    if (!mapRef.current) return
    const center = mapRef.current.getCenter()
    const zoom = mapRef.current.getZoom()
    setViewport({
      longitude: center.lng,
      latitude: center.lat,
      zoom,
    })
    if (layers.censusTracts) fetchBoundaryLayer('census_tract', setCensusTractData)
    if (layers.zoningDistricts) fetchBoundaryLayer('zoning', setZoningData)
  }, [layers.censusTracts, layers.zoningDistricts, fetchBoundaryLayer, setViewport])

  // Attach map event handlers after mount
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    map.on('click', handleMapClick)
    map.on('moveend', handleMove)
    return () => {
      map.off('click', handleMapClick)
      map.off('moveend', handleMove)
    }
  }, [handleMapClick, handleMove])

  const currentTileLayer = BASE_STYLES[baseStyle]

  const getPolygonStyle = (color: string) => ({
    fillColor: color,
    fillOpacity: 0.12,
    color: color,
    weight: 1,
    opacity: 0.6,
  })

  return (
    <MapContainer
      ref={mapRef}
      center={[viewport.latitude, viewport.longitude]}
      zoom={viewport.zoom}
      style={{ width: '100%', height: '100%' }}
      zoomControl={false}
    >
      <ZoomControl position="topright" />
      <TileLayer
        url={currentTileLayer.tiles}
        attribution={currentTileLayer.attribution}
        maxZoom={19}
        tileSize={256}
      />

      {layers.landCover && (
        <TileLayer
          url={NLCD_WMS_TILE_URL}
          attribution="© MRLC"
          opacity={0.55}
          maxZoom={14}
        />
      )}

      {layers.censusTracts && censusTractData && (
        <GeoJSON data={censusTractData} style={() => getPolygonStyle(BOUNDARY_COLORS.census_tract)} />
      )}

      {layers.zoningDistricts && zoningData && (
        <GeoJSON data={zoningData} style={() => getPolygonStyle(BOUNDARY_COLORS.zoning)} />
      )}

      {layers.newsHeatmap &&
        heatmapData?.features.map((f, idx) => {
          const [lon, lat] = f.geometry.coordinates as [number, number]
          const count = f.properties?.count ?? 0
          const maxCount = Math.max(...heatmapData.features.map((feat) => feat.properties?.count ?? 0), 1)
          const opacity = Math.min(count / maxCount, 1)
          return (
            <Circle
              key={`heatmap-${idx}`}
              center={[lat, lon]}
              radius={5000 + count * 500}
              fillColor="#ff5c7c"
              fillOpacity={opacity * 0.7}
              stroke={false}
            />
          )
        })}

      {layers.entities &&
        visibleResults.map((r) => (
          <Marker
            key={r.id}
            position={[r.lat as number, r.lon as number]}
            icon={L.divIcon({
              html: `<div style="background: ${ENTITY_COLORS[r.entity_type] ?? '#7c5cff'}; border: 2px solid white;" class="h-3 w-3 rounded-full cursor-pointer"></div>`,
              iconSize: [12, 12],
              className: 'entity-marker',
            })}
            eventHandlers={{
              click: () => setSelectedEntityId(r.id),
            }}
          />
        ))}

      {layers.alerts &&
        geolocatedAlerts.map((alert) => (
          <Marker
            key={alert.id}
            position={[alert.lat as number, alert.lon as number]}
            icon={L.divIcon({
              html: `<div style="background: ${ALERT_SEVERITY_COLORS[alert.severity]}; border: 2px solid white;" class="h-3.5 w-3.5 rounded-full cursor-pointer animate-pulse" title="${alert.severity}: ${alert.title}"></div>`,
              iconSize: [14, 14],
              className: 'alert-marker',
            })}
          />
        ))}

      {selected && selected.lon != null && selected.lat != null && (
        <Popup
          position={[selected.lat, selected.lon]}
          eventHandlers={{
            remove: () => setSelectedEntityId(null),
          }}
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
    </MapContainer>
  )
}
