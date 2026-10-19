// Dashboard kit with cross-filtering. Wrap a page in <Dash>; then clicking a slice or bar in any Donut / Bars filters
// every KPI, chart and DataTable on the page by that value (rows that carry the same field). A chart never filters
// itself: it highlights the selection and dims the rest, so the selection's share stays visible.
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { Bar, BarChart, Brush, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, Rectangle, ReferenceLine, ResponsiveContainer, Sector, Tooltip, XAxis, YAxis } from 'recharts'
import { fmt, label, type Row } from '../api'
import { WorkspaceContext } from './common'

export type Filters = Record<string, string>

// ---- Period: the year range every time chart and monthly table shows (picked in the page bar) ----------------
export type Period = 'all' | '12m' | `${number}`
export const PeriodContext = createContext<{ period: Period; setPeriod: (p: Period) => void }>({ period: 'all', setPeriod: () => {} })
export const usePeriod = () => useContext(PeriodContext)
const MONTHLY = /^\d{4}-\d{2}/

/** Rows inside the period, judged on the first field that holds a YYYY-MM value (month, week, date). */
export function inPeriod(rows: Row[], period: Period, x?: string) {
  if (period === 'all' || !rows.length) return rows
  const key = x ?? ['month', 'week_start', 'week', 'spend_date', 'date'].find((k) => rows.some((r) => MONTHLY.test(String(r[k] ?? ''))))
  if (!key || !rows.some((r) => MONTHLY.test(String(r[key] ?? '')))) return rows
  if (period === '12m') {
    const last = rows.map((r) => String(r[key] ?? '').slice(0, 7)).filter((v) => MONTHLY.test(v)).sort().at(-1)!
    const [y, m] = last.split('-').map(Number)
    const from = `${m === 12 ? y : y - 1}-${String(m === 12 ? 1 : m + 1).padStart(2, '0')}`
    return rows.filter((r) => { const v = String(r[key] ?? '').slice(0, 7); return !MONTHLY.test(v) || (v >= from && v <= last) })
  }
  return rows.filter((r) => { const v = String(r[key] ?? ''); return !MONTHLY.test(v) || v.startsWith(period) })
}
type Ctx = { filters: Filters; toggle: (key: string, value: string) => void; clear: (key?: string) => void }
export const FilterContext = createContext<Ctx | null>(null)
export const useFilters = () => useContext(FilterContext)

export const PALETTE = ['#3b6fd8', '#2f9e6b', '#c98a1b', '#8a63d2', '#d1495b', '#3aa6b9', '#7a8699']
export const TONE = { good: 'var(--good, #2f9e6b)', ok: 'var(--warn, #c98a1b)', bad: 'var(--bad, #d1495b)' }
const AXIS = { tick: { fontSize: 11, fill: 'var(--faint)' }, tickLine: false, axisLine: false } as const
const TIP = { contentStyle: { background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 } }
const pretty = (v: string) => v.replace(/_/g, ' ')

// Recharts 3 ignores onClick on <Pie>/<Cell> in some layouts, so clicks are attached to the drawn SVG shape itself.
type ShapeProps = Record<string, unknown> & { payload?: Record<string, unknown> }
const clickableSector = (onPick: (p: ShapeProps) => void) => (p: unknown) =>
  <Sector {...(p as object)} style={{ cursor: 'pointer' }} onClick={() => onPick(p as ShapeProps)} />
const clickableBar = (onPick: (p: ShapeProps) => void) => (p: unknown) =>
  <Rectangle {...(p as object)} style={{ cursor: 'pointer' }} onClick={() => onPick(p as ShapeProps)} />

/** Rows matching every active filter whose field the rows carry; `except` skips one field (a chart's own). */
export function applyFilters(rows: Row[], filters: Filters, except?: string) {
  const active = Object.entries(filters).filter(([k]) => k !== except && rows.some((r) => k in r))
  return active.length ? rows.filter((r) => active.every(([k, v]) => String(r[k]) === v)) : rows
}

export function useFiltered(rows: Row[] | undefined, except?: string) {
  const f = useFilters()
  return useMemo(() => applyFilters(rows ?? [], f?.filters ?? {}, except), [rows, f?.filters, except])
}

