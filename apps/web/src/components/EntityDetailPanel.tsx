import { useEffect, useState } from 'react'
import { Download, FileJson, Printer, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { EntityGraphView } from '@/components/EntityGraphView'
import { useMapStore } from '@/store/useMapStore'
import { downloadCSV, downloadJSON, getEntity, type EntityDetail } from '@/lib/api'

export function EntityDetailPanel() {
  const entityId = useMapStore((s) => s.selectedEntityId)
  const setSelectedEntityId = useMapStore((s) => s.setSelectedEntityId)
  const results = useMapStore((s) => s.results)
  const [entity, setEntity] = useState<EntityDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!entityId) {
      setEntity(null)
      return
    }
    let cancelled = false
    setError(null)
    getEntity(entityId)
      .then((e) => !cancelled && setEntity(e))
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : 'failed to load entity'))
    return () => {
      cancelled = true
    }
  }, [entityId])

  if (!entityId) return null

  return (
    <div className="space-y-4 print:text-black">
      <div className="flex items-start justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-muted">Entity detail</h3>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Close entity detail"
          onClick={() => setSelectedEntityId(null)}
          className="print:hidden"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </Button>
      </div>

      {error && <p className="text-xs text-red-400">{error}</p>}

      {entity && (
        <>
          <div>
            <p className="font-medium text-text-h">{entity.name}</p>
            <div className="mt-1 flex flex-wrap gap-1">
              <Badge variant="outline">{entity.entity_type.replace('_', ' ')}</Badge>
              <Badge variant="outline">{entity.source}</Badge>
            </div>
            {/* Source attribution -- every data point links back to its origin. */}
            <p className="mt-2 text-xs text-text-muted">
              {entity.license ?? 'license unknown'} · retrieved {new Date(entity.retrieved_at).toLocaleString()}
            </p>
          </div>

          {Object.keys(entity.metadata ?? {}).length > 0 && (
            <div>
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-muted">
                Filing / record metadata
              </h4>
              <dl className="space-y-1 text-xs">
                {Object.entries(entity.metadata).map(([key, value]) => (
                  <div key={key} className="flex gap-2">
                    <dt className="text-text-muted">{key}:</dt>
                    <dd className="truncate text-text">{String(value)}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}

          {entity.entity_type === 'business' && (
            <div>
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-muted">
                Entity graph
              </h4>
              <EntityGraphView entityId={entity.id} />
            </div>
          )}

          {results.length > 0 && (
            <div>
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-muted">
                Timeline (current results)
              </h4>
              <ol className="max-h-40 space-y-1 overflow-y-auto border-l border-border pl-3 text-xs">
                {[...results]
                  .sort((a, b) => new Date(b.retrieved_at).getTime() - new Date(a.retrieved_at).getTime())
                  .map((r) => (
                    <li key={r.id}>
                      <span className="text-text-muted">{new Date(r.retrieved_at).toLocaleDateString()}</span>{' '}
                      <span className="text-text">{r.name}</span>{' '}
                      <span className="text-text-muted">({r.source})</span>
                    </li>
                  ))}
              </ol>
            </div>
          )}

          <div className="flex gap-2 print:hidden">
            <Button size="sm" variant="outline" onClick={() => downloadJSON(`${entity.id}.json`, entity)}>
              <FileJson className="mr-1 h-3.5 w-3.5" /> JSON
            </Button>
            <Button size="sm" variant="outline" onClick={() => downloadCSV('results.csv', results)}>
              <Download className="mr-1 h-3.5 w-3.5" /> CSV
            </Button>
            <Button size="sm" variant="outline" onClick={() => window.print()}>
              <Printer className="mr-1 h-3.5 w-3.5" /> Print / PDF
            </Button>
          </div>
        </>
      )}
    </div>
  )
}
