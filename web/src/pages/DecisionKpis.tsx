// Decision KPIs: every number with its purpose, definition, owner, source, lineage, reconciliation status, threshold
// and the decision it triggers; the contribution-margin bridge; the unresolved control queue; unit economics movers;
// runway and margin sensitivity; and data trust.
import { useEffect, useState } from 'react'
import { Bridge, KpiRow } from '../components/Dash'
import { fmt, type Row } from '../api'
import { CountText } from '../components/Motion'
import { MonthToDate } from '../components/MonthToDate'
import { usePeriod } from '../components/Dash'
import { Recommend } from '../components/Recommend'
import { AskButton, Card, Chip, DataTable, Loading, Source, useTool, useWorkspace, type Page } from '../components/common'

const STATUS_COLOR: Record<string, string> = { red: 'var(--bad)', amber: 'var(--warn)', green: 'var(--good)', grey: 'var(--faint)' }
const pct = (v: unknown) => (v == null ? '—' : `${(Number(v) * 100).toFixed(1)}%`)

function show(r: Row) {
  const v = r.value as number | null
  if (v == null) return '—'
  return r.unit === 'usd' ? fmt('amount', v, 'usd') : r.unit === 'ratio' ? (Math.abs(v) < 5 && !/ratio|multiple|magic|ltv/.test(String(r.metric)) ? pct(v) : `${v.toFixed(2)}x`)
    : r.unit === 'days' ? `${v.toFixed(1)} days` : r.unit === 'months' ? (v > 60 ? '60+ mo' : `${v.toFixed(1)} mo`) : v.toLocaleString()
}

function compareText(r: Row) {
  const x = r.compare_value as number | null
  if (x == null) return ''
  return r.compare_basis === 'value' ? '' : `${String(r.compare_basis)}: ${x >= 0 ? '+' : ''}${(x * 100).toFixed(1)}%`
}

export function DecisionKpis() {
  const k = useTool('get_decision_kpis')
  const { period } = usePeriod()
  const [open, setOpen] = useState<Row | null>(null)
  if (!k.data) return <div className="page"><Loading state={k} /></div>
  const rows = k.data.rows as Row[]
  const counts = k.data.counts as Record<string, number>
  const trust = k.data.trust as Row
  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Decision KPIs</h1><p>{`Every number with its purpose, definition, owner, source, reconciliation status and threshold · recommendations are reasoned by the AI from current data, not stored · ${String(k.data.month)}`}</p></div>
        <AskButton text="Which KPIs are red or amber this month, why, and what do you recommend given today's data?">Ask the assistant</AskButton>
      </div>
      <KpiRow items={[
        { label: 'Red', value: String(counts.red), note: 'past the red line', tone: counts.red ? 'bad' : 'good' },
        { label: 'Amber', value: String(counts.amber), note: 'past the amber line', tone: counts.amber ? 'ok' : 'good' },
        { label: 'Green', value: String(counts.green), note: 'within threshold', tone: 'good' },
        { label: 'Data trust', value: Number(trust.recon_checks_failing) ? `${String(trust.recon_checks_failing)} breaks` : 'All reconciled', note: `${String(trust.recon_checks_run)} checks this month · live through ${String(trust.live_through)}`, tone: Number(trust.recon_checks_failing) ? 'bad' : 'good' },
      ]} />
      {period === 'mtd' && <MonthToDate compact />}
      <Card title="KPIs by status" sub="Click a KPI for its definition, owner, source, lineage, reconciliation and an AI recommendation on today's data">
        <div className="kpi-decision-grid">
          {rows.map((r) => (
            <button key={String(r.metric)} className={`kpi-decision ${open?.metric === r.metric ? 'on' : ''}`} style={{ borderTopColor: STATUS_COLOR[String(r.status)] }} onClick={() => setOpen(r)}>
              <span className="label">{String(r.label)}</span>
              <span className="value"><CountText text={show(r)} /></span>
              <span className="decision" style={{ color: r.status === 'green' ? 'var(--muted)' : STATUS_COLOR[String(r.status)] }}>{String(r.status_reason)}</span>
              <span className="owner">{String(r.owner)} · recon {String(r.recon_status)}</span>
            </button>
          ))}
        </div>
      </Card>
      {open && <KpiContract r={open} onClose={() => setOpen(null)} />}
      <ControlQueue />
      <ContributionBridge />
      <Sensitivity />
      <Source data={k.data} />
    </div>
  )
}

