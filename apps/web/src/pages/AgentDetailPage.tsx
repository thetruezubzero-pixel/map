import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { getAgent, type AgentDetail } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { PageShell } from './PageShell'

/** Simple weight-over-time sparkline -- SVG polyline, no charting
 * library. This is weight (a real, stored-per-event signal), not
 * "accuracy over time" -- per-task accuracy isn't recorded with its own
 * timestamp series, only cumulative total_tasks/total_successes, so a
 * literal accuracy-over-time heatmap would have to be synthesized;
 * showing the real weight trajectory instead of a fabricated one. */
function WeightSparkline({ trajectory }: { trajectory: AgentDetail['weight_trajectory'] }) {
  if (trajectory.length < 2) {
    return <p className="text-xs text-text-muted">Not enough weight history yet for a trend line.</p>
  }
  const width = 400
  const height = 80
  const weights = trajectory.map((t) => t.weight)
  const min = Math.min(...weights)
  const max = Math.max(...weights)
  const range = max - min || 1
  const points = trajectory
    .map((t, i) => {
      const x = (i / (trajectory.length - 1)) * width
      const y = height - ((t.weight - min) / range) * height
      return `${x},${y}`
    })
    .join(' ')

  return (
    <svg width={width} height={height} className="rounded-md border border-border bg-surface">
      <polyline points={points} fill="none" stroke="#7c5cff" strokeWidth={2} />
    </svg>
  )
}

export function AgentDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [agent, setAgent] = useState<AgentDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    let cancelled = false
    getAgent(id)
      .then((res) => {
        if (!cancelled) setAgent(res)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'failed to load agent')
      })
    return () => {
      cancelled = true
    }
  }, [id])

  if (error) {
    return (
      <PageShell title="Agent">
        <p className="text-sm text-red-400">{error}</p>
      </PageShell>
    )
  }

  if (!agent) {
    return (
      <PageShell title="Agent">
        <p className="text-sm text-text-muted">Loading…</p>
      </PageShell>
    )
  }

  return (
    <PageShell title={`Agent: ${agent.role.replace('_', ' ')}`}>
      <div className="mb-6 flex flex-wrap items-center gap-2">
        <Badge>{agent.level}</Badge>
        <span className="text-sm text-text-muted">{agent.model}</span>
        {agent.graduated && <Badge variant="success">graduated</Badge>}
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
        <div className="rounded-md border border-border bg-surface p-3">
          <p className="text-xs text-text-muted">Current weight</p>
          <p className="text-2xl font-semibold text-text">{agent.current_weight.toFixed(4)}</p>
        </div>
        <div className="rounded-md border border-border bg-surface p-3">
          <p className="text-xs text-text-muted">Accuracy</p>
          <p className="text-2xl font-semibold text-text">
            {agent.accuracy != null ? `${(agent.accuracy * 100).toFixed(1)}%` : '—'}
          </p>
          <p className="text-xs text-text-muted">
            {agent.total_successes}/{agent.total_tasks} tasks
          </p>
        </div>
        <div className="rounded-md border border-border bg-surface p-3">
          <p className="text-xs text-text-muted">Consecutive successes</p>
          <p className="text-2xl font-semibold text-text">{agent.consecutive_successes}</p>
        </div>
      </div>

      <div className="mt-6">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">Weight trajectory</h3>
        <WeightSparkline trajectory={agent.weight_trajectory} />
      </div>

      <div className="mt-6">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
          Recent tasks ({agent.recent_tasks.length})
        </h3>
        <div className="space-y-1.5">
          {agent.recent_tasks.map((t) => (
            <div key={t.id} className="flex items-center justify-between rounded-md border border-border bg-surface px-3 py-1.5 text-xs">
              <span className="text-text-muted">
                {t.role.replace('_', ' ')} · {new Date(t.created_at).toLocaleString()}
              </span>
              <span>
                {t.was_winner && <Badge variant="success">won consensus</Badge>}
                {!t.reward_applied && <Badge variant="outline">pending review</Badge>}
              </span>
            </div>
          ))}
          {agent.recent_tasks.length === 0 && <p className="text-sm text-text-muted">No tasks recorded yet.</p>}
        </div>
      </div>
    </PageShell>
  )
}
