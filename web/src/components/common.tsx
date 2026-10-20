import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { display, InfoTip, isCode, useRegisterSource } from './sources'
import { describe, useNames } from './names'
import { applyFilters, FilterContext, inPeriod, usePeriod } from './Dash'
import { api, fmt, label, type Row, type ToolResult } from '../api'

// ---- app context: navigation and handing questions to the assistant ------------------------------

export type Page = 'home' | 'alerts' | 'reports' | 'financials' | 'analysis' | 'growth' | 'pipeline' | 'scenarios' | 'entities' | 'deals' | 'comp' | 'revenue' | 'spend' | 'budget' | 'plan' | 'cash' | 'close' | 'projects' | 'billing' | 'ar' | 'ap' | 'pricing' | 'capital' | 'tax' | 'trust' | 'contracts' | 'drivers' | 'ceo' | 'explore' | 'corpfin' | 'calculators' | 'kpis' | 'predictions' | 'treasury' | 'controller' | 'welcome'

export type EntityKind = 'customer' | 'vendor' | 'project' | 'kpi' | 'invoice'
export interface Entity { kind: EntityKind; id: string }

export interface Workspace {
  page: Page
  go: (p: Page) => void
  ask: (text: string) => void
  refreshKey: number
  refresh: () => void
  inspect: (e: Entity) => void   // open the drill-down panel for a customer, vendor, project or KPI
}

export const WorkspaceContext = createContext<Workspace | null>(null)
export const useWorkspace = () => useContext(WorkspaceContext)!

// ---- data -----------------------------------------------------------------------------------------

export function useTool(tool: string, args: Record<string, unknown> = {}) {
  const { refreshKey } = useWorkspace()
  const { period } = usePeriod()
  // a year in the Period control means "as of that year's last month" for every tool that takes a month (the API
  // applies it only where the tool has a month argument and none was given; the latest closed month caps it)
  const asOf = /^\d{4}$/.test(period) && !FORWARD.test(tool) ? `${period}-12` : null
  const key = JSON.stringify(asOf && !('month' in args) ? { ...args, _as_of: asOf } : args)
  const [state, setState] = useState<{ data?: ToolResult; error?: string; loading: boolean }>({ loading: true })
  useEffect(() => {
    let live = true
    setState((s) => ({ ...s, loading: true }))
    api.data(tool, JSON.parse(key))
      .then((data) => live && setState({ data, loading: false }))
      .catch((e) => live && setState({ error: String(e), loading: false }))
    return () => { live = false }
  }, [tool, key, refreshKey])
  useRegisterSource(state.data?.source)
  // the Period control (top bar) narrows every monthly series a page loads, so hand-built charts follow it too;
  // forward-looking tools (forecasts, scenarios) and Explore keep their own ranges
  return useMemo(() => {
    if (!state.data || period === 'all' || FORWARD.test(tool)) return state
    const data: ToolResult = { ...state.data }
    for (const [k, v] of Object.entries(data)) {
      if (Array.isArray(v) && v.length && typeof v[0] === 'object' && v[0] !== null) (data as Record<string, unknown>)[k] = inPeriod(v as Row[], period)
    }
    return { ...state, data }
  }, [state, period, tool])
}

const FORWARD = /forecast|stress|scenario|sweep|fundraise|long_range|explore|runway|cap_table|predictions|_ml/

// ---- display --------------------------------------------------------------------------------------

// file and table references in a card's subtitle move to its ⓘ hover; the visible line keeps the plain explanation
function visibleSub(sub: ReactNode) {
  if (typeof sub !== 'string') return sub
  return sub.replace(/\s*\([^()]*(seeds\/|marts\.|fct_)[^()]*\)/g, '').replace(/[;,]?\s*(assumptions in )?seeds\/[\w]+\.csv/g, '').replace(/\s{2,}/g, ' ').trim()
}

export function Card({ title, sub, right, children, className = '' }:
  { title?: ReactNode; sub?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {(title || right) && (
        <div className="card-head">
          <div><h2>{title}{title && <InfoTip what={sub ?? title} />}</h2>{sub && <div className="sub">{visibleSub(sub)}</div>}</div>
          {right}
        </div>
      )}
      <div className="card-body">{children}</div>
    </section>
  )
}

