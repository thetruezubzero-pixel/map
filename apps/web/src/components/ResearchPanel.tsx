import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { createResearchJob, getSwarmActivity, type SwarmTask } from '@/lib/api'
import { SwarmTaskList } from '@/components/SwarmTaskList'

const POLL_INTERVAL_MS = 10_000

export function ResearchPanel() {
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [swarmTasks, setSwarmTasks] = useState<SwarmTask[]>([])

  const submit = async () => {
    if (!query.trim()) return
    setLoading(true)
    setStatus(null)
    setSwarmTasks([])
    try {
      const res = await createResearchJob(query)
      setJobId(res.job_id)
      setStatus(`Queued for review (${res.status})`)
    } catch (err) {
      setStatus(err instanceof Error ? err.message : 'Failed to queue research job')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!jobId) return
    let cancelled = false
    const poll = () => {
      // Supplementary to the status line above -- a failed poll here
      // shouldn't overwrite or block the job-submission status message.
      getSwarmActivity(20, jobId)
        .then((res) => {
          if (!cancelled) setSwarmTasks(res.tasks)
        })
        .catch(() => {})
    }
    poll()
    const interval = setInterval(poll, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [jobId])

  return (
    <div className="space-y-2 rounded-md border border-border bg-surface p-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
        Research (public records only)
      </h3>
      <Input
        placeholder="e.g. subsidiaries of Acme Holdings in Delaware since 2020"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && submit()}
      />
      <Button size="sm" className="w-full" disabled={loading} onClick={submit}>
        {loading ? 'Queuing…' : 'Start research job'}
      </Button>
      {status && (
        <p className="text-xs text-text-muted" role="alert">
          {status}
        </p>
      )}
      {jobId && <p className="truncate text-xs text-text-muted">job: {jobId}</p>}
      <p className="text-[11px] text-text-muted">
        Business/property records only. Every job queues for human review before finalization.
      </p>
      {jobId && (
        <div className="space-y-1 pt-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-text-muted">Swarm activity for this job</h4>
          <SwarmTaskList tasks={swarmTasks} emptyMessage="No swarm activity recorded for this job yet." />
        </div>
      )}
    </div>
  )
}
