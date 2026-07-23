import { useEffect, useMemo, useState } from 'react'
import {
  listSnapshots,
  listPlans,
  listPlanActions,
  runArchitectCycle,
  type ProjectSnapshotSummary,
  type ProjectPlanSummary,
  type ProjectPlanAction,
} from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { PageShell } from './PageShell'

type SortKey = 'newest' | 'oldest'

const ACTION_LABELS: Record<ProjectPlanAction['action'], string> = {
  branch_created: 'branch created',
  committed: 'committed',
  pushed: 'pushed',
  pr_opened: 'PR opened',
  skipped: 'skipped',
  failed: 'failed',
}

export function ArchitectPage() {
  const [snapshots, setSnapshots] = useState<ProjectSnapshotSummary[]>([])
  const [plans, setPlans] = useState<ProjectPlanSummary[]>([])
  const [actions, setActions] = useState<ProjectPlanAction[]>([])
  const [token, setToken] = useState('')
  const [runError, setRunError] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const [query, setQuery] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('newest')
  const [loadError, setLoadError] = useState<string | null>(null)

  const refresh = () => {
    setLoadError(null)
    const onLoadError = (err: unknown) =>
      setLoadError(err instanceof Error ? err.message : 'failed to load architect data')

    listSnapshots(10).then(setSnapshots).catch((err) => {
      setSnapshots([])
      onLoadError(err)
    })
    listPlans(10).then(setPlans).catch((err) => {
      setPlans([])
      onLoadError(err)
    })
    listPlanActions(50).then(setActions).catch((err) => {
      setActions([])
      onLoadError(err)
    })
  }

  useEffect(refresh, [])

  const visibleActions = useMemo(() => {
    const q = query.trim().toLowerCase()
    const filtered = q
      ? actions.filter((a) =>
          [a.action, a.branch_name, a.commit_sha, a.pr_url].some((f) => (f ?? '').toLowerCase().includes(q)),
        )
      : actions
    const sorted = [...filtered]
    sorted.sort((a, b) =>
      sortKey === 'newest'
        ? new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
        : new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
    )
    return sorted
  }, [actions, query, sortKey])

  async function handleRun() {
    setRunError(null)
    if (!token) {
      setRunError('a bearer token is required -- POST /architect/run is JWT-gated, see app/auth.py')
      return
    }
    setRunning(true)
    try {
      await runArchitectCycle(token)
      refresh()
    } catch (err) {
      setRunError(err instanceof Error ? err.message : 'run failed')
    } finally {
      setRunning(false)
    }
  }

  const latestSnapshot = snapshots[0]
  const latestPlan = plans[0]

  return (
    <PageShell title="The Architect -- project digital twin, plan, and commit ledger">
      <p className="mb-4 max-w-2xl text-xs text-text-muted sm:text-sm">
        The <code className="rounded bg-surface-2 px-1">project_architect</code> agent introspects this project's
        real, live state (a "digital twin" snapshot), plans ranked next steps grounded in that snapshot, and can
        autonomously commit ONE self-owned file --{' '}
        <code className="rounded bg-surface-2 px-1">PROJECT_PLAN.md</code> -- to a branch and open a PR. It never
        merges; that always goes through the same human/CI-gated review every other change in this repo does. See
        ROADMAP.md "Phase 5b: the Architect".
      </p>

      {loadError && (
        <p className="mb-4 text-xs text-red-400 sm:text-sm" role="alert">
          Bad Gateway -- failed to load architect data: {loadError}
        </p>
      )}

      <div className="mb-6 flex flex-col gap-2 sm:flex-row sm:items-end">
        <div className="flex-1">
          <label htmlFor="architect-token" className="mb-1 block text-xs text-text-muted">
            bearer token
          </label>
          <Input
            id="architect-token"
            placeholder="JWT"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            className="w-full text-xs sm:text-sm"
          />
        </div>
        <Button size="sm" onClick={handleRun} disabled={running} className="text-xs sm:text-sm">
          {running ? 'Running…' : 'Run'}
        </Button>
      </div>
      {runError && (
        <p className="mb-4 text-xs text-red-400 sm:text-sm" role="alert">
          {runError}
        </p>
      )}

      <div className="mb-6 grid grid-cols-1 gap-3 sm:gap-4 lg:grid-cols-2">
        <div className="rounded-md border border-border bg-surface p-2 sm:p-4">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
            Latest digital twin snapshot
          </h3>
          {latestSnapshot ? (
            <>
              <p className="text-xs text-text sm:text-sm">{latestSnapshot.summary}</p>
              <p className="mt-1 text-xs text-text-muted">{new Date(latestSnapshot.created_at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</p>
            </>
          ) : (
            <p className="text-xs text-text-muted sm:text-sm">No snapshot taken yet.</p>
          )}
        </div>

        <div className="rounded-md border border-border bg-surface p-2 sm:p-4">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">Latest plan</h3>
          {latestPlan ? (
            <ol className="space-y-2">
              {latestPlan.items.map((item, i) => (
                <li key={i} className="text-xs sm:text-sm">
                  <div className="flex flex-wrap items-center gap-1 sm:gap-2">
                    <span className="font-medium text-text">
                      {i + 1}. {item.title}
                    </span>
                    <Badge variant="outline" className="text-xs">{item.category.replace('_', ' ')}</Badge>
                    {item.safe_to_autoimplement && <Badge variant="success" className="text-xs">auto</Badge>}
                  </div>
                  <p className="text-xs text-text-muted">{item.rationale}</p>
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-xs text-text-muted sm:text-sm">No plan generated yet.</p>
          )}
        </div>
      </div>

      <div>
        <div className="mb-2 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
            Commit ledger ({visibleActions.length}
            {visibleActions.length !== actions.length ? ` of ${actions.length}` : ''})
          </h3>
          <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:gap-2">
            <div className="flex-1 sm:flex-none">
              <label htmlFor="architect-search" className="sr-only">
                Filter the commit ledger by action, branch, commit, or PR URL
              </label>
              <Input
                id="architect-search"
                placeholder="Filter…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="h-8 w-full text-xs sm:w-auto"
              />
            </div>
            <div>
              <label htmlFor="architect-sort" className="sr-only">
                Sort commit ledger
              </label>
              <select
                id="architect-sort"
                value={sortKey}
                onChange={(e) => setSortKey(e.target.value as SortKey)}
                className="h-8 w-full rounded-md border border-border bg-surface px-2 text-xs text-text sm:w-auto"
              >
                <option value="newest">Newest</option>
                <option value="oldest">Oldest</option>
              </select>
            </div>
          </div>
        </div>
        <div className="max-h-[400px] space-y-2 overflow-y-auto" aria-live="polite">
          {visibleActions.map((a) => (
            <div key={a.id} className="rounded-md border border-border bg-surface p-2 text-xs sm:p-3">
              <div className="mb-1 flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                <Badge variant={a.action === 'failed' ? 'outline' : a.action === 'skipped' ? 'outline' : 'success'}>
                  {ACTION_LABELS[a.action]}
                </Badge>
                <span className="text-text-muted text-xs">{new Date(a.created_at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
              </div>
              <p className="text-text-muted truncate text-xs">
                {a.branch_name && <>b: {a.branch_name.split('/').pop()} · </>}
                {a.commit_sha && <>c: {a.commit_sha.slice(0, 8)} · </>}
                {a.pr_url && (
                  <a href={a.pr_url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
                    PR
                  </a>
                )}
                {!a.branch_name && !a.pr_url && a.detail?.reason ? String(a.detail.reason).slice(0, 40) : null}
              </p>
            </div>
          ))}
          {actions.length === 0 && <p className="text-xs text-text-muted sm:text-sm">No architect actions logged yet.</p>}
          {actions.length > 0 && visibleActions.length === 0 && (
            <p className="text-xs text-text-muted sm:text-sm">No actions match "{query}".</p>
          )}
        </div>
      </div>
    </PageShell>
  )
}