export function Dash({ children }: { children: ReactNode }) {
  const [filters, setFilters] = useState<Filters>({})
  const toggle = useCallback((key: string, value: string) =>
    setFilters((f) => (f[key] === value ? Object.fromEntries(Object.entries(f).filter(([k]) => k !== key)) : { ...f, [key]: value })), [])
  const clear = useCallback((key?: string) => setFilters((f) => (key ? Object.fromEntries(Object.entries(f).filter(([k]) => k !== key)) : {})), [])
  const ctx = useMemo(() => ({ filters, toggle, clear }), [filters, toggle, clear])
  return <FilterContext.Provider value={ctx}><FilterBar />{children}</FilterContext.Provider>
}

const DRILL_KEYS: Record<string, 'customer' | 'vendor' | 'project'> = { customer_id: 'customer', vendor_id: 'vendor', project_id: 'project' }

function FilterBar() {
  const f = useFilters()
  const ws = useContext(WorkspaceContext)
  const entries = Object.entries(f?.filters ?? {})
  if (!entries.length) return <div className="filter-bar empty">Click any slice or bar to filter the whole page · click a month on a trend to drill into it · drag the slider under a chart to zoom.</div>
  return (
    <div className="filter-bar">
      <span className="faint">Filtered by</span>
      {entries.map(([k, v]) => (
        <button key={k} className="filter-chip" onClick={() => f!.clear(k)} title="Remove this filter">
          {label(k)}: <b>{pretty(v)}</b> <span aria-hidden>×</span>
        </button>
      ))}
      {entries.filter(([k]) => DRILL_KEYS[k]).map(([k, v]) => (
        <button key={`open-${k}`} className="btn small" onClick={() => ws?.inspect({ kind: DRILL_KEYS[k], id: v })}>Open {DRILL_KEYS[k]} {v} details</button>
      ))}
      <button className="btn small" onClick={() => f!.clear()}>Clear all</button>
    </div>
  )
}

/** Drill-down from a time chart: on a cross-filtering page, clicking a month filters every table and chart on the
 *  page to that month (click it again to clear). Off such pages time charts only zoom. */
function drillTo(f: Ctx | null, x: string) {
  if (!f) return null
  return (value?: string) => { if (value != null && MONTHLY.test(String(value))) f.toggle(x, String(value)) }
}

/** Sum a measure (or count rows when measure is undefined) by a dimension, largest first. */
export function groupSum(rows: Row[], dim: string, measure?: string, order?: string[]) {
  const m = new Map<string, number>()
  rows.forEach((r) => { const k = String(r[dim] ?? '—'); m.set(k, (m.get(k) ?? 0) + (measure ? Number(r[measure] ?? 0) : 1)) })
  const out = [...m.entries()].map(([name, value]) => ({ name, value }))
  return order ? out.sort((a, b) => order.indexOf(a.name) - order.indexOf(b.name)) : out.sort((a, b) => b.value - a.value)
}

// ---- KPI cards ------------------------------------------------------------------------------------------------

export type Kpi = { label: string; value: string; note?: ReactNode; tone?: 'good' | 'ok' | 'bad' | null; title?: string }

export function KpiRow({ items }: { items: Kpi[] }) {
  return (
    <div className={`grid cols-${Math.min(items.length, 6)} kpi-row`}>
      {items.map((k) => (
        <div key={k.label} className="card kpi" title={k.title} style={{ borderTop: `3px solid ${k.tone ? TONE[k.tone] : 'var(--border)'}` }}>
          <div className="label">{k.label}</div>
          <div className="value" style={k.tone === 'bad' ? { color: TONE.bad } : undefined}>{k.value}</div>
          {k.note != null && <div className="note">{k.note}</div>}
        </div>
      ))}
    </div>
  )
}

// ---- Charts that filter -------------------------------------------------------------------------------------

type Breakdown = { rows: Row[]; dim: string; measure?: string; unit?: string; order?: string[]; colors?: Record<string, string>; height?: number }

function useBreakdown({ rows, dim, measure, order }: Breakdown) {
  const f = useFilters()
  const own = useFiltered(rows, dim)  // filtered by everything except this chart's own field
  const data = useMemo(() => groupSum(own, dim, measure, order), [own, dim, measure, order])
  const selected = f?.filters[dim]
  return { data, selected, click: (name: string) => f?.toggle(dim, name) }
}

