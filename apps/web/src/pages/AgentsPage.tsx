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
      <div className="mb-4 max-w-full sm:max-w-xs">
        <Input
          placeholder="user_id (blank = all)"
          value={userId}
          onChange={(e) => setUserId(e.target.value)}
          className="text-xs sm:text-sm"
        />
      </div>

      {error && <p className="mb-4 text-xs text-red-400 sm:text-sm">{error}</p>}

      <div className="grid grid-cols-1 gap-3 sm:gap-6 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
            Weight graph (node size = weight, color = level)
          </h3>
          <AgentGraph agents={agents} onSelect={(id) => navigate(`/agents/${id}`)} />
        </div>

        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
            Roster ({agents.length})
          </h3>
          <div className="max-h-[400px] space-y-1.5 overflow-y-auto sm:space-y-2">
            {agents.map((a) => (
              <button
                key={a.id}
                type="button"
                onClick={() => navigate(`/agents/${a.id}`)}
                className="block w-full rounded-md border border-border bg-surface px-2 py-1.5 text-left text-xs hover:bg-surface-2 sm:px-3 sm:py-2 sm:text-sm"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-text truncate">{a.role.replace('_', ' ')}</span>
                  <Badge variant={LEVEL_BADGE[a.level]} className="text-xs shrink-0">{a.level}</Badge>
                </div>
                <p className="text-xs text-text-muted truncate">
                  {a.model.split('/').pop()} · w:{a.current_weight.toFixed(2)} ·{' '}
                  {a.accuracy != null ? `${(a.accuracy * 100).toFixed(0)}%` : 'new'}
                  {a.level === 'amateur' && !a.graduated ? ' · shadow' : ''}
                </p>
              </button>
            ))}
            {agents.length === 0 && !error && (
              <p className="text-xs text-text-muted sm:text-sm">
                No agents yet -- submit a research job to seed the roster.
              </p>
            )}
          </div>
        </div>
      </div>
    </PageShell>
  )
}
