import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { AlertMessage, AlertSeverity, Subscription } from '@/lib/api'

export type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error'

interface AlertState {
  /** Ops-issued JWT -- see the comment above the subscriptions/alerts
   * section of lib/api.ts. Persisted to localStorage so a refresh
   * doesn't drop the connection. */
  token: string | null
  setToken: (token: string | null) => void

  connectionStatus: ConnectionStatus
  setConnectionStatus: (status: ConnectionStatus) => void

  alerts: AlertMessage[]
  addAlert: (alert: AlertMessage) => void
  clearAlerts: () => void

  unreadCount: number
  markAllRead: () => void

  severityFilter: AlertSeverity | null
  setSeverityFilter: (severity: AlertSeverity | null) => void
  sourceFilter: string | null
  setSourceFilter: (source: string | null) => void

  subscriptions: Subscription[]
  setSubscriptions: (subs: Subscription[]) => void
  upsertSubscription: (sub: Subscription) => void
  removeSubscription: (id: string) => void
}

const MAX_ALERTS = 200

export const useAlertStore = create<AlertState>()(
  persist(
    (set) => ({
      token: null,
      setToken: (token) => set({ token }),

      connectionStatus: 'disconnected',
      setConnectionStatus: (connectionStatus) => set({ connectionStatus }),

      alerts: [],
      addAlert: (alert) =>
        set((s) => ({
          alerts: [alert, ...s.alerts].slice(0, MAX_ALERTS),
          unreadCount: s.unreadCount + 1,
        })),
      clearAlerts: () => set({ alerts: [], unreadCount: 0 }),

      unreadCount: 0,
      markAllRead: () => set({ unreadCount: 0 }),

      severityFilter: null,
      setSeverityFilter: (severityFilter) => set({ severityFilter }),
      sourceFilter: null,
      setSourceFilter: (sourceFilter) => set({ sourceFilter }),

      subscriptions: [],
      setSubscriptions: (subscriptions) => set({ subscriptions }),
      upsertSubscription: (sub) =>
        set((s) => ({
          subscriptions: [sub, ...s.subscriptions.filter((existing) => existing.id !== sub.id)],
        })),
      removeSubscription: (id) =>
        set((s) => ({ subscriptions: s.subscriptions.filter((sub) => sub.id !== id) })),
    }),
    {
      name: 'aether-alert-store',
      // Only the token is worth persisting -- alerts/subscriptions are
      // re-fetched/re-streamed fresh on each session rather than risking
      // stale cached state.
      partialize: (s) => ({ token: s.token }),
    },
  ),
)
