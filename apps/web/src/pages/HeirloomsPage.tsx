import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { exportHeirloom, listAgents, listHeirlooms, type AgentSummary, type Heirloom } from '@/lib/api'
import { AgentGraph } from '@/components/AgentGraph'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { PageShell } from './PageShell'

type SortKey = 'newest' | 'oldest' | 'agent'

export function HeirloomsPage() {
  const [userId, setUserId] = useState('')
  const [deviceId, setDeviceId] = useState('device-1')
  const [agents, setAgents] = useState<AgentSummary[]>([])
  const [heirlooms, setHeirlooms] = useState<Heirloom[]>([])
  const [selectedAgentId, setSelectedAgentId] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('newest')

  const visibleHeirlooms = useMemo(() => {
    const q = query.trim().toLowerCase()
    const filtered = q
      ? heirlooms.filter((h) =>
          [h.agent_name, h.device_id, h.backend, h.content_hash].some((field) => field.toLowerCase().includes(q)),
        )
      : heirlooms
    const sorted = [...filtered]
    if (sortKey === 'newest') {
      sorted.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    } else if (sortKey === 'oldest') {
      sorted.sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
    } else {
      sorted.sort((a, b) => a.agent_name.localeCompare(b.agent_name))
    }
    return sorted
  }, [heirlooms, query, sortKey])

  const refresh = () => {
    listAgents(userId || undefined)
      .then(setAgents)
      .catch((err) => setError(err instanceof Error ? err.message : 'failed to load agents'))
    listHeirlooms(userId || undefined)
      .then((res) => setHeirlooms(res.heirlooms))
      .catch((err) => setError(err instanceof Error ? err.message : 'failed to load heirlooms'))
  }

  useEffect(refresh, [userId])

  async function handleExport() {
    setExportError(null)
    if (!selectedAgentId || !userId || !deviceId) {
      setExportError('user_id, device_id, and a selected agent are all required')
      return
    }
    try {
      await exportHeirloom(selectedAgentId, userId, deviceId)
      refresh()
    } catch (err) {
      setExportError(err instanceof Error ? err.message : 'export failed')
    }
  }

  return (
    <PageShell title="Heirlooms -- cross-device knowledge persistence">
      <p className="mb-4 max-w-2xl text-xs text-text-muted sm:text-sm">
        Real, working backend: AES-256-GCM-encrypted weight snapshots in Postgres. The spec's IPFS + blockchain layer is a documented stub -- see ROADMAP.md.
      </p>

      <div className="mb-6 flex flex-col gap-2 sm:flex-row sm:items-end sm:flex-wrap">
        <div className="flex-1 sm:flex-none">
          <label htmlFor="heirloom-user-id" className="mb-1 block text-xs text-text-muted">
            user_id
          </label>
          <Input
            id="heirloom-user-id"
            placeholder="user_id"
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            className="w-full text-xs sm:w-auto sm:text-sm"
          />
        </div>
        <div className="flex-1 sm:flex-none">
          <label htmlFor="heirloom-device-id" className="mb-1 block text-xs text-text-muted">
            device_id
          </label>
          <Input
            id="heirloom-device-id"
            placeholder="device_id"
            value={deviceId}
            onChange={(e) => setDeviceId(e.target.value)}
            className="w-full text-xs sm:w-auto sm:text-sm"
          />
        </div>
        <div className="flex-1 sm:flex-none">
          <label htmlFor="heirloom-agent-select" className="mb-1 block text-xs text-text-muted">
            agent
          </label>
          <select
            id="heirloom-agent-select"
            value={selectedAgentId}
            onChange={(e) => setSelectedAgentId(e.target.value)}
            className="h-9 w-full rounded-md border border-border bg-surface px-2 text-xs text-text sm:w-auto sm:text-sm"
          >
            <option value="">select…</option>
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.role.replace('_', ' ')} ({a.level})
              </option>
            ))}
          </select>
        </div>
        <Button size="sm" onClick={handleExport} className="text-xs sm:text-sm">
          Export
        </Button>
      </div>
      {exportError && (
        <p className="mb-4 text-xs text-red-400 sm:text-sm" role="alert">
          {exportError}
        </p>
      )}
      {error && (
        <p className="mb-4 text-xs text-red-400 sm:text-sm" role="alert">
          {error}
        </p>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
            Family tree (edges = parent_agent_id lineage)
          </h3>
          <AgentGraph agents={agents} />
        </div>

        <div>
          <div className="mb-2 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
              Transfer log ({visibleHeirlooms.length}
              {visibleHeirlooms.length !== heirlooms.length ? ` of ${heirlooms.length}` : ''})
            </h3>
            <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:gap-2">
              <div className="flex-1 sm:flex-none">
                <label htmlFor="heirloom-search" className="sr-only">
                  Filter heirlooms
                </label>
                <Input
                  id="heirloom-search"
                  placeholder="Filter…"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  className="h-8 w-full text-xs sm:w-auto"
                />
              </div>
              <div>
                <label htmlFor="heirloom-sort" className="sr-only">
                  Sort heirlooms
                </label>
                <select
                  id="heirloom-sort"
                  value={sortKey}
                  onChange={(e) => setSortKey(e.target.value as SortKey)}
                  className="h-8 w-full rounded-md border border-border bg-surface px-2 text-xs text-text sm:w-auto"
                >
                  <option value="newest">Newest</option>
                  <option value="oldest">Oldest</option>
                  <option value="agent">By agent</option>
                </select>
              </div>
            </div>
          </div>
          <div className="max-h-[400px] space-y-1.5 overflow-y-auto sm:space-y-2" aria-live="polite">
            {visibleHeirlooms.map((h) => (
              <div key={h.id} className="rounded-md border border-border bg-surface p-2 text-xs sm:p-3">
                <div className="mb-1 flex items-center justify-between gap-2">
                  <Link to={`/agents/${h.agent_id}`} className="font-medium text-accent hover:underline truncate">
                    {h.agent_name}
                  </Link>
                  <Badge variant={h.verified ? 'success' : 'outline'} className="text-xs shrink-0">{h.backend}</Badge>
                </div>
                <p className="text-text-muted truncate text-xs">
                  d: {h.device_id.slice(0, 10)} · h: {h.content_hash.slice(0, 8)}… · {new Date(h.created_at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                </p>
              </div>
            ))}
            {heirlooms.length === 0 && <p className="text-xs text-text-muted sm:text-sm">No heirlooms exported yet.</p>}
            {heirlooms.length > 0 && visibleHeirlooms.length === 0 && (
              <p className="text-xs text-text-muted sm:text-sm">No heirlooms match "{query}".</p>
            )}
          </div>
        </div>
      </div>
    </PageShell>
  )
}
