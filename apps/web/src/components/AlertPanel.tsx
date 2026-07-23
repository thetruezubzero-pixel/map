import { useEffect, useMemo, useState } from 'react'
import {
  ALERT_SEVERITIES,
  SUBSCRIPTION_TYPES,
  createSubscription,
  deleteSubscription,
  listSubscriptions,
  type AlertSeverity,
  type SubscriptionType,
} from '@/lib/api'
import { useAlertStore, type ConnectionStatus } from '@/store/useAlertStore'
import { useAlertsSocket } from '@/lib/useAlertsSocket'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'

const SEVERITY_VARIANT: Record<AlertSeverity, 'default' | 'outline' | 'success'> = {
  INFO: 'outline',
  WARNING: 'default',
  CRITICAL: 'success', // accent-2 reads as the loudest of the three available badge colors
}

const STATUS_LABEL: Record<ConnectionStatus, string> = {
  disconnected: 'Not connected',
  connecting: 'Connecting…',
  connected: 'Live',
  error: 'Connection error',
}

const STATUS_DOT: Record<ConnectionStatus, string> = {
  disconnected: 'bg-text-muted',
  connecting: 'bg-accent animate-pulse',
  connected: 'bg-accent-2',
  error: 'bg-red-500',
}

/** Real-time alert panel + subscription management ("what's happening
 * now" feed) -- Phase 4. See the comment above the subscriptions
 * section of lib/api.ts for why a raw JWT paste is the auth flow here:
 * there is no login/signup system anywhere in this app. */
