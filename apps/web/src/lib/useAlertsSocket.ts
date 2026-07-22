import { useEffect, useRef } from 'react'
import { alertsWebSocketUrl, type AlertMessage } from '@/lib/api'
import { useAlertStore } from '@/store/useAlertStore'

const RECONNECT_DELAYS_MS = [1000, 2000, 5000, 10000, 30000]

/**
 * Owns the GET /ws/alerts connection lifecycle: connect when a token is
 * present, push incoming alerts into useAlertStore, reconnect with
 * backoff on drop. Call this once (e.g. from AlertPanel) -- it's the
 * single source of truth for the connection, not something every
 * consumer of alert state should re-open.
 */
export function useAlertsSocket(): void {
  const token = useAlertStore((s) => s.token)
  const addAlert = useAlertStore((s) => s.addAlert)
  const setConnectionStatus = useAlertStore((s) => s.setConnectionStatus)

  const attemptRef = useRef(0)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const socketRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (!token) {
      setConnectionStatus('disconnected')
      return
    }

    let cancelled = false

    const connect = () => {
      if (cancelled) return
      setConnectionStatus('connecting')

      const ws = new WebSocket(alertsWebSocketUrl(token))
      socketRef.current = ws

      ws.onopen = () => {
        attemptRef.current = 0
        setConnectionStatus('connected')
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'connected') return // initial handshake ack, not an alert
          addAlert(data as AlertMessage)
        } catch (err) {
          console.error('failed to parse alert message', err)
        }
      }

      ws.onerror = () => {
        setConnectionStatus('error')
      }

      ws.onclose = () => {
        if (cancelled) return
        setConnectionStatus('disconnected')
        const delay = RECONNECT_DELAYS_MS[Math.min(attemptRef.current, RECONNECT_DELAYS_MS.length - 1)]
        attemptRef.current += 1
        timeoutRef.current = setTimeout(connect, delay)
      }
    }

    connect()

    return () => {
      cancelled = true
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
      socketRef.current?.close()
      socketRef.current = null
    }
  }, [token, addAlert, setConnectionStatus])
}
