import { useEffect, useRef, useState } from 'react'
import { Send, Loader2, Sparkles } from 'lucide-react'
import { getResearchJob, sendChatMessage, type ChatMessage } from '@/lib/api'
import { applyMapActions, plotLocatedRecords } from '@/lib/mapActions'

// The single conversational surface: the user types plain English, the
// agent answers AND drives the map (search, move, filter, toggle layers)
// via the actions it returns. This is the "you talk, the agent operates
// the machine" interaction -- the map is the stage, this is the control.
//
// Stateless backend: we resend the running message history each turn (the
// /chat endpoint keeps no server-side session), capped so it never grows
// unbounded. Map actions are applied even when OPENROUTER_API_KEY is unset,
// because the backend parses them deterministically (app/agents/map_intent.py).

const MAX_HISTORY = 20 // messages resent for context (endpoint caps at 40)
const RESEARCH_POLL_MS = 2500
const RESEARCH_TIMEOUT_MS = 120_000 // the swarm can run ~2 min worst case

export function AgentCommandBar() {
  const [history, setHistory] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [researching, setResearching] = useState(false)
  const [reply, setReply] = useState<string | null>(null)
  const [notes, setNotes] = useState<string[]>([])
  const inputRef = useRef<HTMLInputElement>(null)
  // Cancels an in-flight research poll if the component unmounts.
  const cancelledRef = useRef(false)
  useEffect(() => () => { cancelledRef.current = true }, [])

  // Poll a launched research job to a terminal state, then plot its located
  // records on the map and surface the summary (Combine B). Human-review is
  // unchanged -- a finished job sits in `awaiting_review`; we only display.
  async function followResearchJob(jobId: string) {
    setResearching(true)
    const deadline = Date.now() + RESEARCH_TIMEOUT_MS
    try {
      while (!cancelledRef.current && Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, RESEARCH_POLL_MS))
        if (cancelledRef.current) return
        let job
        try {
          job = await getResearchJob(jobId)
        } catch {
          continue // transient; keep polling until the deadline
        }
        if (job.status === 'failed') {
          setReply('The research job failed. You can try again.')
          return
        }
        // awaiting_review / completed both carry a finished report.
        if (job.result && (job.status === 'awaiting_review' || job.status === 'completed')) {
          const records = job.result.records ?? []
          const plotted = plotLocatedRecords(records, `research:${jobId}`)
          const tail =
            plotted > 0
              ? ` Plotted ${plotted} located record${plotted === 1 ? '' : 's'} on the map.`
              : records.length > 0
                ? ` Found ${records.length} record${records.length === 1 ? '' : 's'} (none had coordinates to map).`
                : ''
          setReply((job.result.summary || 'Research complete.') + tail)
          return
        }
      }
      if (!cancelledRef.current) setReply('The research job is still running — check the Research panel for the full report.')
    } finally {
      if (!cancelledRef.current) setResearching(false)
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    const text = input.trim()
    if (!text || busy) return

    const userMsg: ChatMessage = { role: 'user', content: text }
    const nextHistory: ChatMessage[] = [...history, userMsg].slice(-MAX_HISTORY)
    setHistory(nextHistory)
    setInput('')
    setBusy(true)
    setNotes([])

    try {
      const res = await sendChatMessage(nextHistory)
      setReply(res.reply)
      const assistantMsg: ChatMessage = { role: 'assistant', content: res.reply }
      setHistory((h) => [...h, assistantMsg].slice(-MAX_HISTORY))

      const outcome = res.actions?.length ? await applyMapActions(res.actions) : null
      if (outcome?.notes.length) setNotes(outcome.notes)

      // Combine A: if nothing else populated the map (no search ran, no
      // research launched), plot the entities the agent grounded its answer
      // on -- the ones it's actually talking about.
      const didSearch = (outcome?.resultCount ?? null) !== null
      if (!didSearch && !outcome?.researchJobId && res.grounding?.length) {
        plotLocatedRecords(res.grounding, 'grounding')
      }

      // Combine B: follow a launched research job to completion.
      if (outcome?.researchJobId) {
        await followResearchJob(outcome.researchJobId)
      }
    } catch (err) {
      setReply('I couldn’t reach the assistant just now. Please try again.')
      console.error('agent command failed', err)
    } finally {
      setBusy(false)
      inputRef.current?.focus()
    }
  }

  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-0 z-[1000] flex justify-center p-3 sm:p-4">
      <div className="pointer-events-auto w-full max-w-2xl">
        {(reply || notes.length > 0) && (
          <div
            className="mb-2 rounded-lg border border-border bg-background/95 px-3 py-2 text-sm text-text shadow-lg backdrop-blur"
            role="status"
            aria-live="polite"
          >
            {reply && <p className="whitespace-pre-wrap">{reply}</p>}
            {researching && (
              <p className="mt-1 flex items-center gap-1.5 text-xs text-text-muted">
                <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
                Running the multi-source research swarm…
              </p>
            )}
            {notes.map((n, i) => (
              <p key={i} className="mt-1 text-xs text-text-muted">
                {n}
              </p>
            ))}
          </div>
        )}
        <form
          onSubmit={submit}
          className="flex items-center gap-2 rounded-full border border-border bg-background/95 px-3 py-1.5 shadow-lg backdrop-blur"
        >
          <Sparkles className="h-4 w-4 shrink-0 text-accent" aria-hidden="true" />
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={busy}
            aria-label="Ask the agent to search or change the map"
            placeholder="Ask the map… e.g. “show businesses near Austin”"
            className="min-w-0 flex-1 bg-transparent py-1 text-sm text-text outline-none placeholder:text-text-muted disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={busy || !input.trim()}
            aria-label="Send"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent text-white transition-opacity disabled:opacity-40"
          >
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <Send className="h-4 w-4" aria-hidden="true" />
            )}
          </button>
        </form>
      </div>
    </div>
  )
}