export function Loading({ state }: { state: { loading: boolean; error?: string } }) {
  if (state.error) return <div className="error">Could not load: {state.error}</div>
  return <div className="skeleton" aria-label="Loading"><span /><span /><span /></div>
}

const GOOD = new Set(['pass', 'paid', 'auto_approve', 'approved', 'current', 'answered'])
const BAD = new Set(['fail', 'overapplied', 'needs_review', 'rejected', 'high', '90+', 'churn', 'exceeds_cap_or_funding'])
const WARN = new Set(['open', 'ready', 'sent', 'pending', 'medium', '61-90', '31-60', 'contraction', 'reverted'])

export function Chip({ value, kind }: { value: ReactNode; kind?: 'good' | 'warn' | 'bad' | 'info' }) {
  const v = String(value)
  const k = kind ?? (GOOD.has(v) ? 'good' : BAD.has(v) ? 'bad' : WARN.has(v) ? 'warn' : undefined)
  const text = isCode(v) ? display(v) : /^[a-z]+$/.test(v) ? v.charAt(0).toUpperCase() + v.slice(1) : v.replace(/_/g, ' ')
  return <span className={`chip ${k ?? ''}`}>{text}</span>
}

export interface Column {
  key: string
  label?: string
  unit?: 'usd' | 'ratio' | 'days' | 'count' | 'months'
  chip?: boolean
  flag?: 'bad' | 'warn' | 'good'   // render booleans as a chip when true
  render?: (row: Row) => ReactNode
}

// columns whose values open a drill-down panel when clicked
const ENTITY_KEYS: Record<string, EntityKind> = { customer_id: 'customer', vendor_id: 'vendor', project_id: 'project', invoice_ref: 'invoice', invoice_id: 'invoice', applied_ref: 'invoice', correct_invoice_ref: 'invoice' }

function csvCell(v: unknown) {
  const t = v == null ? '' : Array.isArray(v) ? v.join('; ') : String(v)
  return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t
}

const PAGE = 15

