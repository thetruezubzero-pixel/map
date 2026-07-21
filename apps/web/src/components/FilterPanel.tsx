import { ENTITY_TYPES } from '@/lib/api'
import { useMapStore } from '@/store/useMapStore'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'

const SOURCES = ['openstreetmap', 'newsapi', 'opencorporates'] as const

export function FilterPanel() {
  const filters = useMapStore((s) => s.filters)
  const setSource = useMapStore((s) => s.setSource)
  const setEntityType = useMapStore((s) => s.setEntityType)
  const resetFilters = useMapStore((s) => s.resetFilters)
  const layers = useMapStore((s) => s.layers)
  const toggleLayer = useMapStore((s) => s.toggleLayer)

  return (
    <div className="space-y-5">
      <div>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-text-muted">Entity type</h3>
        </div>
        <div className="space-y-2">
          {ENTITY_TYPES.map((type) => (
            <label key={type} className="flex items-center gap-2 text-sm">
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
        <div className="space-y-2">
          {SOURCES.map((source) => (
            <label key={source} className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={filters.source === source}
                onCheckedChange={(checked) => setSource(checked ? source : null)}
              />
              {source}
            </label>
          ))}
        </div>
      </div>

      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">Layers</h3>
        <div className="space-y-2">
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={layers.entities} onCheckedChange={() => toggleLayer('entities')} />
            Entity markers
          </label>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={layers.heatmap} onCheckedChange={() => toggleLayer('heatmap')} />
            Density heatmap
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
