// "Recommend with AI": asks the assistant to reason a recommendation from today's data (not a stored template), so
// it changes whenever the data changes. Shows the answer and what it rests on.
import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Row } from '../api'

export function Recommend({ kind, subject, context = '', label = 'Recommend with AI' }: { kind: 'kpi' | 'variance' | 'situation'; subject: string; context?: string; label?: string }) {
  const [state, setState] = useState<{ busy?: boolean; text?: string; error?: string; ev?: Row; unverified?: string[] }>({})
  const run = () => {
    setState({ busy: true })
    fetch('/api/recommend', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind, subject, context }) })
      .then(async (r) => { const j = await r.json(); if (!r.ok) throw new Error(j.detail ?? r.statusText); return j })
      .then((j) => setState({ text: j.text, ev: j.evidence, unverified: j.unverified_numbers }))
      .catch((e) => setState({ error: String(e.message ?? e) }))
  }
  const ev = state.ev as Row | undefined
  return (
    <div className="recommend">
      <div className="recommend-head">
        <button className="btn small" onClick={run} disabled={state.busy}>{state.busy ? 'Reasoning over today’s data…' : state.text ? 'Recommend again' : label}</button>
        <span className="muted" style={{ fontSize: 12 }}>Reasoned by the assistant from current data each time; not a fixed rule.</span>
      </div>
      {state.busy && <div className="skeleton"><span /><span /><span /></div>}
      {state.error && <div className="error">{state.error}</div>}
      {state.text && (
        <div className="recommend-body">
          <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{state.text}</ReactMarkdown></div>
          <div className="muted" style={{ fontSize: 12 }}>
            {ev ? `Data closed through ${String((ev.freshness as Row)?.closed_through)} · books ${String((ev.reconciliation as Row)?.status)} · ${ev.numbers_verified ? 'every number verified against the data' : 'some numbers unverified'}` : ''}
            {state.unverified?.length ? ` · unverified: ${state.unverified.join(', ')}` : ''}
          </div>
        </div>
      )}
    </div>
  )
}
