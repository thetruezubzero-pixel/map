import { useEffect, useState } from 'react'
import { getStreamingHealth, type StreamingHealth } from '@/lib/api'
import { Badge } from '@/components/ui/badge'

const POLL_INTERVAL_MS = 15_000

function Dot({ ok }: { ok: boolean }) {
  return (
    <span
      className={`inline-block h-2 w-2 rounded-full ${ok ? 'bg-accent-2' : 'bg-red-500'}`}
      role="status"
      aria-label={ok ? 'reachable' : 'unreachable'}
    />
  )
}

/** GET /health/streaming display -- Kafka topic activity, Flink job
 * state, ksqlDB/Schema Registry reachability. See
 * apps/gateway/src/routes/health_streaming.rs for what's a real signal
 * here vs. a documented gap (no per-consumer-group lag). */
export function SystemHealthPanel() {
  const [health, setHealth] = useState<StreamingHealth | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const poll = () => {
      getStreamingHealth()
        .then((h) => {
          if (!cancelled) {
            setHealth(h)
            setError(null)
          }
        })
        .catch((err) => {
          if (!cancelled) setError(err instanceof Error ? err.message : 'unreachable')
        })
    }
    poll()
    const id = setInterval(poll, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  if (error) {
    return (
      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
          Streaming health
        </h3>
        <p className="text-sm text-red-400">Gateway unreachable: {error}</p>
      </div>
    )
  }

  if (!health) {
    return (
      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
          Streaming health
        </h3>
        <p className="text-sm text-text-muted">Loading…</p>
      </div>
    )
  }

  const runningJobs = health.flink.jobs?.jobs.filter((j) => j.state === 'RUNNING') ?? []

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
          Streaming health
        </h3>
        <Badge variant={health.status === 'ok' ? 'success' : 'outline'}>{health.status}</Badge>
      </div>

      <div className="space-y-1 text-xs">
        <div className="flex items-center gap-2">
          <Dot ok={health.kafka.reachable} /> Kafka
        </div>
        <div className="flex items-center gap-2">
          <Dot ok={health.schema_registry.reachable} /> Schema Registry
        </div>
        <div className="flex items-center gap-2">
          <Dot ok={health.ksqldb.reachable} /> ksqlDB
        </div>
        <div className="flex items-center gap-2">
          <Dot ok={health.flink.reachable} /> Flink ({runningJobs.length} job{runningJobs.length === 1 ? '' : 's'} running)
        </div>
      </div>

      {health.kafka.topics && (
        <div className="space-y-1">
          <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Topic activity</p>
          {health.kafka.topics.map((t) => (
            <div key={t.topic} className="flex items-center justify-between text-xs text-text-muted">
              <span className="truncate">{t.topic.replace('aether.', '')}</span>
              <span>{t.found ? t.message_count : '—'}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
