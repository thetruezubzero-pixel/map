import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getSwarmActivity, type SwarmTask } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { PageShell } from './PageShell'

const POLL_INTERVAL_MS = 10_000

export function SwarmPage() {
  const [tasks, setTasks] = useState<SwarmTask[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const poll = () => {
      getSwarmActivity(50)
        .then((res) => {
          if (!cancelled) {
            setTasks(res.tasks)
            setError(null)
          }
        })
        .catch((err) => {
          if (!cancelled) setError(err instanceof Error ? err.message : 'failed to load swarm activity')
        })
    }
    poll()
    const interval = setInterval(poll, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  return (
    <PageShell title="Live swarm activity">
      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}
      <p className="mb-4 text-sm text-text-muted">
        Every consensus round across every role, most recent first. Refreshes every 10s.
      </p>

      <div className="space-y-3">
        {tasks.map((task) => (
          <div key={task.id} className="rounded-md border border-border bg-surface p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-medium text-text">{task.role.replace('_', ' ')}</span>
              <span className="flex items-center gap-2 text-xs text-text-muted">
                {task.reward_applied ? <Badge variant="success">settled</Badge> : <Badge variant="outline">awaiting review</Badge>}
                {new Date(task.created_at).toLocaleString()}
              </span>
            </div>
            <div className="space-y-1">
              {task.votes.map((v) => (
                <div key={v.agent_id} className="flex items-center justify-between text-xs">
                  <Link to={`/agents/${v.agent_id}`} className="text-accent hover:underline">
                    {v.agent_level} agent
                  </Link>
                  <span className="text-text-muted">
                    output: {v.output_key} · weight {v.weight.toFixed(2)} · confidence {(v.confidence * 100).toFixed(0)}%
                    {v.agent_id === task.winning_agent_id ? ' · won' : ''}
                  </span>
                </div>
              ))}
              {task.votes.length === 0 && (
                <p className="text-xs text-text-muted">
                  No votes recorded (single-agent/degraded mode, or a data_retriever bookkeeping row).
                </p>
              )}
            </div>
          </div>
        ))}
        {tasks.length === 0 && !error && <p className="text-sm text-text-muted">No swarm activity yet.</p>}
      </div>
    </PageShell>
  )
}