export function DataTable({ rows, columns, onRow, empty = 'Nothing here.', title = 'export', pageSize = PAGE }:
  { rows: Row[]; columns: Column[]; onRow?: (r: Row) => void; empty?: string; title?: string; pageSize?: number }) {
  const { inspect } = useWorkspace()
  useNames()
  // inside a <Dash> page, the page's cross-filters apply to any table whose rows carry the filtered field
  const pageFilters = useContext(FilterContext)?.filters
  const allRows = rows
  const { period } = usePeriod()
  rows = useMemo(() => inPeriod(pageFilters ? applyFilters(allRows, pageFilters) : allRows, period), [allRows, pageFilters, period])
  const [q, setQ] = useState('')
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null)
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [pg, setPg] = useState(0)
  // categorical columns (chips or few distinct short values) get a dropdown filter
  const facets = useMemo(() => columns.filter((c) => {
    if (c.render || c.flag) return false
    const vals = new Set(rows.map((r) => r[c.key]).filter((v) => v != null && typeof v !== 'number'))
    return (c.chip || ENTITY_KEYS[c.key] === undefined) && vals.size > 1 && vals.size <= 12 && rows.length > 6
  }).map((c) => ({ key: c.key, label: c.label ?? label(c.key),
                   values: [...new Set(rows.map((r) => String(r[c.key] ?? '')))].filter(Boolean).sort() })), [rows, columns])
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase()
    let out = rows.filter((r) => (!needle || columns.some((c) => String(r[c.key] ?? '').toLowerCase().includes(needle)))
      && Object.entries(filters).every(([k, v]) => !v || String(r[k] ?? '') === v))
    if (sort) {
      out = [...out].sort((a, b) => {
        const x = a[sort.key], y = b[sort.key]
        if (x == null) return 1
        if (y == null) return -1
        return (typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y))) * sort.dir
      })
    }
    return out
  }, [rows, columns, q, filters, sort])
  useEffect(() => setPg(0), [q, filters, sort, rows])
  if (!rows.length) return <div className="muted">{allRows.length ? 'No rows match the page filter.' : empty}</div>
  const numeric = (c: Column) => !c.chip && !c.flag && !c.render && typeof rows.find((r) => r[c.key] != null)?.[c.key] === 'number'
  const toggleSort = (key: string) => setSort((s) => (s?.key === key ? (s.dir === 1 ? { key, dir: -1 } : null) : { key, dir: 1 }))
  const exportCsv = () => {
    const lines = [columns.map((c) => csvCell(c.label ?? label(c.key))).join(','),
      ...shown.map((r) => columns.map((c) => csvCell(r[c.key])).join(','))]
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/csv' }))
    a.download = `${title.replace(/\W+/g, '_').toLowerCase()}.csv`
    a.click()
  }
  const tools = rows.length > 6
  const pages = Math.ceil(shown.length / pageSize)
  const page = Math.min(pg, Math.max(pages - 1, 0))
  return (
    <div>
      {tools && (
        <div className="table-tools">
          <input className="table-search" placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} />
          {facets.map((f) => (
            <select key={f.key} value={filters[f.key] ?? ''} onChange={(e) => setFilters({ ...filters, [f.key]: e.target.value })}>
              <option value="">{f.label}: all</option>
              {f.values.map((v) => <option key={v} value={v}>{v.replace(/_/g, ' ')}</option>)}
            </select>
          ))}
          <span className="spacer" />
          <span className="faint">{shown.length === rows.length ? `${rows.length} rows` : `${shown.length} of ${rows.length}`}</span>
          <button className="btn small" onClick={exportCsv}>CSV</button>
        </div>
      )}
      <div className="table-wrap">
        <table>
          <thead><tr>{columns.map((c) => (
            <th key={c.key} className={`${numeric(c) ? 'num' : ''} sortable`} onClick={() => toggleSort(c.key)}>
              {c.label ?? label(c.key)}{sort?.key === c.key ? (sort.dir === 1 ? ' ▲' : ' ▼') : ''}
            </th>))}</tr></thead>
          <tbody>
            {shown.slice(page * pageSize, page * pageSize + pageSize).map((r, i) => (
              <tr key={i} className={onRow ? 'clickable' : ''} onClick={onRow ? () => onRow(r) : undefined}>
                {columns.map((c) => (
                  <td key={c.key} className={`${numeric(c) ? 'num' : ''}${/(^|_)(date|month|week_of)$/.test(c.key) ? ' nowrap' : ''}`}>
                    {c.render ? c.render(r)
                      : ENTITY_KEYS[c.key] && r[c.key] ? (
                        <button className="link" title={`${describe(r[c.key]) ?? String(r[c.key])} · click for details`} onClick={(e) => { e.stopPropagation(); inspect({ kind: ENTITY_KEYS[c.key], id: String(r[c.key]) }) }}>
                          {isCode(String(r[c.key])) ? display(String(r[c.key])) : String(r[c.key])}
                        </button>)
                      : c.chip ? (r[c.key] == null ? '—' : <Chip value={String(r[c.key])} />)
                      : c.flag ? (r[c.key] ? <Chip value={c.label ?? label(c.key)} kind={c.flag} /> : '')
                      : fmt(c.key, r[c.key], c.unit)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {!shown.length && <div className="muted" style={{ padding: 8 }}>No rows match.</div>}
      </div>
      {pages > 1 && (
        <div className="pager">
          <button className="btn small" disabled={page === 0} onClick={() => setPg(page - 1)}>Previous</button>
          <span className="faint">Page {page + 1} of {pages}</span>
          <button className="btn small" disabled={page >= pages - 1} onClick={() => setPg(page + 1)}>Next</button>
        </div>
      )}
    </div>
  )
}

// sources are no longer printed on the page: each card's ⓘ shows them on hover (components/sources)
export function Source({ data }: { data?: ToolResult }) {
  useRegisterSource(data?.source)
  return null
}

export function AskButton({ text, children = 'Ask about this' }: { text: string; children?: ReactNode }) {
  const { ask } = useWorkspace()
  return <button className="btn small" onClick={() => ask(text)}>{children}</button>
}
