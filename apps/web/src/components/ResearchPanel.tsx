import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { createResearchJob } from '@/lib/api'

export function ResearchPanel() {
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const submit = async () => {
    if (!query.trim()) return
    setLoading(true)
    setStatus(null)
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
      {status && <p className="text-xs text-text-muted">{status}</p>}
      {jobId && <p className="truncate text-xs text-text-muted">job: {jobId}</p>}
      <p className="text-[11px] text-text-muted">
        Business/property records only. Every job queues for human review before finalization.
      </p>
    </div>
  )
}
