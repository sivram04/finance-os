import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api, fmt, type Action, type AgentEvent, type Evidence, type UploadedDoc } from '../api'
import { Chip, useWorkspace } from './common'

// One assistant turn: the user's message (or uploaded document), then every event the agent streamed back.
interface Turn { id: number; text: string; events: AgentEvent[]; running: boolean; doc?: UploadedDoc; uploading?: string }

const STORE = 'fos.conversation'
const ACCEPT = '.pdf,.png,.jpg,.jpeg,.webp'

const SUGGESTIONS = [
  'What needs my attention right now?',
  'Why is usage revenue below budget this year?',
  'Review the AP inbox and recommend what to approve or reject.',
  'Which projects are at risk and why?',
]

const TOOL_LABEL: Record<string, string> = {
  get_attention_items: 'Checked everything flagged',
  get_kpis: 'Read KPIs',
  get_kpi_trend: 'Read KPI trend',
  get_metric_definition: 'Looked up a metric definition',
  get_pnl: 'Read the P&L',
  get_budget_vs_actual: 'Read budget vs. actual',
  get_variance_drivers: 'Read the transactions behind a variance',
  get_unit_economics: 'Read customer margins',
  get_revenue_movements: 'Read revenue movements',
  get_tech_spend: 'Read tech spend',
  get_gpu_capacity_and_forecast: 'Read GPU capacity and forecast',
  get_projects: 'Read project financials',
  get_contract_funding: 'Read contract funding',
  get_billing_status: 'Read billing status',
  get_ar_aging: 'Read AR aging',
  get_collections_queue: 'Read the collections queue',
  get_ar_exceptions: 'Read AR exceptions and disputes',
  get_ap_review_queue: 'Read the AP review queue',
  get_reconciliation_status: 'Checked reconciliations',
  get_uploaded_document: 'Read the uploaded document and its checks',
  propose_ap_document_decision: 'Prepared an AP decision for your approval',
  propose_reminder_decision: 'Prepared a reminder decision for your approval',
  propose_cash_application_fix: 'Prepared a cash-application fix for your approval',
}

const METHOD: Record<string, string> = {
  pdf_text: 'PDF text → AI', pdf_rules: 'PDF text → rules', ocr_image: 'Image → AI OCR', ocr_scanned_pdf: 'Scanned PDF → AI OCR',
}

function DocCard({ doc }: { doc: UploadedDoc }) {
  const f = doc.fields
  const n = doc.issues.length
  return (
    <div className="doc">
      <div className="doc-head">
        <span>📄 {doc.filename}</span>
        <span className={`chip ${n ? 'bad' : 'good'}`}>{n ? `${n} issue${n > 1 ? 's' : ''}` : 'passed checks'}</span>
      </div>
      <div className="doc-grid">
        <span>Vendor</span><span>{f.vendor_name ?? '—'}{doc.vendor_id ? '' : ' (unknown)'}</span>
        <span>Invoice</span><span>{f.vendor_invoice_number ?? '—'} · {f.invoice_date ?? '—'}</span>
        <span>PO</span><span>{f.po_number ?? '—'}</span>
        <span>Total</span><span>{fmt('total', f.total)} · {f.lines.length} line{f.lines.length === 1 ? '' : 's'}</span>
        <span>Read by</span><span>{METHOD[doc.method] ?? doc.method} · {doc.model}</span>
      </div>
      {doc.issues.map((i) => <div key={i.code} className="doc-issue"><b>{i.code.replace(/_/g, ' ')}</b> · {i.detail}</div>)}
    </div>
  )
}

function ProposalCard({ initial }: { initial: Action }) {
  const [action, setAction] = useState(initial)
  const [busy, setBusy] = useState(false)
  const { refresh } = useWorkspace()
  const decide = async (d: 'approve' | 'reject' | 'undo') => {
    setBusy(true)
    try { setAction((await api.decide(action.id, d)).action); refresh() } finally { setBusy(false) }
  }
  return (
    <div className="proposal">
      <div className="head"><span>Needs your approval · {action.kind.replace(/_/g, ' ')}</span><Chip value={action.status} /></div>
      <div className="preview">{action.preview}</div>
      <div className="actions">
        {action.status === 'pending' && <>
          <button className="btn small primary" disabled={busy} onClick={() => decide('approve')}>Approve</button>
          <button className="btn small" disabled={busy} onClick={() => decide('reject')}>Reject</button>
        </>}
        {action.status === 'approved' && <button className="btn small" disabled={busy} onClick={() => decide('undo')}>Undo</button>}
      </div>
    </div>
  )
}

