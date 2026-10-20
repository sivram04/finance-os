// Executive views: the scorecard with context (vs last month, budget, last year, benchmark, trend), the monthly
// "what changed and why", growth (ARR waterfall, cohorts, customer health, unit economics) and the sales pipeline.
// Every number comes from the same read-only tools the assistant uses.
import { display } from '../components/sources'
import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fmt, type Row } from '../api'
import { AskButton, Card, Chip, DataTable, Loading, Source, useTool, useWorkspace } from '../components/common'

const AXIS = { tick: { fontSize: 11, fill: 'var(--faint)' }, tickLine: false, axisLine: false } as const
const TIP = { contentStyle: { background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 } }
const usd = (v: unknown) => fmt('amount', v as number, 'usd')
const pct = (v: unknown, signed = false) => (v == null ? '—' : `${signed && (v as number) > 0 ? '+' : ''}${((v as number) * 100).toFixed(1)}%`)
const TONE: Record<string, string> = { good: 'var(--good, #2f9e6b)', ok: 'var(--warn, #c98a1b)', bad: 'var(--bad, #d1495b)' }

function show(metric: string, unit: string, v: unknown) {
  if (v == null) return '—'
  if (metric === 'burn_multiple') return `${(v as number).toFixed(2)}x`
  if (metric === 'rule_of_40') return `${((v as number) * 100).toFixed(0)}`
  if (metric === 'runway_months' && (v as number) > 60) return '60+ mo'
  if (unit === 'months') return `${(v as number).toFixed(1)} mo`
  return fmt(metric, v, unit)
}

function Head({ title, sub, ask }: { title: string; sub: string; ask: string }) {
  return (
    <div className="page-head">
      <div><h1>{title}</h1><p>{sub}</p></div>
      <AskButton text={ask}>Ask the assistant</AskButton>
    </div>
  )
}