export function AlertPanel() {
  const token = useAlertStore((s) => s.token)
  const setToken = useAlertStore((s) => s.setToken)
  const connectionStatus = useAlertStore((s) => s.connectionStatus)
  const alerts = useAlertStore((s) => s.alerts)
  const unreadCount = useAlertStore((s) => s.unreadCount)
  const markAllRead = useAlertStore((s) => s.markAllRead)
  const severityFilter = useAlertStore((s) => s.severityFilter)
  const setSeverityFilter = useAlertStore((s) => s.setSeverityFilter)
  const sourceFilter = useAlertStore((s) => s.sourceFilter)
  const setSourceFilter = useAlertStore((s) => s.setSourceFilter)
  const subscriptions = useAlertStore((s) => s.subscriptions)
  const setSubscriptions = useAlertStore((s) => s.setSubscriptions)
  const upsertSubscription = useAlertStore((s) => s.upsertSubscription)
  const removeSubscription = useAlertStore((s) => s.removeSubscription)

  useAlertsSocket()

  const [tokenInput, setTokenInput] = useState('')
  const [newSubType, setNewSubType] = useState<SubscriptionType>('keyword')
  const [newSubValue, setNewSubValue] = useState('')
  const [subError, setSubError] = useState<string | null>(null)

  useEffect(() => {
    if (!token) return
    listSubscriptions(token)
      .then(setSubscriptions)
      .catch((err) => console.error('failed to load subscriptions', err))
  }, [token, setSubscriptions])

  const availableSources = useMemo(
    () => Array.from(new Set(alerts.map((a) => a.source_topic))).sort(),
    [alerts],
  )

  const filteredAlerts = useMemo(
    () =>
      alerts.filter(
        (a) =>
          (!severityFilter || a.severity === severityFilter) &&
          (!sourceFilter || a.source_topic === sourceFilter),
      ),
    [alerts, severityFilter, sourceFilter],
  )

  if (!token) {
    return (
      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
          Alerts
        </h3>
        <p className="mb-2 text-xs text-text-muted sm:text-sm">
          No login flow exists yet -- paste a pre-issued JWT (signed with the gateway's JWT_SECRET) to
          connect to real-time alerts.
        </p>
        <div className="flex flex-col gap-1 sm:flex-row sm:gap-2">
          <Input
            type="password"
            placeholder="JWT"
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            className="text-xs sm:text-sm"
          />
          <Button size="sm" onClick={() => setToken(tokenInput.trim() || null)} disabled={!tokenInput.trim()} className="text-xs sm:text-sm">
            Connect
          </Button>
        </div>
      </div>
    )
  }

  async function handleCreateSubscription() {
    setSubError(null)
    const criteria =
      newSubType === 'keyword'
        ? { keywords: newSubValue.split(',').map((s) => s.trim()).filter(Boolean) }
        : newSubType === 'entity'
          ? { entity_name: newSubValue.trim() }
          : newSubType === 'geofence'
            ? { lat: 0, lon: 0, radius_km: 10 } // placeholder -- see criteria caveat below
            : { keywords: newSubValue.split(',').map((s) => s.trim()).filter(Boolean) }

    if (!token) return
    try {
      const sub = await createSubscription(token, { subscription_type: newSubType, criteria })
      upsertSubscription(sub)
      setNewSubValue('')
    } catch (err) {
      setSubError(err instanceof Error ? err.message : 'failed to create subscription')
    }
  }

  async function handleDelete(id: string) {
    if (!token) return
    try {
      await deleteSubscription(token, id)
      removeSubscription(id)
    } catch (err) {
      console.error('failed to delete subscription', err)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-muted">Alerts</h3>
        <div className="flex items-center gap-2">
          {unreadCount > 0 && (
            <button
              type="button"
              onClick={markAllRead}
              className="rounded-full bg-accent px-2 py-0.5 text-xs font-medium text-white"
              title="Mark all read"
            >
              {unreadCount}
            </button>
          )}
          <span className="flex items-center gap-1.5 text-xs text-text-muted">
            <span className={`h-2 w-2 rounded-full ${STATUS_DOT[connectionStatus]}`} />
            {STATUS_LABEL[connectionStatus]}
          </span>
        </div>
      </div>

      <div className="space-y-2 rounded-md border border-border bg-surface p-2 sm:p-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">New subscription</p>
        <div className="flex flex-wrap gap-1">
          {SUBSCRIPTION_TYPES.map((t) => (
            <Button
              key={t}
              size="sm"
              variant={newSubType === t ? 'default' : 'outline'}
              onClick={() => setNewSubType(t)}
              className="flex-1 px-1 text-xs"
            >
              {t}
            </Button>
          ))}
        </div>
        {newSubType === 'geofence' ? (
          <p className="text-xs text-text-muted">
            Geofence subscriptions don't match any alerts yet -- the current Flink CEP detections
            (filing clusters, volume spikes, news correlation) carry no coordinates. Creating one is
            harmless but it will stay silent; see streaming/README.md.
          </p>
        ) : (
          <Input
            placeholder={newSubType === 'entity' ? 'Company name, e.g. Acme Corp' : 'Keywords, comma-separated'}
            value={newSubValue}
            onChange={(e) => setNewSubValue(e.target.value)}
          />
        )}
        <Button
          size="sm"
          className="w-full"
          onClick={handleCreateSubscription}
          disabled={newSubType === 'geofence' || !newSubValue.trim()}
        >
          {newSubType === 'geofence' ? 'Not available yet' : 'Create'}
        </Button>
        {subError && <p className="text-xs text-red-400">{subError}</p>}
      </div>

      {subscriptions.length > 0 && (
        <div className="space-y-1.5">
          {subscriptions.map((sub) => (
            <div
              key={sub.id}
              className="flex items-center justify-between rounded-md border border-border bg-surface px-2 py-1.5 text-xs"
            >
              <span className="truncate text-text-muted">
                <Badge variant="outline" className="mr-1.5">
                  {sub.subscription_type}
                </Badge>
                {JSON.stringify(sub.criteria)}
              </span>
              <button
                type="button"
                onClick={() => handleDelete(sub.id)}
                className="ml-2 shrink-0 text-text-muted hover:text-red-400"
                aria-label="Delete subscription"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-1">
        {ALERT_SEVERITIES.map((sev) => (
          <Button
            key={sev}
            size="sm"
            variant={severityFilter === sev ? 'default' : 'outline'}
            onClick={() => setSeverityFilter(severityFilter === sev ? null : sev)}
            className="px-2 text-xs"
          >
            {sev}
          </Button>
        ))}
        {availableSources.length > 0 && (
          <select
            aria-label="Filter alerts by source"
            value={sourceFilter ?? ''}
            onChange={(e) => setSourceFilter(e.target.value || null)}
            className="h-8 rounded-md border border-border bg-surface px-2 text-xs text-text"
          >
            <option value="">all sources</option>
            {availableSources.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        )}
      </div>

      <div className="space-y-1.5">
        {filteredAlerts.length === 0 && (
          <p className="text-xs text-text-muted sm:text-sm">
            {alerts.length === 0 ? 'No alerts yet -- this feed updates live.' : 'No alerts match the current filters.'}
          </p>
        )}
        {filteredAlerts.map((alert) => (
          <div key={alert.id} className="rounded-md border border-border bg-surface p-2 text-xs sm:p-2.5 sm:text-sm">
            <div className="mb-1 flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
              <Badge variant={SEVERITY_VARIANT[alert.severity]} className="w-fit text-xs">{alert.severity}</Badge>
              <span className="text-xs text-text-muted">
                {new Date(alert.created_at).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}
              </span>
            </div>
            <p className="font-medium text-text line-clamp-1">{alert.title}</p>
            <p className="text-xs text-text-muted line-clamp-2">{alert.description}</p>
          </div>
        ))}
      </div>

      <Button variant="ghost" size="sm" className="w-full" onClick={() => setToken(null)}>
        Disconnect
      </Button>
    </div>
  )
}
