import { Link } from 'react-router-dom'
import type { SwarmTask } from '@/lib/api'
import { Badge } from '@/components/ui/badge'

// Shared by SwarmPage.tsx (every job) and ResearchPanel.tsx (one job's
// activity, scoped via getSwarmActivity's job_id param) so both surfaces
// render one consensus round identically.
export function SwarmTaskList({
  tasks,
  emptyMessage = 'No swarm activity yet.',
}: {
  tasks: SwarmTask[]
  emptyMessage?: string
}) {
  return (
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
      {tasks.length === 0 && <p className="text-sm text-text-muted">{emptyMessage}</p>}
    </div>
  )
}
