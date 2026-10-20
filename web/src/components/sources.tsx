// Where a page's numbers come from, shown on hover instead of as raw table names on the page. Every tool a page
// loads registers its source tables here; cards and KPI tiles show an ⓘ that explains what they show and lists
// those sources in plain words (with the exact tables underneath, for anyone tracing a number).
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

type Sources = { list: string[]; add: (s: string) => void }
const SourcesContext = createContext<Sources | null>(null)

export function SourcesProvider({ children }: { children: ReactNode }) {
  const [list, setList] = useState<string[]>([])
  const add = (s: string) => setList((l) => (l.includes(s) ? l : [...l, s]))
  return <SourcesContext.Provider value={{ list, add }}>{children}</SourcesContext.Provider>
}

/** Register a tool result's source string (called by useTool when data arrives). */
export function useRegisterSource(source?: string) {
  const ctx = useContext(SourcesContext)
  useEffect(() => { if (source && ctx) ctx.add(source) }, [source])  // eslint-disable-line react-hooks/exhaustive-deps
}

const ACRONYMS = new Set(['gl', 'ap', 'ar', 'po', 'gpu', 'mrr', 'arr', 'nrr', 'grr', 'cogs', 'kpi', 'kpis', 'fx', 'odc', 'crm', 'cac',
  'ltv', 'ebitda', 'rou', 'je', 'bva', 'npv', 'irr', 'wacc', 'dcf', 'rpo', 'crpo', 'sku', 'gcp', 'lrp', 'ml', 'api', 'tm', 'eac', 'fte', 'sla', 'cei', 'dso', 'dpo', 'vat', 'gst', 'us', 'uk', 'usd', 'mtm', 'clin'])
const NAMES: Record<string, string> = {
  batch_pro: 'Batch Pro', batch_base: 'Batch Base', stream: 'Streaming', annotate_co: 'Annotate Co', fedsec: 'FedSec', nimbus: 'Nimbus',
  series_a: 'Series A', series_b: 'Series B', seed: 'Seed', self_serve: 'Self-serve', mid_market: 'Mid-market', one_off: 'One-off',
  po_not_found: 'PO not found', fav_variance: 'Favorable variance', tm: 'Time and materials', fixed_fee: 'Fixed fee',
  cost_minus_cash: 'Cost minus cash', cumulative_cost_minus_cash: 'Cumulative cost minus cash',
  rep_id: 'Rep', customer_id: 'Customer', vendor_id: 'Vendor', opportunity_id: 'Deal', project_id: 'Project',
  contract_id: 'Contract', account_id: 'Account', department_id: 'Department', entity_id: 'Entity', invoice_ref: 'Invoice',
}

/** A readable name for a code like batch_pro, duplicate_invoice or gl_revenue_vs_rated_usage. */
export function display(code: string): string {
  if (NAMES[code]) return NAMES[code]
  const words = code.split('_').map((w) => (w === 'pct' ? '%' : ACRONYMS.has(w) ? w.toUpperCase() : w))
  const s = words.join(' ')
  return s.charAt(0).toUpperCase() + s.slice(1)
}

export const isCode = (v: string) => /^[a-z][a-z0-9]*(_[a-z0-9]+)+$/.test(v) || NAMES[v] !== undefined

/** "marts.fct_unit_economics_monthly" -> "Unit economics (monthly)"; tool names and notes are left out. */
function friendly(table: string): string | null {
  const t = table.trim().replace(/\s*\(.*\)$/, '')
  if (!t || t.startsWith('get_')) return null
  const name = t.split('.').pop() ?? t
  let core = name.replace(/^(fct|stg|int|dim|recon)_+/, '').replace(/^[a-z]+__/, '')
  const monthly = /_monthly$/.test(core), daily = /_daily$/.test(core)
  core = core.replace(/_(monthly|daily)$/, '')
  return `${display(core)}${monthly ? ' (monthly)' : daily ? ' (daily)' : ''}`
}

function parse(sources: string[]) {
  const tables = sources.flatMap((s) => s.split(/[,;+]|\band\b/).map((x) => x.trim()).filter((x) => /^[a-z]/.test(x) && /[_.]/.test(x)))
  const unique = [...new Set(tables.map((t) => t.replace(/\s*\(.*$/, '')))]
  const names = [...new Set(unique.map(friendly).filter(Boolean))] as string[]
  return { names, tables: unique }
}

/** The ⓘ with a hover panel: what this card shows, and the page's data sources. */
export function InfoTip({ what }: { what?: ReactNode }) {
  const ctx = useContext(SourcesContext)
  const { names, tables } = parse(ctx?.list ?? [])
  if (!what && !names.length) return null
  return (
    <span className="infotip" tabIndex={0} aria-label="What this shows and where the data comes from">
      ⓘ
      <span className="infotip-panel" role="tooltip">
        {what && <span className="infotip-what">{what}</span>}
        {names.length > 0 && <>
          <span className="infotip-h">Data comes from</span>
          <span className="infotip-src">{names.slice(0, 6).join(' · ')}</span>
          <span className="infotip-tables">{tables.slice(0, 8).join(', ')}</span>
        </>}
      </span>
    </span>
  )
}

/** Codes inside a sentence get readable names ("batch_pro at $0.07/hour" -> "Batch Pro at $0.07/hour"); table and
    file references (marts.fct_x, seeds/x.csv) are kept exact. Standalone codes are left alone, because filters and
    links rely on them; they are made readable where they are displayed. */
export function humanizeText(s: string): string {
  if (!s.includes(' ')) return s
  return s.replace(/(^|[^./\w])([a-z][a-z0-9]*(?:_[a-z0-9]+)+)(?![\w.]*\.csv)(?=$|[^\w.]|\.(?:\s|$))/g, (_m, pre, code) => pre + display(code))
}

/** Apply humanizeText to every sentence in a tool result, except where sources are named. */
export function humanizeResult<T>(v: T, key = ''): T {
  if (key === 'source' || key === 'sources') return v
  if (typeof v === 'string') return humanizeText(v) as unknown as T
  if (Array.isArray(v)) return v.map((x) => humanizeResult(x)) as unknown as T
  if (v && typeof v === 'object') {
    return Object.fromEntries(Object.entries(v as Record<string, unknown>).map(([k, x]) => [k, humanizeResult(x, k)])) as T
  }
  return v
}
