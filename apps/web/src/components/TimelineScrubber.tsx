import { useMemo, useState } from 'react'
import { useMapStore } from '@/store/useMapStore'

const MIN_YEAR = 2015
const CURRENT_YEAR = new Date().getFullYear()

/**
 * Scrubs research_entities.retrieved_at up to a chosen "as of" date, so the
 * map shows the state of public records at that point in time.
 */
export function TimelineScrubber() {
  const setDateRange = useMapStore((s) => s.setDateRange)
  const filters = useMapStore((s) => s.filters)
  const [year, setYear] = useState(CURRENT_YEAR)

  const asOfDate = useMemo(() => `${year}-12-31`, [year])

  return (
    <div className="flex items-center gap-3 rounded-md border border-border bg-surface px-4 py-2">
      <span className="text-xs text-text-muted">{MIN_YEAR}</span>
      <input
        type="range"
        min={MIN_YEAR}
        max={CURRENT_YEAR}
        step={1}
        value={year}
        onChange={(e) => {
          const y = Number(e.target.value)
          setYear(y)
          setDateRange(filters.dateFrom, `${y}-12-31`)
        }}
        className="h-1 flex-1 cursor-pointer appearance-none rounded-full bg-surface-2 accent-accent"
      />
      <span className="text-xs text-text-muted">{CURRENT_YEAR}</span>
      <span className="w-24 text-right text-sm font-medium text-text">as of {asOfDate}</span>
    </div>
  )
}