export function Donut(props: Breakdown) {
  const { data, selected, click } = useBreakdown(props)
  const total = data.reduce((a, d) => a + d.value, 0)
  const show = (v: number) => (props.measure ? fmt(props.measure, v, props.unit ?? 'usd') : String(v))
  const color = (n: string, i: number) => props.colors?.[n] ?? PALETTE[i % PALETTE.length]
  return (
    <div className="donut">
      <div style={{ height: props.height ?? 200, position: 'relative' }}>
        <ResponsiveContainer>
          <PieChart>
            <Pie data={data} dataKey="value" nameKey="name" innerRadius="58%" outerRadius="88%" paddingAngle={1} isAnimationActive={false}
              shape={clickableSector((p) => click(String(p.payload?.name ?? p.name)))}>
              {data.map((d, i) => <Cell key={d.name} fill={color(d.name, i)} fillOpacity={!selected || selected === d.name ? 1 : 0.25} stroke="var(--card)"
                />)}
            </Pie>
            <Tooltip formatter={(v) => show(v as number)} {...TIP} />
          </PieChart>
        </ResponsiveContainer>
        <div className="donut-center"><div className="faint">{selected ? pretty(selected) : 'Total'}</div>
          <b>{show(selected ? data.find((d) => d.name === selected)?.value ?? 0 : total)}</b></div>
      </div>
      <div className="legend-list">
        {data.map((d, i) => (
          <button key={d.name} className={`legend-item ${selected === d.name ? 'on' : ''}`} onClick={() => click(d.name)} style={{ opacity: !selected || selected === d.name ? 1 : 0.5 }}>
            <i style={{ background: color(d.name, i) }} />{pretty(d.name)}<span>{show(d.value)} · {total ? Math.round((d.value / total) * 100) : 0}%</span>
          </button>
        ))}
      </div>
    </div>
  )
}

/** Horizontal bars (top N by value) that filter on click. `stack` splits each bar by a second field. */
export function Bars({ top = 8, stack, signed, refX, valueFormat, ...props }: Breakdown & { top?: number; signed?: boolean; refX?: { x: number; label: string }[]; valueFormat?: (v: number) => string; stack?: { key: string; values: string[]; labels?: Record<string, string>; colors?: Record<string, string> } }) {
  const f = useFilters()
  const own = useFiltered(props.rows, props.dim)
  const selected = f?.filters[props.dim]
  const data = useMemo(() => {
    const grouped = groupSum(own, props.dim, props.measure, props.order)
    const base = (signed ? [...grouped].sort((a, b) => Math.abs(b.value) - Math.abs(a.value)) : grouped).slice(0, top)
    if (!stack) return base
    return base.map((b) => {
      const row: Row = { name: b.name, value: b.value }
      stack.values.forEach((s) => { row[s] = own.filter((r) => String(r[props.dim]) === b.name && String(r[stack.key]) === s).reduce((a, r) => a + Number(props.measure ? r[props.measure] ?? 0 : 1), 0) })
      return row
    })
  }, [own, props.dim, props.measure, props.order, top, stack])
  const show = (v: unknown) => (valueFormat ? valueFormat(v as number) : props.measure ? fmt(props.measure, v as number, props.unit ?? 'usd') : String(v))
  const opacity = (name: unknown) => (!selected || selected === name ? 1 : 0.25)
  return (
    <div style={{ height: props.height ?? Math.max(160, data.length * 30 + 30) }}>
      <ResponsiveContainer>
        <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16, top: 4, bottom: 4 }} style={{ cursor: 'pointer' }}>
          <CartesianGrid stroke="var(--border)" horizontal={false} />
          <XAxis type="number" tickFormatter={show} allowDecimals={!!props.measure} {...AXIS} />
          <YAxis type="category" dataKey="name" width={110} tickFormatter={pretty} {...AXIS} style={{ cursor: 'pointer' }}
            onClick={(t: unknown) => { const v = (t as { value?: string })?.value; if (v != null) f?.toggle(props.dim, String(v)) }} />
          <Tooltip formatter={(v) => show(v)} labelFormatter={(l) => pretty(String(l))} {...TIP} />
          {stack ? stack.values.map((s, i) => (
            <Bar key={s} dataKey={s} name={stack.labels?.[s] ?? pretty(s)} stackId="s" fill={stack.colors?.[s] ?? PALETTE[i]} isAnimationActive={false}
              shape={clickableBar((p) => f?.toggle(props.dim, String(p.payload?.name)))}>
              {data.map((d) => <Cell key={String(d.name)} fillOpacity={opacity(d.name)} />)}
            </Bar>
          )) : (
            <Bar dataKey="value" radius={[0, 3, 3, 0]} isAnimationActive={false} shape={clickableBar((p) => f?.toggle(props.dim, String(p.payload?.name)))}>
              {data.map((d, i) => <Cell key={String(d.name)} fill={signed ? ((d.value as number) >= 0 ? TONE.good : TONE.bad) : props.colors?.[String(d.name)] ?? PALETTE[props.colors ? i : 0]} fillOpacity={opacity(d.name)} />)}
            </Bar>
          )}
          {stack && <Legend wrapperStyle={{ fontSize: 12 }} />}
          {signed && <ReferenceLine x={0} stroke="var(--faint)" />}
          {(refX ?? []).map((r) => <ReferenceLine key={r.label} x={r.x} stroke="var(--faint)" strokeDasharray="4 4" label={{ value: r.label, fontSize: 11, fill: 'var(--faint)', position: 'top' }} />)}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