function KpiContract({ r, onClose }: { r: Row; onClose: () => void }) {
  const t = r.threshold as Row
  const items: [string, React.ReactNode][] = [
    ['Status', <Chip key="s" value={String(r.status)} kind={r.status === 'red' ? 'bad' : r.status === 'amber' ? 'warn' : 'good'} />],
    ['Value', `${show(r)} ${compareText(r)}`],
    ['Purpose', String(r.purpose)],
    ['Definition', String(r.formula)],
    ['Threshold', `${String(t.basis)} · ${String(t.better)} is better · amber at ${String(t.amber)} · red at ${String(t.red)}`],
    ['Why this status', String(r.status_reason)],
    ['Owner', String(r.owner)],
    ['Source model', String(r.source_model)],
    ['Lineage: raw sources', ((r.lineage_sources ?? []) as string[]).join(', ') || '—'],
    ['Lineage: seeds', ((r.lineage_seeds ?? []) as string[]).join(', ') || '—'],
    ['Lineage: models in between', `${((r.lineage_models ?? []) as string[]).length} models (${((r.lineage_models ?? []) as string[]).slice(0, 6).join(', ')}${((r.lineage_models ?? []) as string[]).length > 6 ? ', …' : ''})`],
    ['Reconciliation', `${String(r.recon_status)}${((r.recon_checks ?? []) as string[]).length ? ` · ${((r.recon_checks ?? []) as string[]).join(', ')}` : ''}`],
    ['Version / freshness', `v${String(r.version)} · closed through ${String((r.freshness as Row).closed_through)} · live through ${String((r.freshness as Row).live_through)}`],
  ]
  return (
    <Card title={`${String(r.label)}: metric contract`} right={<span style={{ display: 'flex', gap: 6 }}>
      <AskButton text={`Explain ${String(r.label)} this month: value, threshold status and why it moved.`}>Ask</AskButton>
      <button className="btn small" onClick={onClose}>Close</button></span>}>
      <table className="pairs"><tbody>{items.map(([a, b]) => <tr key={a}><td style={{ width: 200 }}>{a}</td><td>{b}</td></tr>)}</tbody></table>
      <Recommend key={String(r.metric)} kind="kpi" subject={String(r.label)} label={r.status === 'green' ? 'Ask AI how to keep it green' : 'Recommend with AI'} />
    </Card>
  )
}

function ControlQueue() {
  const [q, setQ] = useState<Row | null>(null)
  const { go } = useWorkspace()
  useEffect(() => { fetch('/api/control-queue').then((r) => r.json()).then(setQ) }, [])
  if (!q) return <Card title="Unresolved variance and control queue"><div className="muted">Loading…</div></Card>
  const rows = q.rows as Row[]
  const open = (r: Row) => {
    if (r.type === 'Budget variance') location.hash = `budget?alert=${String(r.reference)}`
    else go(String(r.page) as Page)
  }
  return (
    <Card title="Unresolved variance and control queue" sub={`${rows.filter((r) => r.status === 'open').length} open · ${String(q.resolved)} resolved · every item has an owner, a threshold and an action · click to resolve it`}>
      <DataTable title="control_queue" rows={rows} onRow={open} pageSize={12} columns={[{ key: 'severity', chip: true }, { key: 'type', chip: true }, { key: 'reference' }, { key: 'description' }, { key: 'owner' },
        { key: 'amount', unit: 'usd' }, { key: 'age_days', label: 'Age (days)' }, { key: 'threshold' }, { key: 'action' }, { key: 'status', chip: true }, { key: 'resolution' }]} />
    </Card>
  )
}

