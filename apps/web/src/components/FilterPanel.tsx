import { ENTITY_TYPES } from '@/lib/api'
import { BASE_STYLES, type BaseStyle, useMapStore } from '@/store/useMapStore'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'

const SOURCES = [
  'openstreetmap',
  'newsapi',
  'opencorporates',
  'sec_edgar',
  'census_tiger',
  'usgs_national_map',
  'gdelt',
  'data_gov',
  'fema_nfhl',
  'noaa_nws_alerts',
] as const

const BASE_STYLE_LABELS: Record<BaseStyle, string> = {
  streets: 'Streets',
  satellite: 'Satellite',
  outdoors: 'Outdoors',
  light: 'Light',
  satelliteOnly: 'Satellite (no labels)',
  navigationDay: 'Navigation (day)',
  navigationNight: 'Navigation (night)',
}

export function FilterPanel() {
  const filters = useMapStore((s) => s.filters)
  const setSource = useMapStore((s) => s.setSource)
  const setEntityType = useMapStore((s) => s.setEntityType)
  const resetFilters = useMapStore((s) => s.resetFilters)
  const baseStyle = useMapStore((s) => s.baseStyle)
  const setBaseStyle = useMapStore((s) => s.setBaseStyle)
  const layers = useMapStore((s) => s.layers)
  const toggleLayer = useMapStore((s) => s.toggleLayer)
  const visibleEntityTypes = useMapStore((s) => s.visibleEntityTypes)
  const toggleEntityTypeVisibility = useMapStore((s) => s.toggleEntityTypeVisibility)

  return (
    <div className="space-y-3 sm:space-y-5">
      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">Base map</h3>
        <div className="flex flex-wrap gap-1" role="group" aria-label="Base map style">
          {(Object.keys(BASE_STYLES) as BaseStyle[]).map((style) => (
            <Button
              key={style}
              size="sm"
              variant={baseStyle === style ? 'default' : 'outline'}
              aria-pressed={baseStyle === style}
              onClick={() => setBaseStyle(style)}
              className="text-xs"
            >
              {BASE_STYLE_LABELS[style].split(' ')[0]}
            </Button>
          ))}
        </div>
      </div>

      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
          Entity type
        </h3>
        <div className="space-y-1.5">
          {ENTITY_TYPES.map((type) => (
            <label key={type} className="flex items-center gap-2 text-xs sm:text-sm">
              <Checkbox
                checked={filters.entityType === type}
                onCheckedChange={(checked) => setEntityType(checked ? type : null)}
              />
              {type.replace('_', ' ')}
            </label>
          ))}
        </div>
      </div>

      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">Source</h3>
        <div className="space-y-1.5">
          {SOURCES.map((source) => (
            <label key={source} className="flex items-center gap-2 text-xs sm:text-sm">
              <Checkbox
                checked={filters.source === source}
                onCheckedChange={(checked) => setSource(checked ? source : null)}
              />
              {source.replace(/_/g, ' ')}
            </label>
          ))}
        </div>
      </div>

      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
          Map layers
        </h3>
        <div className="space-y-1.5">
          <label className="flex items-center gap-2 text-xs sm:text-sm">
            <Checkbox checked={layers.entities} onCheckedChange={() => toggleLayer('entities')} />
            Entity markers
          </label>
          {layers.entities && (
            <div className="ml-4 space-y-1 border-l border-border pl-2 sm:ml-6 sm:pl-3">
              {ENTITY_TYPES.map((type) => (
                <label key={type} className="flex items-center gap-2 text-xs text-text-muted">
                  <Checkbox
                    checked={visibleEntityTypes.has(type)}
                    onCheckedChange={() => toggleEntityTypeVisibility(type)}
                  />
                  {type.replace('_', ' ')}
                </label>
              ))}
            </div>
          )}
          <label className="flex items-center gap-2 text-xs sm:text-sm">
            <Checkbox checked={layers.newsHeatmap} onCheckedChange={() => toggleLayer('newsHeatmap')} />
            News density heatmap
          </label>
          <label className="flex items-center gap-2 text-xs sm:text-sm">
            <Checkbox checked={layers.terrain} onCheckedChange={() => toggleLayer('terrain')} />
            3D terrain (elevation)
          </label>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={layers.landCover} onCheckedChange={() => toggleLayer('landCover')} />
            Land cover (NLCD)
          </label>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={layers.alerts} onCheckedChange={() => toggleLayer('alerts')} />
            Alert pins
          </label>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={layers.censusTracts} onCheckedChange={() => toggleLayer('censusTracts')} />
            Census tract boundaries
          </label>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={layers.zoningDistricts} onCheckedChange={() => toggleLayer('zoningDistricts')} />
            Zoning districts
          </label>
        </div>
      </div>

      <Button variant="outline" size="sm" onClick={resetFilters} className="w-full">
        Reset filters
      </Button>
    </div>
  )
}

export function DateRangeInputs() {
  const filters = useMapStore((s) => s.filters)
  const setDateRange = useMapStore((s) => s.setDateRange)

  return (
    <div className="grid grid-cols-2 gap-2">
      <div>
        <Label htmlFor="date-from">From</Label>
        <Input
          id="date-from"
          type="date"
          value={filters.dateFrom ?? ''}
          onChange={(e) => setDateRange(e.target.value || null, filters.dateTo)}
        />
      </div>
      <div>
        <Label htmlFor="date-to">To</Label>
        <Input
          id="date-to"
          type="date"
          value={filters.dateTo ?? ''}
          onChange={(e) => setDateRange(filters.dateFrom, e.target.value || null)}
        />
      </div>
    </div>
  )
}
