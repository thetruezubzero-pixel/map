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
    <div className="space-y-2 sm:space-y-3">
      {tasks.map((task) => (
        <div key={task.id} className="rounded-md border border-border bg-surface p-2 sm:p-3">
          <div className="mb-2 flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
            <span className="text-xs font-medium text-text sm:text-sm">{task.role.replace('_', ' ')}</span>
            <div className="flex flex-wrap items-center gap-1 sm:gap-2">
              {task.reward_applied ? <Badge variant="success" className="text-xs">settled</Badge> : <Badge variant="outline" className="text-xs">awaiting</Badge>}
              <span className="text-xs text-text-muted">{new Date(task.created_at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
            </div>
          </div>
          <div className="space-y-1 text-xs sm:text-sm">
            {task.votes.map((v) => (
              <div key={v.agent_id} className="flex flex-col gap-1 rounded-sm bg-surface-2 p-1.5 sm:flex-row sm:items-center sm:justify-between">
                <Link to={`/agents/${v.agent_id}`} className="font-medium text-accent hover:underline">
                  {v.agent_level} agent
                </Link>
                <div className="flex flex-wrap gap-1 text-text-muted sm:gap-2">
                  <span className="whitespace-nowrap text-xs">out: {v.output_key}</span>
                  <span className="whitespace-nowrap text-xs">w: {v.weight.toFixed(2)}</span>
                  <span className="whitespace-nowrap text-xs">c: {(v.confidence * 100).toFixed(0)}%</span>
                  {v.agent_id === task.winning_agent_id && <span className="whitespace-nowrap rounded-sm bg-accent/20 px-1 text-xs font-medium text-accent">won</span>}
                </div>
              </div>
            ))}
            {task.votes.length === 0 && (
              <p className="text-xs text-text-muted">
                No votes (single-agent/degraded/data_retriever row).
              </p>
            )}
          </div>
        </div>
      ))}
      {tasks.length === 0 && <p className="text-xs text-text-muted sm:text-sm">{emptyMessage}</p>}
    </div>
  )
}