function ContributionBridge() {
  const b = useTool('get_contribution_bridge')
  if (!b.data) return <Card title="Contribution-margin variance bridge"><Loading state={b} /></Card>
  const st = b.data.start as Row, en = b.data.end as Row, mp = b.data.margin_pct as Row
  const steps = (b.data.rows as Row[]).filter((x) => Math.abs(Number(x.amount)) >= 1).map((x) => ({ name: String(x.step).replace(' per hour', '/hr'), value: Number(x.amount) }))
  return (
    <Card title="Contribution-margin variance bridge" sub={`Last month → this month: volume, mix, price and each cost-to-serve component · margin ${pct(mp.prior)} → ${pct(mp.this)} · steps add up exactly`}>
      <div className="grid cols-2">
        <Bridge start={{ name: 'Last month', value: Number(st.amount) }} steps={steps} end={{ name: 'This month', value: Number(en.amount) }} height={300} />
        <div>
          <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>Customer × workload unit economics that moved contribution most · click a customer for detail</div>
          <DataTable rows={b.data.movers as Row[]} pageSize={8} columns={[{ key: 'customer_id' }, { key: 'workload', chip: true }, { key: 'contribution_margin', label: 'Contribution', unit: 'usd' }, { key: 'change', unit: 'usd' }, { key: 'contribution_margin_pct', label: 'CM %', unit: 'ratio' }, { key: 'cm_per_hour', label: 'CM / hour', render: (r) => (r.cm_per_hour == null ? '—' : `$${Number(r.cm_per_hour).toFixed(4)}`) }]} />
        </div>
      </div>
      <Source data={b.data} />
    </Card>
  )
}

function Sensitivity() {
  const m = useTool('get_margin_sensitivity')
  const r = useTool('get_runway_sensitivity')
  const cell = (v: unknown, base: number) => {
    const n = Number(v)
    const c = n >= base ? 'var(--good-soft)' : n >= base - 0.08 ? 'var(--warn-soft)' : 'var(--bad-soft)'
    return <span style={{ display: 'block', textAlign: 'center', background: c, borderRadius: 4, padding: '2px 0' }}>{pct(v)}</span>
  }
  const base = Number((m.data?.base as Row | undefined)?.contribution_margin_pct ?? 0.6)
  return (
    <div className="grid cols-2">
      <Card title="Margin sensitivity" sub={`Contribution margin % by price change (rows) and cost to serve per hour (columns) · today ${pct(base)}`}>
        {m.data ? <DataTable rows={m.data.rows} columns={Object.keys(m.data.rows[0] ?? {}).map((k) => (k === 'price_change'
          ? { key: k, label: 'Price', render: (x: Row) => `${Number(x[k]) > 0 ? '+' : ''}${Math.round(Number(x[k]) * 100)}%` }
          : { key: k, label: k, render: (x: Row) => cell(x[k], base) }))} /> : <Loading state={m} />}
      </Card>
      <Card title="Cash runway sensitivity" sub="Months until cash runs out with no new money, by NRR change and opex change (driver engine)">
        {r.data ? <DataTable rows={r.data.rows} columns={Object.keys(r.data.rows[0] ?? {}).map((k) => (k === 'nrr_change'
          ? { key: k, label: 'NRR change', render: (x: Row) => `${Number(x[k]) > 0 ? '+' : ''}${Math.round(Number(x[k]) * 100)} pts` }
          : { key: k, label: k, render: (x: Row) => <span style={{ color: typeof x[k] === 'number' && Number(x[k]) < 24 ? 'var(--bad)' : undefined }}>{String(x[k])} mo</span> }))} /> : <Loading state={r} />}
      </Card>
    </div>
  )
}
