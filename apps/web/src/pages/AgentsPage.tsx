import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { listAgents, type AgentSummary } from '@/lib/api'
import { AgentGraph } from '@/components/AgentGraph'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { PageShell } from './PageShell'

const LEVEL_BADGE: Record<string, 'default' | 'outline' | 'success'> = {
  amateur: 'outline',
  actuarial: 'default',
  coordinator: 'success',
}

export function AgentsPage() {
  const navigate = useNavigate()
  const [userId, setUserId] = useState('')
  const [agents, setAgents] = useState<AgentSummary[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listAgents(userId || undefined)
      .then((res) => {
        if (!cancelled) setAgents(res)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'failed to load agents')
      })
    return () => {
      cancelled = true
    }
  }, [userId])

  return (
    <PageShell title="Agents">
      <div className="mb-4 max-w-xs">
        <Input
          placeholder="user_id (blank = platform-wide view)"
          value={userId}
          onChange={(e) => setUserId(e.target.value)}
        />
      </div>

      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
            Weight graph (node size = weight, color = level, edges = heirloom lineage)
          </h3>
          <AgentGraph agents={agents} onSelect={(id) => navigate(`/agents/${id}`)} />
        </div>

        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
            Roster ({agents.length})
          </h3>
          <div className="max-h-[400px] space-y-2 overflow-y-auto">
            {agents.map((a) => (
              <button
                key={a.id}
                type="button"
                onClick={() => navigate(`/agents/${a.id}`)}
                className="block w-full rounded-md border border-border bg-surface px-3 py-2 text-left text-sm hover:bg-surface-2"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-text">{a.role.replace('_', ' ')}</span>
                  <Badge variant={LEVEL_BADGE[a.level]}>{a.level}</Badge>
                </div>
                <p className="text-xs text-text-muted">
                  {a.model} · weight {a.current_weight.toFixed(3)} ·{' '}
                  {a.accuracy != null ? `${(a.accuracy * 100).toFixed(0)}% accuracy` : 'no tasks yet'}
                  {a.level === 'amateur' && !a.graduated ? ' · shadow mode' : ''}
                </p>
              </button>
            ))}
            {agents.length === 0 && !error && (
              <p className="text-sm text-text-muted">
                No agents yet -- one submitted /research job seeds the default roster.
              </p>
            )}
          </div>
        </div>
      </div>
    </PageShell>
  )
}
