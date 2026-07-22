import { useState } from 'react'
import { sendChatMessage, type ChatGroundingRecord, type ChatMessage } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { PageShell } from './PageShell'

interface DisplayMessage extends ChatMessage {
  grounding?: ChatGroundingRecord[]
}

export function ChatPage() {
  const [messages, setMessages] = useState<DisplayMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSend() {
    const content = input.trim()
    if (!content || sending) return

    setError(null)
    const nextMessages: DisplayMessage[] = [...messages, { role: 'user', content }]
    setMessages(nextMessages)
    setInput('')
    setSending(true)

    try {
      // Server is stateless -- resend the whole history each turn (see
      // app/routers/chat.py), stripping the grounding field the server
      // doesn't expect back.
      const reply = await sendChatMessage(nextMessages.map(({ role, content }) => ({ role, content })))
      setMessages((prev) => [...prev, { role: 'assistant', content: reply.reply, grounding: reply.grounding }])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'failed to send message')
    } finally {
      setSending(false)
    }
  }

  return (
    <PageShell title="Chat -- ask the platform directly">
      <p className="mb-4 max-w-2xl text-sm text-text-muted">
        A quick, plain-English way to ask about businesses, locations, and public filings -- grounded in a live
        lookup against this platform's own database when a message names something specific. This is a best-effort
        answer, not a substitute for the <code className="rounded bg-surface-2 px-1">Research</code> panel's deeper,
        multi-source, human-reviewed pipeline.
      </p>

      {error && (
        <p className="mb-4 text-sm text-red-400" role="alert">
          {error}
        </p>
      )}

      <div className="mb-4 max-h-[55vh] space-y-3 overflow-y-auto" aria-live="polite">
        {messages.map((m, i) => (
          <div
            key={i}
            className={`rounded-md border border-border p-3 text-sm ${
              m.role === 'user' ? 'ml-8 bg-accent/10' : 'mr-8 bg-surface'
            }`}
          >
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-muted">
              {m.role === 'user' ? 'You' : 'Assistant'}
            </p>
            <p className="whitespace-pre-wrap text-text">{m.content}</p>
            {m.grounding && m.grounding.length > 0 && (
              <ul className="mt-2 space-y-1 border-t border-border pt-2">
                {m.grounding.map((g) => (
                  <li key={g.id} className="text-xs text-text-muted">
                    {g.name} · {g.entity_type} · {g.source}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
        {messages.length === 0 && (
          <p className="text-sm text-text-muted">Ask something, e.g. "What businesses are near Main St?"</p>
        )}
      </div>

      <div className="flex items-end gap-2">
        <div className="flex-1">
          <label htmlFor="chat-input" className="sr-only">
            Message
          </label>
          <Input
            id="chat-input"
            placeholder="Ask about a business, location, or filing…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleSend()
              }
            }}
          />
        </div>
        <Button size="sm" onClick={handleSend} disabled={sending || !input.trim()}>
          {sending ? 'Sending…' : 'Send'}
        </Button>
      </div>
    </PageShell>
  )
}