function Spark({ values, good }: { values: (number | null)[]; good: boolean | null }) {
  const pts = values.map((v, i) => ({ i, v }))
  return (
    <div style={{ height: 28 }}>
      <ResponsiveContainer>
        <LineChart data={pts} margin={{ top: 2, bottom: 2, left: 0, right: 0 }}>
          <YAxis hide domain={['dataMin', 'dataMax']} />
          <Line dataKey="v" stroke={good == null ? 'var(--accent)' : good ? TONE.good : TONE.bad} strokeWidth={1.6} dot={false} isAnimationActive animationDuration={700} connectNulls />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

// percent change is only meaningful for a positive base; ratios move in points; huge runways don't move at all
const NEEDS_YEAR = new Set(['nrr', 'grr', 'rule_of_40'])

function deltaText(r: Row, change: number | null) {
  const m = String(r.metric), u = String(r.unit), prior = r.prior as number | null, v = r.value as number | null
  if (v == null && NEEDS_YEAR.has(m)) return 'needs 12 months of history'
  if (r.undefined_reason) return String(r.undefined_reason)
  if (change == null) return r.prior == null && v != null ? 'not defined last month' : 'no prior month'
  if (m === 'runway_months') {  // months, never percent; anything past five years is "60+"
    if ((v ?? 0) > 60 && (prior ?? 0) > 60) return 'above 5 years, unchanged'
    if ((v ?? 0) > 60) return `up from ${(prior ?? 0).toFixed(1)} mo`
    if ((prior ?? 0) > 60) return 'down from 60+ mo'
    return `${change > 0 ? '▲' : '▼'} ${Math.abs(change).toFixed(1)} mo vs last month`
  }
  if (u === 'usd' && ((v ?? 0) < 0 || (prior ?? 0) < 0)) {  // a percent across zero means nothing: show dollars
    return `${change > 0 ? '▲' : '▼'} ${show(m, u, Math.abs(change))} vs last month`
  }
  const arrow = change > 0 ? '▲' : change < 0 ? '▼' : '·'
  const size = u === 'ratio' && m !== 'burn_multiple' && m !== 'rule_of_40' ? `${(Math.abs(change) * 100).toFixed(1)} pts`
    : m === 'rule_of_40' ? `${(Math.abs(change) * 100).toFixed(0)} pts`
    : prior != null && prior > 0 && r.change_pct != null ? pct(Math.abs(r.change_pct as number))
    : show(m, u, Math.abs(change))
  return `${arrow} ${size} vs last month`
}

function contextText(r: Row) {
  const u = String(r.unit), v = r.value as number | null
  if (r.budget != null && v != null) {
    return u === 'ratio' ? `${((v - (r.budget as number)) * 100 > 0 ? '+' : '')}${((v - (r.budget as number)) * 100).toFixed(1)} pts vs budget`
      : `${pct(r.vs_budget_pct, true)} vs budget`
  }
  if (r.last_year != null && v != null && (r.last_year as number) > 0 && String(r.metric) !== 'runway_months') {
    return u === 'ratio' ? `${((v - (r.last_year as number)) * 100 > 0 ? '+' : '')}${((v - (r.last_year as number)) * 100).toFixed(1)} pts vs last year`
      : `${pct(r.yoy_pct, true)} vs last year`
  }
  return ''
}

// ---- Scorecard ---------------------------------------------------------------------------------------------

export function Scorecard({ month }: { month?: string } = {}) {
  const { inspect } = useWorkspace()
  const s = useTool('get_kpi_scorecard', month ? { month } : {})
  if (!s.data) return <Loading state={s} />
  const netBurn = ((s.data.rows as Row[]).find((x) => x.metric === 'net_burn')?.value ?? null) as number | null
  return (
    <div className="grid cols-6 scorecard">
      {(s.data.rows as Row[]).map((row) => {
        let r = row
        const change = r.change as number | null
        const flatRunway = r.metric === 'runway_months' && Number(r.value) > 60 && Number(r.prior ?? 0) > 60
        if (r.metric === 'burn_multiple' && netBurn != null && netBurn <= 0) r = { ...r, value: null, undefined_reason: 'not meaningful: cash generated this month', status: null }
        const better = change == null || change === 0 || flatRunway || r.undefined_reason || r.value == null ? null : (change > 0) === (r.higher_is_better as boolean)
        const kpiId = ['net_new_arr', 'burn_multiple', 'rule_of_40', 'cac_payback_months'].includes(String(r.metric)) ? null : String(r.metric)
        return (
          <button key={String(r.metric)} className="card kpi clickable score" disabled={!kpiId}
            title={r.benchmark_source ? `Benchmark: ${r.benchmark_source}` : 'Open the trend and definition'}
            onClick={() => kpiId && inspect({ kind: 'kpi', id: kpiId })}
            style={{ borderTop: `3px solid ${r.status ? TONE[String(r.status)] : 'var(--border)'}` }}>
            <div className="label">{r.metric === 'net_burn' && Number(r.value) < 0 ? 'Net burn (cash generated)' : String(r.label)}</div>
            <div className="value">{show(String(r.metric), String(r.unit), r.value)}</div>
            <div className="delta" style={{ color: better == null ? 'var(--faint)' : better ? TONE.good : TONE.bad }}>
              {deltaText(r, change)}
            </div>
            <div className="note">
              {contextText(r)}
              {r.benchmark_median != null ? `${r.vs_budget_pct != null || r.yoy_pct != null ? ' · ' : ''}bench ${show(String(r.metric), String(r.unit), r.benchmark_good)}` : ''}
            </div>
            <Spark values={(r.spark as (number | null)[]) ?? []} good={r.status ? r.status !== 'bad' : null} />
          </button>
        )
      })}
    </div>
  )
}

// ---- What changed and why -----------------------------------------------------------------------------------

export function MonthSummary({ month }: { month?: string } = {}) {
  const s = useTool('get_month_summary', month ? { month } : {})
  return (
    <Card title={`${s.data?.month ? String(s.data.month) : 'This month'}: what changed and why`} sub={s.data ? String(s.data.headline) : undefined}
      right={<AskButton text="Walk me through this month: what changed, why, and what I should do about it. Lead with the conclusion.">Dig in</AskButton>}>
      {s.data ? (
        <div className="summary-grid">
          {(s.data.sections as Row[]).map((sec) => (
            <div key={String(sec.title)} className="summary-section" style={{ borderLeft: `3px solid ${sec.status ? TONE[String(sec.status)] : 'var(--border)'}` }}>
              <div className="summary-title">{String(sec.title)} {sec.status ? <Chip value={sec.status === 'bad' ? 'needs attention' : sec.status === 'ok' ? 'ok' : 'on track'} kind={sec.status === 'bad' ? 'bad' : sec.status === 'ok' ? 'warn' : 'good'} /> : null}</div>
              <ul>{(sec.bullets as string[]).map((b, i) => <li key={i}>{b}</li>)}</ul>
            </div>
          ))}
        </div>
      ) : <Loading state={s} />}
    </Card>
  )
}

// ---- Growth: ARR waterfall, cohorts, customer health, unit economics --------------------------------------

function Waterfall({ row }: { row: Row }) {
  const steps: [string, number][] = [['Opening ARR', row.opening_arr as number], ['New', row.new_arr as number], ['Expansion', row.expansion_arr as number],
    ['Reactivation', row.reactivation_arr as number], ['Contraction', row.contraction_arr as number], ['Churn', row.churned_arr as number]]
  let run = 0
  const data = steps.map(([name, v], i) => {
    const base = i === 0 ? 0 : v >= 0 ? run : run + v
    run = i === 0 ? v : run + v
    return { name, base, v: Math.abs(v), sign: i === 0 ? 'total' : v >= 0 ? 'up' : 'down' }
  })
  data.push({ name: 'Closing ARR', base: 0, v: row.closing_arr as number, sign: 'total' })
  const color = (s: string) => (s === 'total' ? 'var(--accent)' : s === 'up' ? TONE.good : TONE.bad)
  // start the axis just below the lowest point the bars reach, so the moves are readable next to total ARR
  const lows = data.filter((d) => d.sign !== 'total').map((d) => d.base)
  const lo = Math.floor((Math.min(...lows, data[0].v, data.at(-1)!.v) * 0.9) / 1e5) * 1e5
  return (
    <div style={{ height: 260 }}>
      <ResponsiveContainer>
        <BarChart data={data} margin={{ left: 8, right: 8, top: 8 }}>
          <CartesianGrid stroke="var(--border)" vertical={false} />
          <XAxis dataKey="name" {...AXIS} />
          <YAxis tickFormatter={usd} width={70} domain={[Math.max(0, lo), 'auto']} allowDataOverflow {...AXIS} />
          <Tooltip formatter={(v, n) => (n === 'base' ? null : usd(v))} {...TIP} />
          <Bar dataKey="base" stackId="w" fill="transparent" isAnimationActive animationDuration={700} />
          <Bar dataKey="v" stackId="w" radius={[3, 3, 0, 0]} isAnimationActive animationDuration={700}>
            {data.map((d, i) => <Cell key={i} fill={color(d.sign)} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function heat(v: number | null | undefined, kind: string) {
  if (v == null) return 'transparent'
  const t = Math.max(0, Math.min(1, kind === 'revenue' ? (v - 0.5) / 0.8 : v))  // net revenue: 50% → 130% scale; gross and logos: 0-100%
  return `color-mix(in srgb, var(--accent) ${Math.round(12 + t * 70)}%, transparent)`
}

function Cohorts() {
  const [kind, setKind] = useState<'revenue' | 'gross' | 'logo'>('revenue')
  const c = useTool('get_cohort_retention', { kind, max_months: 12 })
  const rows = (c.data?.rows as Row[] | undefined) ?? []
  const cols = Array.from({ length: 13 }, (_, i) => `m${i}`).filter((k) => kind === 'logo' || k !== 'm0')
  return (
    <Card title="Cohort retention" sub={kind === 'revenue' ? 'Net revenue retention by vintage: what each cohort pays vs its first full month (above 100% = it grew)'
      : kind === 'gross' ? 'Gross revenue retention by vintage: each customer capped at its first-month revenue, so expansion cannot hide churn' : 'Share of each signup cohort still paying'}
      right={<div className="segmented"><button className={kind === 'revenue' ? 'on' : ''} onClick={() => setKind('revenue')}>Net revenue</button><button className={kind === 'gross' ? 'on' : ''} onClick={() => setKind('gross')}>Gross revenue</button><button className={kind === 'logo' ? 'on' : ''} onClick={() => setKind('logo')}>Logos</button></div>}>
      {c.data ? (
        <div className="sheet-wrap" style={{ maxHeight: 420 }}>
          <table className="cohort">
            <thead><tr><th>Cohort</th><th className="num">Customers</th>{cols.map((k) => <th key={k} className="num">{k.replace('m', 'M')}</th>)}</tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={String(r.cohort)}><td>{String(r.cohort)}</td><td className="num">{String(r.customers)}</td>
                {cols.map((k) => <td key={k} className="num" style={{ background: heat(r[k] as number | null, kind) }}>{r[k] == null ? '' : `${Math.round((r[k] as number) * 100)}%`}</td>)}</tr>
            ))}</tbody>
          </table>
        </div>
      ) : <Loading state={c} />}
    </Card>
  )
}

export function Growth() {
  const g = useTool('get_growth_efficiency', { months: 12 })
  const h = useTool('get_customer_health')
  const u = useTool('get_product_unit_economics', { months: 12 })
  const rows = (g.data?.rows as Row[] | undefined) ?? []
  const last = rows.at(-1)
  const conc = (h.data?.concentration ?? {}) as Row
  const sum = Object.fromEntries(((h.data?.summary ?? []) as Row[]).map((r) => [r.health, r]))
  const products = [...new Set(((u.data?.rows ?? []) as Row[]).map((r) => String(r.product_id)))]
  const byMonth = Object.values(((u.data?.rows ?? []) as Row[]).reduce<Record<string, Row>>((a, r) => {
    const m = String(r.month); a[m] ??= { month: m }; a[m][`${r.product_id}_margin`] = r.gross_margin_pct; a[m][`${r.product_id}_cost`] = r.cost_per_hour; return a
  }, {}))
  const COLORS = ['var(--accent)', '#2f9e6b', '#c98a1b', '#8a63d2']
  return (
    <div className="page">
      <Head title="Growth" sub="Where ARR comes from and goes, how cohorts retain, which customers are at risk and what each product earns per hour."
        ask="Is our growth healthy? Use the ARR waterfall, quick ratio, burn multiple, cohorts and at-risk customers, and tell me what to do." />
      <div className="grid cols-4">
        {[['Net new ARR (month)', last ? usd(last.net_new_arr) : '—', ''],
          ['Quick ratio (3 mo)', last?.quick_ratio != null ? `${(last.quick_ratio as number).toFixed(1)}x` : '—', 'ARR added per ARR lost · 4x strong'],
          ['Burn multiple (3 mo)', last?.burn_multiple != null ? `${(last.burn_multiple as number).toFixed(2)}x` : 'n/m', 'net burn / net new ARR · under 1x best'],
          ['At-risk ARR', sum.at_risk ? usd(sum.at_risk.arr) : '$0', `${sum.at_risk?.customers ?? 0} at risk · ${sum.watch?.customers ?? 0} to watch`]]
          .map(([l, v, n]) => <div key={l} className="card kpi"><div className="label">{l}</div><div className="value">{v}</div><div className="note">{n}</div></div>)}
      </div>
      <div className="grid cols-2">
        <Card title="ARR waterfall" sub={last ? `${String(last.month)}: opening → closing ARR · no FX step: contracts are priced in USD and billed in local currency at the day's rate, so currency moves land in realized FX (Tax & FX), not ARR` : ''}>
          {last ? <Waterfall row={last} /> : <Loading state={g} />}
        </Card>
        <Card title="Net new ARR by month" sub="Gross added (new + expansion + reactivation) vs lost (contraction + churn)">
          {g.data ? (
            <div style={{ height: 260 }}>
              <ResponsiveContainer>
                <BarChart data={rows.map((r) => ({ month: r.month, added: (r.new_arr as number) + (r.expansion_arr as number) + (r.reactivation_arr as number), lost: (r.contraction_arr as number) + (r.churned_arr as number), net: r.net_new_arr }))} margin={{ left: 8, right: 8, top: 8 }} stackOffset="sign">
                  <CartesianGrid stroke="var(--border)" vertical={false} />
                  <XAxis dataKey="month" {...AXIS} />
                  <YAxis tickFormatter={usd} width={70} {...AXIS} />
                  <Tooltip formatter={usd} {...TIP} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <ReferenceLine y={0} stroke="var(--faint)" />
                  <Bar dataKey="added" name="Added" stackId="a" fill={TONE.good} />
                  <Bar dataKey="lost" name="Lost" stackId="a" fill={TONE.bad} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : <Loading state={g} />}
        </Card>
      </div>
      <Cohorts />
      <div className="grid cols-2">
        <Card title="Customers at risk" sub="Leading indicators: usage trend, silence, disputes, late payment, margin floor">
          {h.data ? <DataTable title="customer_health" rows={(h.data.rows as Row[]).filter((r) => r.health !== 'healthy')} empty="No customer is at risk or on watch."
            columns={[{ key: 'customer_id' }, { key: 'health', chip: true }, { key: 'arr', unit: 'usd' }, { key: 'usage_trend', label: 'Usage 30d vs prior', unit: 'ratio' }, { key: 'reasons' }]} /> : <Loading state={h} />}
        </Card>
        <Card title="Revenue concentration" sub="Share of last month's revenue · top 10 above about half is a diligence flag">
          {h.data ? (
            <>
              <div className="grid cols-3">
                {[['Top customer', conc.top1], ['Top 5', conc.top5], ['Top 10', conc.top10]].map(([l, v]) => (
                  <div key={String(l)} className="card kpi"><div className="label">{String(l)}</div><div className="value" style={{ color: l === 'Top 10' && (v as number) > 0.55 ? TONE.bad : undefined }}>{pct(v)}</div></div>))}
              </div>
              <DataTable rows={(h.data.rows as Row[]).filter((r) => (r.revenue_rank as number) <= 10).sort((a, b) => (a.revenue_rank as number) - (b.revenue_rank as number))}
                columns={[{ key: 'revenue_rank', label: '#' }, { key: 'customer_id' }, { key: 'segment', chip: true }, { key: 'arr', unit: 'usd' }, { key: 'revenue_share', label: 'Share', unit: 'ratio' }, { key: 'health', chip: true }]} />
            </>
          ) : <Loading state={h} />}
        </Card>
      </div>
      <div className="grid cols-2">
        <Card title="Gross margin by product" sub="Revenue minus cost to serve, per product, by month">
          {u.data ? (
            <div style={{ height: 240 }}>
              <ResponsiveContainer>
                <LineChart data={byMonth} margin={{ left: 8, right: 8, top: 8 }}>
                  <CartesianGrid stroke="var(--border)" vertical={false} />
                  <XAxis dataKey="month" {...AXIS} />
                  <YAxis tickFormatter={(v) => pct(v)} width={52} {...AXIS} />
                  <Tooltip formatter={(v) => pct(v)} {...TIP} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  {products.map((p, i) => <Line key={p} dataKey={`${p}_margin`} name={display(p)} stroke={COLORS[i % 4]} strokeWidth={2} dot={false} />)}
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : <Loading state={u} />}
        </Card>
        <Card title="Cost to serve per audio hour" sub="COGS per hour by product: GPU, shared GPU, unused commit and cloud">
          {u.data ? (
            <div style={{ height: 240 }}>
              <ResponsiveContainer>
                <LineChart data={byMonth} margin={{ left: 8, right: 8, top: 8 }}>
                  <CartesianGrid stroke="var(--border)" vertical={false} />
                  <XAxis dataKey="month" {...AXIS} />
                  <YAxis tickFormatter={(v) => `$${(v as number).toFixed(3)}`} width={60} {...AXIS} />
                  <Tooltip formatter={(v) => `$${(v as number).toFixed(4)}`} {...TIP} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  {products.map((p, i) => <Line key={p} dataKey={`${p}_cost`} name={display(p)} stroke={COLORS[i % 4]} strokeWidth={2} dot={false} />)}
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : <Loading state={u} />}
        </Card>
      </div>
      <Source data={g.data} />
    </div>
  )
}

// ---- Pipeline ------------------------------------------------------------------------------------------------

export function Pipeline() {
  const p = useTool('get_pipeline')
  const d = p.data as (Row & { rows: Row[] }) | undefined
  const q = (d?.next_quarter ?? {}) as Row
  return (
    <div className="page">
      <Head title="Pipeline" sub="Sales-led deals from the CRM: what is open, what is likely to close next quarter against quota, and what has slipped."
        ask="Review the pipeline like a VP Sales and CFO would: coverage, slipped deals, win rates, and whether next quarter's number is at risk." />
      {d ? (
        <>
          <div className="grid cols-4">
            <div className="card kpi"><div className="label">Open pipeline</div><div className="value">{usd(d.total_arr)}</div><div className="note">{usd(d.weighted_arr)} weighted by stage</div></div>
            <div className="card kpi"><div className="label">Coverage, {String(q.quarter)}</div><div className="value" style={{ color: (q.coverage as number) >= 3 ? TONE.good : TONE.bad }}>{(q.coverage as number).toFixed(1)}x</div><div className="note">{usd(q.pipeline_arr)} vs {usd(q.quota)} quota · 3x+ healthy</div></div>
            <div className="card kpi"><div className="label">Slipped deals</div><div className="value" style={{ color: (d.slipped as number) > 0 ? TONE.bad : undefined }}>{String(d.slipped)}</div><div className="note">{usd(d.slipped_arr)} past close date, still open</div></div>
            <div className="card kpi"><div className="label">Win rate</div><div className="value">{pct(((d.win_rates as Row[]) ?? []).reduce((a, r) => a + (r.won as number), 0) / Math.max(1, ((d.win_rates as Row[]) ?? []).reduce((a, r) => a + (r.won as number) + (r.lost as number), 0)))}</div>
              <div className="note">{((d.win_rates as Row[]) ?? []).map((r) => `${String(r.segment).replace('_', ' ')} ${pct(r.win_rate)} · ${Math.round(r.avg_cycle_days as number)}d cycle`).join(' · ')}</div></div>
          </div>
          <div className="grid cols-2">
            <Card title="Pipeline by stage" sub="Total vs probability-weighted ARR">
              <div style={{ height: 240 }}>
                <ResponsiveContainer>
                  <BarChart data={d.by_stage as Row[]} margin={{ left: 8, right: 8, top: 8 }}>
                    <CartesianGrid stroke="var(--border)" vertical={false} />
                    <XAxis dataKey="stage" {...AXIS} />
                    <YAxis tickFormatter={usd} width={70} {...AXIS} />
                    <Tooltip formatter={usd} {...TIP} />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Bar dataKey="arr" name="Run-rate ARR" fill="var(--accent)" fillOpacity={0.35} radius={[3, 3, 0, 0]} />
                    <Bar dataKey="weighted_arr" name="Weighted" fill="var(--accent)" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
            <Card title="Bookings by month" sub="ARR of sales-led deals won">
              <div style={{ height: 240 }}>
                <ResponsiveContainer>
                  <BarChart data={d.bookings as Row[]} margin={{ left: 8, right: 8, top: 8 }}>
                    <CartesianGrid stroke="var(--border)" vertical={false} />
                    <XAxis dataKey="month" {...AXIS} />
                    <YAxis tickFormatter={usd} width={70} {...AXIS} />
                    <Tooltip formatter={usd} {...TIP} />
                    <Bar dataKey="bookings_arr" name="Bookings" fill={TONE.good} radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
          </div>
          <Card title="Sales capacity vs results" sub="Ramp-adjusted capacity (AEs on payroll and planned hires; quota × ramp × 80% attainment, seeds/sales_capacity_policy.csv) against ARR credited to sales (new + expansion) and new-logo bookings">
            <div style={{ height: 240 }}>
              <ResponsiveContainer>
                <LineChart data={(d.capacity ?? []) as Row[]} margin={{ left: 8, right: 16, top: 8 }}>
                  <CartesianGrid stroke="var(--border)" vertical={false} />
                  <XAxis dataKey="month" {...AXIS} />
                  <YAxis tickFormatter={usd} width={70} {...AXIS} />
                  <Tooltip formatter={usd} {...TIP} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Line dataKey="capacity_arr" name="Capacity" stroke="#7a8699" strokeDasharray="5 4" strokeWidth={2} dot={false} isAnimationActive animationDuration={700} />
                  <Line dataKey="credited_arr" name="Credited ARR (new + expansion)" stroke={TONE.good} strokeWidth={2} dot={false} isAnimationActive animationDuration={700} />
                  <Line dataKey="bookings_arr" name="New-logo bookings" stroke="var(--accent)" strokeWidth={2} dot={false} isAnimationActive animationDuration={700} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="muted">{(() => { const c = (d.capacity ?? []) as Row[]; const next = c.find((r) => r.is_forecast); const plannedRow = c.at(-1)
              return next ? `${String(next.account_executives)} AEs now (${String(next.ramped_aes)} fully ramped); ${String(plannedRow?.planned_aes ?? 0)} planned hires take capacity to ${usd(plannedRow?.capacity_arr)} a month by ${String(plannedRow?.month)}.` : '' })()}</div>
          </Card>
          <Card title="Open deals" sub="Slipped = expected close date has passed · age vs the median won sales cycle">
            <DataTable title="open_pipeline" rows={d.rows} columns={[{ key: 'opportunity_id' }, { key: 'account_name' }, { key: 'segment', chip: true }, { key: 'rep_id' },
              { key: 'stage', chip: true }, { key: 'amount_arr', label: 'ARR', unit: 'usd' }, { key: 'weighted_arr', label: 'Weighted', unit: 'usd' }, { key: 'close_date' },
              { key: 'close_quarter', label: 'Quarter' }, { key: 'is_slipped', label: 'Slipped', flag: 'bad' }, { key: 'age_days', label: 'Age (days)' }, { key: 'median_won_cycle_days', label: 'Typical cycle' }]} />
          </Card>
          <Source data={p.data} />
        </>
      ) : <Loading state={p} />}
    </div>
  )
}
