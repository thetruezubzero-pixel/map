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
      <p className="mb-4 max-w-2xl text-sm text-text-muted">
        Real, working backend: AES-256-GCM-encrypted weight snapshots in Postgres, content-addressed by a sha256
        hash. The spec's IPFS + blockchain attestation layer is a documented interface stub, not live infrastructure
        -- see streaming and ROADMAP.md for why (real wallet/key management and gas fees, not something to fake).
      </p>

      <div className="mb-6 flex flex-wrap items-end gap-2">
        <div>
          <label htmlFor="heirloom-user-id" className="mb-1 block text-xs text-text-muted">
            user_id
          </label>
          <Input
            id="heirloom-user-id"
            placeholder="user_id"
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            className="w-48"
          />
        </div>
        <div>
          <label htmlFor="heirloom-device-id" className="mb-1 block text-xs text-text-muted">
            device_id
          </label>
          <Input
            id="heirloom-device-id"
            placeholder="device_id"
            value={deviceId}
            onChange={(e) => setDeviceId(e.target.value)}
            className="w-40"
          />
        </div>
        <div>
          <label htmlFor="heirloom-agent-select" className="mb-1 block text-xs text-text-muted">
            agent
          </label>
          <select
            id="heirloom-agent-select"
            value={selectedAgentId}
            onChange={(e) => setSelectedAgentId(e.target.value)}
            className="h-9 rounded-md border border-border bg-surface px-2 text-sm text-text"
          >
            <option value="">select an agent…</option>
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.role} / {a.level} ({a.model})
              </option>
            ))}
          </select>
        </div>
        <Button size="sm" onClick={handleExport}>
          Export heirloom
        </Button>
      </div>
      {exportError && (
        <p className="mb-4 text-sm text-red-400" role="alert">
          {exportError}
        </p>
      )}
      {error && (
        <p className="mb-4 text-sm text-red-400" role="alert">
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
          <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
              Transfer log ({visibleHeirlooms.length}
              {visibleHeirlooms.length !== heirlooms.length ? ` of ${heirlooms.length}` : ''})
            </h3>
            <div className="flex items-end gap-2">
              <div>
                <label htmlFor="heirloom-search" className="sr-only">
                  Filter heirlooms by agent, device, backend, or hash
                </label>
                <Input
                  id="heirloom-search"
                  placeholder="Filter by agent, device, backend…"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  className="h-8 w-48 text-xs"
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
                  className="h-8 rounded-md border border-border bg-surface px-2 text-xs text-text"
                >
                  <option value="newest">Newest first</option>
                  <option value="oldest">Oldest first</option>
                  <option value="agent">By agent name</option>
                </select>
              </div>
            </div>
          </div>
          <div className="max-h-[400px] space-y-2 overflow-y-auto" aria-live="polite">
            {visibleHeirlooms.map((h) => (
              <div key={h.id} className="rounded-md border border-border bg-surface p-3 text-xs">
                <div className="mb-1 flex items-center justify-between">
                  <Link to={`/agents/${h.agent_id}`} className="font-medium text-accent hover:underline">
                    {h.agent_name}
                  </Link>
                  <Badge variant={h.verified ? 'success' : 'outline'}>{h.backend}</Badge>
                </div>
                <p className="text-text-muted">
                  device: {h.device_id} · hash: {h.content_hash.slice(0, 16)}… · {new Date(h.created_at).toLocaleString()}
                </p>
              </div>
            ))}
            {heirlooms.length === 0 && <p className="text-sm text-text-muted">No heirlooms exported yet.</p>}
            {heirlooms.length > 0 && visibleHeirlooms.length === 0 && (
              <p className="text-sm text-text-muted">No heirlooms match "{query}".</p>
            )}
          </div>
        </div>
      </div>
    </PageShell>
  )
}