/** A trend by month (or week): lines, with optional target / reference lines. Not a filter source. */
export function Trend({ rows, x, series, unit = 'usd', refs = [], height = 220, format }: {
  rows: Row[]; x: string; series: { key: string; label: string; color?: string; dashed?: boolean }[]; unit?: string
  refs?: { y: number; label: string; color?: string }[]; height?: number; format?: (v: number) => string
}) {
  const show = format ?? ((v: number) => fmt(series[0]?.key ?? 'value', v, unit))
  const { period } = usePeriod()
  const f = useFilters()
  rows = useMemo(() => inPeriod(rows, period, x), [rows, period, x])
  const drill = drillTo(f, x)
  const zoom = rows.length > 12
  return (
    <div style={{ height: height + (zoom ? 30 : 0) }}>
      <ResponsiveContainer>
        <LineChart data={rows} margin={{ left: 8, right: 16, top: 8 }} onClick={drill ? (st) => drill((st as { activeLabel?: string })?.activeLabel) : undefined} style={drill ? { cursor: 'pointer' } : undefined}>
          <CartesianGrid stroke="var(--border)" vertical={false} />
          <XAxis dataKey={x} {...AXIS} />
          <YAxis tickFormatter={(v) => show(v as number)} width={64} {...AXIS} />
          <Tooltip formatter={(v) => show(v as number)} {...TIP} />
          {series.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
          {refs.map((r) => <ReferenceLine key={r.label} y={r.y} stroke={r.color ?? 'var(--faint)'} strokeDasharray="4 4" label={{ value: r.label, fontSize: 11, fill: 'var(--faint)', position: 'insideTopRight' }} />)}
          {series.map((s, i) => <Line key={s.key} dataKey={s.key} name={s.label} stroke={s.color ?? PALETTE[i]} strokeWidth={2} strokeDasharray={s.dashed ? '5 4' : undefined} dot={false} activeDot={{ r: 5 }} isAnimationActive={false} />)}
          {f?.filters[x] && <ReferenceLine x={f.filters[x]} stroke="var(--accent)" strokeWidth={2} />}
          {zoom && <Brush dataKey={x} height={22} stroke="var(--accent)" fill="var(--panel)" travellerWidth={8} />}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

/** Vertical bars over time (e.g. receipts by week). Not a filter source. */
export function Columns({ rows, x, y, unit = 'usd', color = PALETTE[0], height = 220, xFormat }: {
  rows: Row[]; x: string; y: string; unit?: string; color?: string; height?: number; xFormat?: (v: string) => string
}) {
  const { period } = usePeriod()
  const f = useFilters()
  rows = useMemo(() => inPeriod(rows, period, x), [rows, period, x])
  const drill = drillTo(f, x)
  const zoom = rows.length > 14
  return (
    <div style={{ height: height + (zoom ? 30 : 0) }}>
      <ResponsiveContainer>
        <BarChart data={rows} margin={{ left: 8, right: 16, top: 8 }} onClick={drill ? (st) => drill((st as { activeLabel?: string })?.activeLabel) : undefined} style={drill ? { cursor: 'pointer' } : undefined}>
          <CartesianGrid stroke="var(--border)" vertical={false} />
          <XAxis dataKey={x} tickFormatter={xFormat} {...AXIS} />
          <YAxis tickFormatter={(v) => fmt(y, v as number, unit)} width={64} {...AXIS} />
          <Tooltip formatter={(v) => fmt(y, v as number, unit)} labelFormatter={(l) => (xFormat ? xFormat(String(l)) : String(l))} {...TIP} />
          <Bar dataKey={y} radius={[3, 3, 0, 0]} isAnimationActive={false}>
            {rows.map((r, i) => <Cell key={i} fill={color} fillOpacity={f?.filters[x] && f.filters[x] !== String(r[x]) ? 0.3 : 1} />)}
          </Bar>
          {zoom && <Brush dataKey={x} height={22} stroke="var(--accent)" fill="var(--panel)" travellerWidth={8} />}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}


/** Bridge (waterfall) from a starting total to an ending total through signed steps, green up / red down. */
export function Bridge({ start, steps, end, height = 260, format }: {
  start: { name: string; value: number }; steps: { name: string; value: number }[]; end: { name: string; value: number }; height?: number; format?: (v: number) => string
}) {
  const show = format ?? ((v: number) => fmt('amount', v, 'usd'))
  let run = start.value
  const data = [{ name: start.name, base: 0, v: start.value, kind: 'total' }]
  steps.forEach((s) => {
    data.push({ name: s.name, base: s.value >= 0 ? run : run + s.value, v: Math.abs(s.value), kind: s.value >= 0 ? 'up' : 'down' })
    run += s.value
  })
  data.push({ name: end.name, base: 0, v: end.value, kind: 'total' })
  const vals = data.flatMap((d) => [d.base, d.base + d.v]).concat(data.filter((d) => d.kind === 'total').map((d) => d.v))
  const lo = Math.min(...vals), hi = Math.max(...vals)
  const pad = (hi - lo) * 0.08 || 1
  const color = (k: string) => (k === 'total' ? PALETTE[0] : k === 'up' ? TONE.good : TONE.bad)
  // totals that are negative are drawn from their value up to zero
  const rows = data.map((d) => (d.kind === 'total' && d.v < 0 ? { ...d, base: d.v, v: -d.v } : d))
  return (
    <div style={{ height }}>
      <ResponsiveContainer>
        <BarChart data={rows} margin={{ left: 8, right: 16, top: 8 }}>
          <CartesianGrid stroke="var(--border)" vertical={false} />
          <XAxis dataKey="name" interval={0} angle={-25} textAnchor="end" height={54} tick={{ fontSize: 10, fill: 'var(--faint)' }} tickLine={false} axisLine={false} />
          <YAxis tickFormatter={(v) => show(v as number)} width={70} domain={[Math.min(0, lo - pad), hi + pad]} {...AXIS} />
          <Tooltip formatter={(v, n, item) => (n === 'base' ? null : show((item.payload as { kind: string }).kind === 'down' ? -(v as number) : (v as number)))} {...TIP} />
          <ReferenceLine y={0} stroke="var(--faint)" />
          <Bar dataKey="base" stackId="w" fill="transparent" isAnimationActive={false} />
          <Bar dataKey="v" stackId="w" radius={[3, 3, 0, 0]} isAnimationActive={false}>
            {rows.map((d, i) => <Cell key={i} fill={color(d.kind)} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

/** Vertical grouped bars per category (e.g. earned vs billed per project); clicking a category filters the page. */
export function GroupedBars({ rows, dim, series, unit = 'usd', height = 240, refs = [] }: {
  rows: Row[]; dim: string; series: { key: string; label: string; color?: string }[]; unit?: string; height?: number; refs?: { y: number; label: string }[]
}) {
  const f = useFilters()
  const own = useFiltered(rows, dim)
  const selected = f?.filters[dim]
  const show = (v: number) => (unit === 'ratio' ? `${Math.round(v * 100)}%` : fmt('amount', v, unit))
  return (
    <div style={{ height }}>
      <ResponsiveContainer>
        <BarChart data={own} margin={{ left: 8, right: 16, top: 8 }} style={{ cursor: 'pointer' }}>
          <CartesianGrid stroke="var(--border)" vertical={false} />
          <XAxis dataKey={dim} {...AXIS} />
          <YAxis tickFormatter={(v) => show(v as number)} width={64} {...AXIS} />
          <Tooltip formatter={(v) => show(v as number)} {...TIP} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {refs.map((r) => <ReferenceLine key={r.label} y={r.y} stroke="var(--faint)" strokeDasharray="4 4" label={{ value: r.label, fontSize: 11, fill: 'var(--faint)', position: 'insideTopRight' }} />)}
          {series.map((s, i) => (
            <Bar key={s.key} dataKey={s.key} name={s.label} fill={s.color ?? PALETTE[i]} radius={[3, 3, 0, 0]} isAnimationActive={false}
              shape={clickableBar((p) => f?.toggle(dim, String(p.payload?.[dim])))}>
              {own.map((d) => <Cell key={String(d[dim])} fillOpacity={!selected || selected === String(d[dim]) ? 1 : 0.25} />)}
            </Bar>
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
