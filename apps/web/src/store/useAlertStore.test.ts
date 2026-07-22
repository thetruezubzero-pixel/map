import { beforeEach, describe, expect, it } from 'vitest'
import { useAlertStore } from './useAlertStore'
import type { AlertMessage, Subscription } from '@/lib/api'

const alert = (overrides: Partial<AlertMessage> = {}): AlertMessage => ({
  id: 'a1',
  subscription_id: 's1',
  user_id: 'u1',
  severity: 'WARNING',
  title: 'Rapid filing activity: Acme Corp',
  description: '2 filings within 1 hour',
  source_topic: 'aether.business_registrations',
  source_event_id: null,
  entity_id: null,
  lat: null,
  lon: null,
  channels: ['in_app'],
  created_at: new Date().toISOString(),
  ...overrides,
})

const subscription = (overrides: Partial<Subscription> = {}): Subscription => ({
  id: 'sub1',
  user_id: 'u1',
  subscription_type: 'keyword',
  criteria: { keywords: ['acme'] },
  min_severity: 'INFO',
  channels: ['in_app'],
  webhook_url: null,
  is_active: true,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  ...overrides,
})

describe('useAlertStore', () => {
  beforeEach(() => {
    useAlertStore.getState().clearAlerts()
    useAlertStore.getState().setToken(null)
    useAlertStore.getState().setSubscriptions([])
    useAlertStore.getState().setSeverityFilter(null)
    useAlertStore.getState().setSourceFilter(null)
  })

  it('addAlert prepends and increments unreadCount', () => {
    useAlertStore.getState().addAlert(alert({ id: 'a1' }))
    useAlertStore.getState().addAlert(alert({ id: 'a2' }))

    const state = useAlertStore.getState()
    expect(state.alerts.map((a) => a.id)).toEqual(['a2', 'a1'])
    expect(state.unreadCount).toBe(2)
  })

  it('markAllRead resets unreadCount without clearing alerts', () => {
    useAlertStore.getState().addAlert(alert())
    useAlertStore.getState().markAllRead()

    const state = useAlertStore.getState()
    expect(state.unreadCount).toBe(0)
    expect(state.alerts).toHaveLength(1)
  })

  it('upsertSubscription replaces an existing subscription by id', () => {
    useAlertStore.getState().upsertSubscription(subscription({ id: 's1', is_active: true }))
    useAlertStore.getState().upsertSubscription(subscription({ id: 's1', is_active: false }))

    const state = useAlertStore.getState()
    expect(state.subscriptions).toHaveLength(1)
    expect(state.subscriptions[0].is_active).toBe(false)
  })

  it('removeSubscription drops only the targeted subscription', () => {
    useAlertStore.getState().upsertSubscription(subscription({ id: 's1' }))
    useAlertStore.getState().upsertSubscription(subscription({ id: 's2' }))
    useAlertStore.getState().removeSubscription('s1')

    expect(useAlertStore.getState().subscriptions.map((s) => s.id)).toEqual(['s2'])
  })
})