function Steps({ events, running }: { events: AgentEvent[]; running: boolean }) {
  const steps: { tool: string; args: Record<string, unknown>; result?: Extract<AgentEvent, { type: 'tool_result' }> }[] = []
  for (const e of events) {
    if (e.type === 'step') steps.push({ tool: e.tool, args: e.args })
    if (e.type === 'tool_result') { const s = [...steps].reverse().find((x) => x.tool === e.tool && !x.result); if (s) s.result = e }
  }
  const thinking = running && !events.some((e) => e.type === 'answer')
  return (
    <div className="steps">
      {steps.map((s, i) => (
        <details className="step" key={i}>
          <summary>
            <span className="caret">▸</span>
            {s.result ? (s.result.error ? '⚠' : '✓') : <span className="spinner" />}
            <span>{TOOL_LABEL[s.tool] ?? s.tool}</span>
            {s.result?.rows != null && <span className="faint">· {s.result.rows} rows</span>}
          </summary>
          <div className="meta">
            {s.tool}({Object.keys(s.args).length ? JSON.stringify(s.args) : ''})
            {s.result?.source && `\n→ ${s.result.source}`}
            {s.result?.ms != null && ` · ${s.result.ms} ms`}
            {s.result?.error && `\n${s.result.error}`}
          </div>
        </details>
      ))}
      {thinking && <div className="step"><span className="spinner" /> {steps.length ? 'Working…' : 'Thinking…'}</div>}
    </div>
  )
}

