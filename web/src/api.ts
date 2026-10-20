import { display, humanizeResult, isCode } from './components/sources'
// Typed client for the Finance OS API (src/finance_os/app/api.py).

export type Row = Record<string, unknown>

export interface ToolResult {
  source: string
  row_count: number
  rows: Row[]
  note?: string
  [extra: string]: unknown
}

export interface Action {
  id: string
  kind: string
  target_id: string
  preview: string
  status: 'pending' | 'approved' | 'rejected' | 'reverted'
  created_at: string
  decided_at: string | null
}

export interface UploadedDoc {
  id: string
  filename: string
  method: 'pdf_text' | 'pdf_rules' | 'ocr_image' | 'ocr_scanned_pdf'
  model: string
  vendor_id: string | null
  route: 'auto_approve' | 'needs_review'
  fields: {
    vendor_name: string | null; vendor_invoice_number: string | null; invoice_date: string | null
    po_number: string | null; total: number | null
    lines: { description: string; quantity: number | null; amount: number | null }[]
  }
  issues: { code: string; detail: string }[]
}

export interface Evidence {
  drill?: { label: string; args: Record<string, string> }[]
  sources: string[]
  filters: { tool: string; args: Record<string, unknown> }[]
  metrics: { metric: string; label: string; version: number; effective_from: string; owner: string }[]
  freshness: { closed_through: string; live_through?: string | null }
  reconciliation: { failing_checks: number; status: string }
  numbers_verified: boolean
}

export type AgentEvent =
  | { type: 'step'; tool: string; args: Record<string, unknown> }
  | { type: 'tool_result'; tool: string; ms: number; source?: string; rows?: number; error?: string | null }
  | { type: 'proposal'; action: Action }
  | { type: 'validator_retry'; reason: string; unverified?: string[] }
  | { type: 'answer'; text: string; unverified_numbers: string[]; evidence?: Evidence }
  | { type: 'error'; message: string }
  | { type: 'done'; steps: number; prompt_tokens: number; completion_tokens: number; stopped: string }

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return humanizeResult(await res.json()) as T  // codes inside sentences read as words everywhere
}

export const api = {
  health: () => fetch('/api/health').then(json<{ ok: boolean; data_through: string; live_through?: string }>),
  data: (tool: string, args: Record<string, unknown> = {}) =>
    fetch(`/api/data/${tool}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(args),
    }).then(json<ToolResult>),
  newConversation: () => fetch('/api/conversations', { method: 'POST' }).then(json<{ id: string }>),
  conversations: () => fetch('/api/conversations').then(json<{ id: string; title: string; updated_at: string }[]>),
  conversation: (id: string) => fetch(`/api/conversations/${id}`).then(json<{ id: string; turns: { text: string; events: AgentEvent[]; doc?: UploadedDoc }[] }>),
  async upload(file: File): Promise<UploadedDoc> {
    const bytes = new Uint8Array(await file.arrayBuffer())
    let binary = ''
    for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
    return fetch('/api/documents', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: file.name, content_base64: btoa(binary) }),
    }).then(json<UploadedDoc>)
  },
  alerts: (status?: string) => fetch(`/api/alerts${status ? `?status=${status}` : ''}`).then(json<Row[]>),
  ackAlert: (alert_key: string) => fetch('/api/alerts/ack', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ alert_key }),
  }).then(json<{ acknowledged: string }>),
  actions: (status?: string) => fetch(`/api/actions${status ? `?status=${status}` : ''}`).then(json<Action[]>),
  decide: (id: string, decision: 'approve' | 'reject' | 'undo') =>
    fetch(`/api/actions/${id}/${decision}`, { method: 'POST' }).then(json<{ action: Action }>),

  /** Streams the agent's events (Server-Sent Events over a POST) and calls onEvent for each one. */
  async chat(conversationId: string, text: string, onEvent: (e: AgentEvent) => void, signal?: AbortSignal) {
    const res = await fetch(`/api/conversations/${conversationId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
      signal,
    })
    if (!res.ok || !res.body) throw new Error(`${res.status} ${await res.text()}`)
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let cut: number
      while ((cut = buffer.indexOf('\n\n')) >= 0) {
        const chunk = buffer.slice(0, cut)
        buffer = buffer.slice(cut + 2)
        if (chunk.startsWith('data: ')) onEvent(JSON.parse(chunk.slice(6)) as AgentEvent)
      }
    }
  },
}

// ---- formatting ---------------------------------------------------------------------------------

const PCT_KEYS = /(_pct|_rate|^cei$|^nrr$|^grr$|share_of_actual|accuracy|utilization)/
const MONEY_KEYS = /(revenue|cost|cogs|opex|burn|cash|arr|amount|balance|budget|actual|variance|margin(?!_pct)|eac|etc|earned|billed|unbilled|deferred|value|funded|ceiling|remaining|commitments|mrr|ar_over|ar$|sales|total|spend|forecast|fees|rate$|price)/

export function fmt(key: string, v: unknown, unit?: string): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'boolean') return v ? 'Yes' : 'No'
  if (Array.isArray(v)) return v.join(', ')
  if (typeof v !== 'number') return typeof v === 'string' && isCode(v) ? display(v) : String(v)
  const u = unit ?? (PCT_KEYS.test(key) ? 'ratio' : MONEY_KEYS.test(key) ? 'usd' : undefined)
  if (u === 'ratio') return `${(v * 100).toFixed(1)}%`
  if (u === 'usd') {
    const abs = Math.abs(v)
    const s = abs >= 1e6 ? `$${(abs / 1e6).toFixed(2)}M` : abs >= 1e4 ? `$${(abs / 1e3).toFixed(1)}K` : `$${abs.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
    return v < 0 ? `−${s}` : s
  }
  if (u === 'months' || u === 'days') return v.toFixed(1)
  if (u === 'count') return v.toLocaleString()
  return Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 2 })
}

export const label = (key: string) => display(key)
