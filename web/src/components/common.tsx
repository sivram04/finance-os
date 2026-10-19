import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, fmt, label, type Row, type ToolResult } from '../api'

// ---- app context: navigation and handing questions to the assistant ------------------------------

export type Page = 'home' | 'alerts' | 'deals' | 'comp' | 'revenue' | 'spend' | 'budget' | 'plan' | 'cash' | 'close' | 'projects' | 'billing' | 'ar' | 'ap' | 'pricing' | 'capital' | 'tax' | 'trust'

export interface Workspace {
  page: Page
  go: (p: Page) => void
  ask: (text: string) => void
  refreshKey: number
  refresh: () => void
}

export const WorkspaceContext = createContext<Workspace | null>(null)
export const useWorkspace = () => useContext(WorkspaceContext)!

// ---- data -----------------------------------------------------------------------------------------

export function useTool(tool: string, args: Record<string, unknown> = {}) {
  const { refreshKey } = useWorkspace()
  const key = JSON.stringify(args)
  const [state, setState] = useState<{ data?: ToolResult; error?: string; loading: boolean }>({ loading: true })
  useEffect(() => {
    let live = true
    setState((s) => ({ ...s, loading: true }))
    api.data(tool, JSON.parse(key))
      .then((data) => live && setState({ data, loading: false }))
      .catch((e) => live && setState({ error: String(e), loading: false }))
    return () => { live = false }
  }, [tool, key, refreshKey])
  return state
}

// ---- display --------------------------------------------------------------------------------------

export function Card({ title, sub, right, children, className = '' }:
  { title?: ReactNode; sub?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {(title || right) && (
        <div className="card-head">
          <div><h2>{title}</h2>{sub && <div className="sub">{sub}</div>}</div>
          {right}
        </div>
      )}
      {children}
    </section>
  )
}

export function Loading({ state }: { state: { loading: boolean; error?: string } }) {
  if (state.error) return <div className="error">Could not load: {state.error}</div>
  return <div className="muted"><span className="spinner" /> Loading…</div>
}

const GOOD = new Set(['pass', 'paid', 'auto_approve', 'approved', 'current', 'answered'])
const BAD = new Set(['fail', 'overapplied', 'needs_review', 'rejected', 'high', '90+', 'churn', 'exceeds_cap_or_funding'])
const WARN = new Set(['open', 'ready', 'sent', 'pending', 'medium', '61-90', '31-60', 'contraction', 'reverted'])

export function Chip({ value, kind }: { value: ReactNode; kind?: 'good' | 'warn' | 'bad' | 'info' }) {
  const v = String(value)
  const k = kind ?? (GOOD.has(v) ? 'good' : BAD.has(v) ? 'bad' : WARN.has(v) ? 'warn' : undefined)
  return <span className={`chip ${k ?? ''}`}>{v.replace(/_/g, ' ')}</span>
}

export interface Column {
  key: string
  label?: string
  unit?: 'usd' | 'ratio' | 'days' | 'count' | 'months'
  chip?: boolean
  flag?: 'bad' | 'warn' | 'good'   // render booleans as a chip when true
  render?: (row: Row) => ReactNode
}

export function DataTable({ rows, columns, onRow, empty = 'Nothing here.' }:
  { rows: Row[]; columns: Column[]; onRow?: (r: Row) => void; empty?: string }) {
  if (!rows.length) return <div className="muted">{empty}</div>
  const numeric = (c: Column) => !c.chip && !c.flag && !c.render && typeof rows.find((r) => r[c.key] != null)?.[c.key] === 'number'
  return (
    <div className="table-wrap">
      <table>
        <thead><tr>{columns.map((c) => <th key={c.key} className={numeric(c) ? 'num' : ''}>{c.label ?? label(c.key)}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={onRow ? 'clickable' : ''} onClick={onRow ? () => onRow(r) : undefined}>
              {columns.map((c) => (
                <td key={c.key} className={numeric(c) ? 'num' : ''}>
                  {c.render ? c.render(r)
                    : c.chip ? (r[c.key] == null ? '—' : <Chip value={String(r[c.key])} />)
                    : c.flag ? (r[c.key] ? <Chip value={c.label ?? label(c.key)} kind={c.flag} /> : '')
                    : fmt(c.key, r[c.key], c.unit)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Source({ data }: { data?: ToolResult }) {
  if (!data) return null
  return <div className="source">Source: {data.source}{data.note ? ` · ${data.note}` : ''}</div>
}

export function AskButton({ text, children = 'Ask about this' }: { text: string; children?: ReactNode }) {
  const { ask } = useWorkspace()
  return <button className="btn small" onClick={() => ask(text)}>✦ {children}</button>
}
