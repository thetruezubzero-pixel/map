import { useEffect, useState } from 'react'
import { getSwarmActivity, type SwarmTask } from '@/lib/api'
import { SwarmTaskList } from '@/components/SwarmTaskList'
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

      {!error && <SwarmTaskList tasks={tasks} />}
    </PageShell>
  )
}