// What the answer rests on: governed metrics and their versions, how fresh the data is, whether the books
// reconcile, which tools and filters were used.
function EvidenceBlock({ ev }: { ev: Evidence }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="evidence">
      <button className="evidence-head" onClick={() => setOpen(!open)}>
        <span>Evidence</span>
        <span className="muted">closed through {ev.freshness.closed_through}{ev.freshness.live_through ? ` · live ${ev.freshness.live_through}` : ''}</span>
        <span className={ev.reconciliation.failing_checks ? 'bad' : 'good'}>books {ev.reconciliation.status}</span>
        <span className={ev.numbers_verified ? 'good' : 'bad'}>{ev.numbers_verified ? 'numbers verified' : 'numbers unverified'}</span>
        <span className="muted">{open ? 'hide' : 'show'}</span>
      </button>
      {open && (
        <div className="evidence-body">
          {ev.metrics.length > 0 && <div><b>Metrics</b> {ev.metrics.map((m) => `${m.label} v${m.version} (from ${m.effective_from}, ${m.owner})`).join(' · ')}</div>}
          <div><b>Sources</b> {ev.sources.join(' · ') || 'none'}</div>
          {ev.filters.length > 0 && <div><b>Filters</b> {ev.filters.map((f) => `${f.tool}(${Object.entries(f.args).map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : String(v)}`).join(', ')})`).join(' · ')}</div>}
        </div>
      )}
    </div>
  )
}

function TurnView({ turn }: { turn: Turn }) {
  const answer = turn.events.find((e): e is Extract<AgentEvent, { type: 'answer' }> => e.type === 'answer')
  const done = turn.events.find((e): e is Extract<AgentEvent, { type: 'done' }> => e.type === 'done')
  return (
    <div className="turn">
      {turn.uploading && <div className="msg-user"><span className="spinner" /> Reading {turn.uploading}…</div>}
      {turn.doc ? <div className="msg-user doc-msg"><DocCard doc={turn.doc} /></div> : turn.text && <div className="msg-user">{turn.text}</div>}
      <Steps events={turn.events} running={turn.running} />
      {turn.events.filter((e) => e.type === 'proposal').map((e) => e.type === 'proposal' && <ProposalCard key={e.action.id} initial={e.action} />)}
      {turn.events.filter((e) => e.type === 'error').map((e, i) => e.type === 'error' && <div className="error" key={i}>{e.message}</div>)}
      {answer && <div className="answer"><ReactMarkdown remarkPlugins={[remarkGfm]}>{answer.text}</ReactMarkdown></div>}
      {answer && answer.unverified_numbers.length > 0 && (
        <div className="warning">Unverified: {answer.unverified_numbers.join(', ')} did not match any data the assistant read. Treat with care.</div>
      )}
      {answer?.evidence && <EvidenceBlock ev={answer.evidence} />}
      {done && <div className="usage">{done.steps} tool steps · {(done.prompt_tokens + done.completion_tokens).toLocaleString()} tokens</div>}
    </div>
  )
}

export function Assistant({ pending }: { pending: { text: string; n: number } | null }) {
  const [turns, setTurns] = useState<Turn[]>([])
  const [input, setInput] = useState('')
  const [conversation, setConversation] = useState<string | null>(null)
  const [history, setHistory] = useState<{ id: string; title: string }[] | null>(null)
  const [dragging, setDragging] = useState(false)
  const running = turns.some((t) => t.running || t.uploading)
  const thread = useRef<HTMLDivElement>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  useEffect(() => { thread.current?.scrollTo({ top: thread.current.scrollHeight, behavior: 'smooth' }) }, [turns])

  const load = async (id: string) => {
    try {
      const c = await api.conversation(id)
      setTurns(c.turns.map((t, i) => ({ id: i, text: t.text, events: t.events, running: false, doc: t.doc })))
      setConversation(id)
      localStorage.setItem(STORE, id)
    } catch {
      localStorage.removeItem(STORE)
    }
    setHistory(null)
  }

  // reopen the last conversation after a reload
  useEffect(() => { const id = localStorage.getItem(STORE); if (id) load(id) }, [])

  const ensureConversation = async () => {
    if (conversation) return conversation
    const cid = (await api.newConversation()).id
    setConversation(cid)
    localStorage.setItem(STORE, cid)
    return cid
  }

  const stream = async (id: number, cid: string, text: string) => {
    const push = (e: AgentEvent) => setTurns((t) => t.map((x) => (x.id === id ? { ...x, events: [...x.events, e] } : x)))
    try {
      await api.chat(cid, text, push)
    } catch (err) {
      push({ type: 'error', message: String(err) })
    } finally {
      setTurns((t) => t.map((x) => (x.id === id ? { ...x, running: false } : x)))
    }
  }

  const send = async (text: string) => {
    if (!text.trim() || running) return
    const cid = await ensureConversation()
    const id = Date.now()
    setTurns((t) => [...t, { id, text, events: [], running: true }])
    setInput('')
    await stream(id, cid, text)
  }

  const attach = async (file: File) => {
    if (running) return
    const cid = await ensureConversation()
    const id = Date.now()
    setTurns((t) => [...t, { id, text: '', events: [], running: false, uploading: file.name }])
    let doc: UploadedDoc
    try {
      doc = await api.upload(file)
    } catch (err) {
      setTurns((t) => t.map((x) => (x.id === id
        ? { ...x, uploading: undefined, text: file.name, events: [{ type: 'error', message: `Could not read the file: ${err}` }] }
        : x)))
      return
    }
    const note = input.trim()
    setInput('')
    const prompt = `I uploaded a vendor bill: ${doc.filename} (document id ${doc.id}). ${note || 'Review it and prepare a decision for me.'}`
    setTurns((t) => t.map((x) => (x.id === id ? { ...x, uploading: undefined, doc, text: prompt, running: true } : x)))
    await stream(id, cid, prompt)
  }

  // questions handed over from the workspace ("Ask about this")
  useEffect(() => { if (pending) send(pending.text) }, [pending?.n])  // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <aside
      className={`assistant ${dragging ? 'dragging' : ''}`}
      onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
      onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false) }}
      onDrop={(e) => { e.preventDefault(); setDragging(false); const f = e.dataTransfer.files[0]; if (f) attach(f) }}
    >
      <div className="assistant-head">
        <div className="title"><span className="dot" />Assistant</div>
        <div className="head-actions">
          <button className="btn small" disabled={running} onClick={async () => setHistory(history ? null : await api.conversations())}>History</button>
          <button className="btn small" disabled={running} onClick={() => { setTurns([]); setConversation(null); localStorage.removeItem(STORE) }}>New chat</button>
          {history && (
            <div className="menu">
              {history.length === 0
                ? <div className="muted" style={{ padding: 8 }}>No earlier chats.</div>
                : history.map((h) => <button key={h.id} className={h.id === conversation ? 'on' : ''} onClick={() => load(h.id)}>{h.title}</button>)}
            </div>
          )}
        </div>
      </div>
      <div className="thread" ref={thread}>
        {turns.length === 0 ? (
          <div className="empty">
            <h2>How can I help?</h2>
            <p>I read the warehouse with tools and show every step. Numbers come only from the data; anything that changes something waits for your approval. Drop a vendor bill (PDF, scan or photo) here and I'll read and check it.</p>
            {SUGGESTIONS.map((s) => <button key={s} className="suggestion" onClick={() => send(s)}>{s}</button>)}
          </div>
        ) : turns.map((t) => <TurnView key={t.id} turn={t} />)}
      </div>
      {dragging && <div className="dropzone">Drop a vendor bill to read and check it</div>}
      <div className="composer">
        <div className="box">
          <textarea
            value={input}
            placeholder="Ask about revenue, spend, projects, AR, AP… or attach a bill"
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input) } }}
          />
          <div className="row">
            <button className="btn small" title="Attach a vendor bill (PDF, scan or photo)" disabled={running} onClick={() => fileInput.current?.click()}>Attach</button>
            <input ref={fileInput} type="file" accept={ACCEPT} hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) attach(f); e.target.value = '' }} />
            <span className="hint">Enter to send</span>
            <button className="btn small primary" disabled={running || !input.trim()} onClick={() => send(input)}>Send</button>
          </div>
        </div>
      </div>
    </aside>
  )
}
