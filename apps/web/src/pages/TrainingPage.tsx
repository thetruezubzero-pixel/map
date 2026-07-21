import { useEffect, useState } from 'react'
import { getTrainingProgress, type TrainingEntry } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { PageShell } from './PageShell'

function ProgressBar({ value, target, label }: { value: number; target: number; label: string }) {
  const pct = Math.min(100, (value / target) * 100)
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs text-text-muted">
        <span>{label}</span>
        <span>
          {value} / {target}
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-surface-2">
        <div className="h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export function TrainingPage() {
  const [userId, setUserId] = useState('')
  const [amateurs, setAmateurs] = useState<TrainingEntry[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    getTrainingProgress(userId || undefined)
      .then((res) => {
        if (!cancelled) setAmateurs(res.amateurs)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'failed to load training progress')
      })
    return () => {
      cancelled = true
    }
  }, [userId])

  return (
    <PageShell title="Amateur training progress">
      <div className="mb-4 max-w-xs">
        <Input placeholder="user_id (blank = platform-wide)" value={userId} onChange={(e) => setUserId(e.target.value)} />
      </div>
      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}
      <p className="mb-4 text-sm text-text-muted">
        Graduation requires BOTH ≥90% lifetime accuracy AND 50 consecutive successes -- a lucky streak with a poor
        lifetime record doesn't graduate an agent out of shadow mode.
      </p>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {amateurs.map((a) => (
          <div key={a.id} className="space-y-3 rounded-md border border-border bg-surface p-4">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-text">{a.role.replace('_', ' ')}</span>
              {a.graduated ? <Badge variant="success">graduated</Badge> : <Badge variant="outline">shadow mode</Badge>}
            </div>
            <p className="text-xs text-text-muted">{a.model}</p>
            <ProgressBar
              value={a.total_tasks ? Math.round((a.accuracy ?? 0) * 100) : 0}
              target={Math.round(a.accuracy_needed * 100)}
              label="Accuracy %"
            />
            <ProgressBar value={a.consecutive_successes} target={a.consecutive_needed} label="Consecutive successes" />
          </div>
        ))}
        {amateurs.length === 0 && !error && <p className="text-sm text-text-muted">No amateur agents yet.</p>}
      </div>
    </PageShell>
  )
}
