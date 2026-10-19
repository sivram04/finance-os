// Contracts (committed revenue), driver bridges (why things moved) and the GPU / procurement efficiency cards on
// Tech spend. Each reads the same read-only tools the assistant uses.
import { Bars, Bridge, Columns, Dash, Donut, KpiRow, Trend, useFiltered } from '../components/Dash'
import { fmt, type Row } from '../api'
import { AskButton, Card, DataTable, Loading, Source, useTool, useWorkspace, type Page } from '../components/common'

const usd = (v: number) => fmt('amount', v, 'usd')
const signed = (v: number) => `${v >= 0 ? '+' : '−'}${usd(Math.abs(v))}`

function Head({ title, sub, ask }: { title: string; sub: string; ask: string }) {
  return (
    <div className="page-head">
      <div><h1>{title}</h1><p>{sub}</p></div>
      <AskButton text={ask}>Ask the assistant</AskButton>
    </div>
  )
}

// Contracts: what is owed under contract (RPO), what is due in 12 months (cRPO), contracted vs run-rate ARR, and
// which commitments are burning too slowly ahead of renewal.
export function Contracts() {
  return <Dash><ContractsBody /></Dash>
}

function ContractsBody() {
  const d = useTool('get_contracts')
  const all = (d.data?.rows ?? []) as Row[]
  const rows = useFiltered(all)
  const s = (d.data?.summary ?? {}) as Record<string, number>
  const trend = (d.data?.trend ?? []) as Row[]
  if (!d.data) return <div className="page"><Loading state={d} /></div>
  const gap = Number(s.run_rate_arr ?? 0) - Number(s.contracted_arr ?? 0)
  const paced = rows.map((r) => ({ ...r, pace: r.burn_pace == null ? 'n/a' : Number(r.burn_pace) < 0.9 ? 'Behind (< 90%)' : Number(r.burn_pace) > 1.1 ? 'Ahead (overage)' : 'On pace' }))
  return (
    <div className="page">
      <Head title="Contracts" sub={`What customers owe us under contract, and how fast they consume it · ${String(d.data.month)} · click a slice or bar to filter`}
        ask="Walk me through our contracted revenue: RPO and current RPO, contracted vs run-rate ARR, which commitments are behind pace before renewal, and the revenue at risk." />
      <KpiRow items={[
        { label: 'RPO', value: usd(s.rpo), note: `${s.contracts} active contracts`, title: 'Remaining performance obligations: commitments not yet consumed' },
        { label: 'Current RPO', value: usd(s.crpo), note: 'due in the next 12 months' },
        { label: 'Contracted ARR', value: usd(s.contracted_arr), note: `run-rate ARR ${usd(Number(s.run_rate_arr ?? 0))} · ${signed(gap)} uncommitted`, title: 'Committed minimums, annualized, vs annualized monthly revenue' },
        { label: 'Projected shortfall', value: usd(s.projected_shortfall), note: 'true-ups or expiring credits at year end', tone: s.projected_shortfall > 0 ? 'ok' : 'good' },
        { label: 'Projected overage', value: usd(s.projected_overage), note: 'usage above commitment at run rate', tone: 'good' },
        { label: 'Revenue at risk', value: usd(s.revenue_at_risk), note: `of ${usd(s.renewal_base_180d)} renewing in 180 days, burning below 90% of pace`, tone: s.revenue_at_risk > 0 ? 'bad' : 'good' },
      ]} />
      <div className="grid cols-3">
        <Card title="Contracted vs run-rate ARR" sub="Commitments under contract vs annualized monthly revenue">
          <Trend rows={trend} x="month" series={[{ key: 'run_rate_arr', label: 'Run-rate ARR', color: '#7a8699', dashed: true }, { key: 'contracted_arr', label: 'Contracted ARR' }]} />
        </Card>
        <Card title="RPO and current RPO" sub="By month end">
          <Trend rows={trend} x="month" series={[{ key: 'rpo', label: 'RPO' }, { key: 'crpo', label: 'Current RPO', color: '#2f9e6b' }]} />
        </Card>
        <Card title="Burn pace" sub="Usage vs commitment, year to date · 1.0 = on pace · click to filter">
          <Donut rows={paced} dim="pace" measure="current_commitment" colors={{ 'Behind (< 90%)': '#d1495b', 'On pace': '#2f9e6b', 'Ahead (overage)': '#3b6fd8' }} />
        </Card>
      </div>
      <div className="grid cols-2">
        <Card title="Commitment by billing model" sub="Committed usage billed monthly vs prepaid credit pools"><Bars rows={all} dim="billing_model" measure="current_commitment" /></Card>
        <Card title="RPO by segment"><Bars rows={all} dim="segment" measure="rpo" /></Card>
      </div>
      <Card title="Contracts" sub="Largest RPO first · renewal window = last 180 days">
        <DataTable title="contracts" rows={paced} columns={[{ key: 'contract_id' }, { key: 'customer_id' }, { key: 'billing_model', chip: true }, { key: 'end_date' },
          { key: 'contract_year', label: 'Year' }, { key: 'current_commitment', label: 'Commitment (year)', unit: 'usd' }, { key: 'consumed_ytd', label: 'Consumed', unit: 'usd' },
          { key: 'burn_pace', unit: 'ratio' }, { key: 'pace', chip: true }, { key: 'projected_shortfall', unit: 'usd' }, { key: 'projected_overage', unit: 'usd' },
          { key: 'rpo', label: 'RPO', unit: 'usd' }, { key: 'crpo', label: 'cRPO', unit: 'usd' }, { key: 'days_to_renewal', unit: 'days' }, { key: 'in_renewal_window', label: 'Renewal window', flag: 'warn' }]} />
        <Source data={d.data} />
      </Card>
    </div>
  )
}

// Drivers: bridges that explain the month: gross margin, net burn, cloud cost and headcount, plus magic number.
export function Drivers() {
  return <Dash><DriversBody /></Dash>
}

function steps(rows: Row[]) {
  const ordered = [...rows].sort((a, b) => Number(a.step_order) - Number(b.step_order))
  const first = ordered[0], last = ordered.at(-1)
  return first && last ? {
    start: { name: String(first.step), value: Number(first.amount) },
    steps: ordered.slice(1, -1).map((r) => ({ name: String(r.step), value: Number(r.amount) })),
    end: { name: String(last.step), value: Number(last.amount) },
  } : null
}

function DriversBody() {
  const d = useTool('get_driver_bridges')
  const g = useTool('get_gpu_efficiency')
  if (!d.data) return <div className="page"><Loading state={d} /></div>
  const gm = steps((d.data.gross_margin ?? []) as Row[]), burn = steps((d.data.net_burn ?? []) as Row[])
  const cloud = ((d.data.cloud_cost ?? []) as Row[]).find((r) => r.product_id === 'all')
  const hc = (d.data.headcount ?? []) as Row[]
  const hcSum = (k: string) => hc.reduce((a, r) => a + Number(r[k] ?? 0), 0)
  const magic = (g.data?.magic_number ?? []) as Row[]
  const lastMagic = magic.at(-1)
  return (
    <div className="page">
      <Head title="Drivers" sub={`Why did the numbers move? ${String(d.data.month)} vs the prior month · each bridge adds up (tested)`}
        ask="Explain this month's change in gross margin, net burn, cloud cost and headcount from the driver bridges, and what to do about the biggest driver." />
      <KpiRow items={[
        { label: 'Gross margin change', value: gm ? signed(gm.end.value - gm.start.value) : '—', note: gm ? `${usd(gm.start.value)} → ${usd(gm.end.value)}` : '', tone: gm && gm.end.value >= gm.start.value ? 'good' : 'bad' },
        { label: 'Net burn change', value: burn ? signed(burn.end.value - burn.start.value) : '—', note: burn ? `${usd(burn.start.value)} → ${usd(burn.end.value)}` : '', tone: burn && burn.end.value <= burn.start.value ? 'good' : 'bad' },
        { label: 'Cloud cost change', value: cloud ? signed(Number(cloud.closing) - Number(cloud.opening)) : '—', note: cloud ? `${usd(Number(cloud.opening))} → ${usd(Number(cloud.closing))}` : '' },
        { label: 'Headcount', value: String(hcSum('closing')), note: `+${hcSum('hires')} hires, −${hcSum('leavers')} leavers this month · ${hcSum('hires_ytd')} hires YTD` },
        { label: 'Magic number', value: lastMagic ? Number(lastMagic.magic_number).toFixed(2) : '—', note: 'new quarterly revenue x4 / prior-quarter S&M · 0.75+ efficient', tone: lastMagic ? (Number(lastMagic.magic_number) >= 0.75 ? 'good' : Number(lastMagic.magic_number) >= 0.5 ? 'ok' : 'bad') : null },
      ]} />
      <div className="grid cols-2">
        <Card title="Gross margin bridge" sub="Prior month → volume, price, cost to serve, services → this month">{gm ? <Bridge {...gm} /> : null}</Card>
        <Card title="Net burn bridge" sub="Positive steps add burn; negative steps reduce it">{burn ? <Bridge {...burn} /> : null}</Card>
      </div>
      <div className="grid cols-2">
        <Card title="Cloud and GPU cost bridge" sub="Demand (hours), efficiency (GPU time per hour), rate, shared pool, commitment">
          {cloud ? <Bridge start={{ name: 'Prior month', value: Number(cloud.opening) }} end={{ name: 'This month', value: Number(cloud.closing) }}
            steps={['demand', 'efficiency', 'rate', 'shared', 'commitment', 'other_cloud'].map((k) => ({ name: k.replace('_', ' ').replace(/^./, (c) => c.toUpperCase()), value: Number(cloud[k] ?? 0) }))} /> : null}
        </Card>
        <Card title="Magic number by quarter" sub="Sales efficiency · 0.75 line">
          <Trend rows={magic} x="month" unit="ratio" format={(v) => v.toFixed(2)} series={[{ key: 'magic_number', label: 'Magic number', color: '#8a63d2' }]} refs={[{ y: 0.75, label: '0.75' }]} />
        </Card>
      </div>
      <DriverTree />
      <Card title="Headcount bridge" sub="By department: opening + hires − leavers = closing">
        <DataTable rows={hc} columns={[{ key: 'department_id', label: 'Department' }, { key: 'opening', unit: 'count' }, { key: 'hires', unit: 'count' }, { key: 'leavers', unit: 'count' }, { key: 'closing', unit: 'count' }, { key: 'hires_ytd', label: 'Hires YTD', unit: 'count' }, { key: 'leavers_ytd', label: 'Leavers YTD', unit: 'count' }]} />
        <Source data={d.data} />
      </Card>
    </div>
  )
}

// On Tech spend: GPU idle time and commitment coverage, purchase commitments, procurement savings and anomalies.
export function SpendEfficiency() {
  const g = useTool('get_gpu_efficiency')
  const p = useTool('get_procurement')
  const a = useTool('get_cost_anomalies')
  if (!g.data || !p.data) return <Loading state={g.data ? p : g} />
  const gpu = (g.data.rows ?? []) as Row[]
  const h100 = gpu.filter((r) => r.gpu_type === 'H100')
  const ytd = (p.data.ytd ?? {}) as Record<string, number>
  const commits = (g.data.commitments ?? []) as Row[]
  return (
    <>
      <div className="grid cols-3">
        <Card title="Idle GPU share" sub="Warm-pool time no customer used, by GPU type">
          <Trend rows={h100} x="month" unit="ratio" format={(v) => `${(v * 100).toFixed(1)}%`} series={[{ key: 'idle_share', label: 'H100 idle share', color: '#d1495b' }]} />
        </Card>
        <Card title="Commitment coverage" sub="Committed / used H100 hours · below 100% = on-demand overage">
          <Trend rows={h100} x="month" unit="ratio" format={(v) => `${Math.round(v * 100)}%`} series={[{ key: 'commit_coverage', label: 'Coverage', color: '#3b6fd8' }]} refs={[{ y: 1, label: '100%' }]} />
        </Card>
        <Card title="Procurement savings" sub={`Rate cuts and early-pay discounts · ${usd(Number(ytd.total_savings ?? 0))} this year`}>
          <Columns rows={(p.data.rows ?? []) as Row[]} x="month" y="total_savings" color="#2f9e6b" />
        </Card>
      </div>
      <div className="grid cols-2">
        <Card title="Purchase commitments" sub="What we still owe vendors under contract">
          <DataTable rows={commits} columns={[{ key: 'vendor_id' }, { key: 'contract_id' }, { key: 'committed_gpu_type', label: 'GPU' }, { key: 'end_date' }, { key: 'months_remaining', unit: 'count' }, { key: 'committed_spend_month', label: 'Per month', unit: 'usd' }, { key: 'remaining_commitment', unit: 'usd' }]} />
        </Card>
        <Card title="Cost anomalies" sub="Days more than 3 standard deviations and $500 from the trailing 28 days">
          {a.data ? <DataTable rows={(a.data.rows ?? []) as Row[]} empty="No anomalies in the last 90 days." columns={[{ key: 'spend_date' }, { key: 'vendor_id' }, { key: 'service' }, { key: 'team' }, { key: 'cost', unit: 'usd' }, { key: 'expected', unit: 'usd' }, { key: 'z_score' }, { key: 'direction', chip: true }]} /> : <Loading state={a} />}
        </Card>
      </div>
    </>
  )
}

// CEO one-pager: the headline, then the five biggest opportunities and risks in dollars, each with an owner and a
// link to the page that explains it.
export function CeoOnePager() {
  const d = useTool('get_ceo_one_pager')
  const { go } = useWorkspace()
  if (!d.data) return <div className="page"><Loading state={d} /></div>
  const h = d.data.headline as Record<string, number | string | null>
  const n = (k: string) => Number(h[k] ?? 0)
  const list = (items: Row[], tone: string) => items.map((x, i) => (
    <div key={String(x.title)} className="onepager-item">
      <span className="rank">{i + 1}</span>
      <div>
        <div><b>{String(x.title)}</b> <span className="muted">· {String(x.owner)}</span></div>
        <div className="muted">{String(x.detail)} <a href={`#${String(x.page)}`} onClick={(e) => { e.preventDefault(); go?.(x.page as Page) }}>Open</a></div>
      </div>
      <span className="amt" style={{ color: tone }}>{usd(Number(x.amount))}</span>
    </div>
  ))
  return (
    <div className="page">
      <Head title="CEO one-pager" sub={`What to focus on · ${String(h.month)} closed · opportunities and risks ranked by dollars (annualized where monthly)`}
        ask="Give me the CEO one-pager: the headline, the top five opportunities and top five risks with owners, and what you would do first." />
      <KpiRow items={[
        { label: 'Revenue (month)', value: usd(n('revenue')), note: `run-rate ARR ${usd(n('arr'))}` },
        { label: 'Contracted ARR', value: usd(n('contracted_arr')), note: `RPO ${usd(n('rpo'))}` },
        { label: 'Gross margin', value: `${(n('gross_margin_pct') * 100).toFixed(1)}%`, note: `NRR ${(n('nrr') * 100).toFixed(0)}%` },
        { label: 'Net burn (month)', value: usd(n('net_burn')), note: `cash ${usd(n('closing_cash'))}`, tone: n('net_burn') > 0 ? 'ok' : 'good' },
        { label: 'EBITDA next 12 months', value: usd(n('ebitda_next_12m')), note: 'base scenario, driver engine', tone: n('ebitda_next_12m') >= 0 ? 'good' : 'bad' },
        { label: 'Runway (base)', value: h.runway_base == null ? '5+ years' : `${String(h.runway_base)} mo`, note: 'no new money', tone: h.runway_base == null ? 'good' : 'bad' },
      ]} />
      <div className="grid cols-2">
        <Card title="Top 5 opportunities" sub="Upside in dollars a year">{list((d.data.opportunities ?? []) as Row[], 'var(--good)')}</Card>
        <Card title="Top 5 risks" sub="Exposure in dollars">{list((d.data.risks ?? []) as Row[], 'var(--bad)')}</Card>
      </div>
      <Source data={d.data} />
    </div>
  )
}

// The value driver tree: EBITDA broken into the operating drivers that move it, this month vs last.
export function DriverTree() {
  const d = useTool('get_driver_tree')
  if (!d.data) return <Card title="Driver tree"><Loading state={d} /></Card>
  const rows = (d.data.rows ?? []) as Row[]
  const show = (r: Row, k: string) => {
    const v = Number(r[k])
    return r.unit === 'usd' ? usd(v) : r.unit === 'price' ? `$${v.toFixed(4)}` : v.toLocaleString(undefined, { maximumFractionDigits: 1 })
  }
  const maxPct = Math.max(...rows.map((r) => Math.abs(Number(r.change_pct ?? 0))), 0.01)
  const costs = new Set(['cost_of_revenue', 'usage_cost', 'cost_per_hour', 'other_cost_of_revenue', 'opex', 'payroll', 'headcount', 'cost_per_head', 'other_opex'])
  return (
    <Card title="Driver tree" sub={`EBITDA and the drivers under it · ${String(d.data.month)} vs ${String(d.data.prior_month)} · green helps EBITDA, red hurts`}>
      <div className="tree-row head"><span>Driver</span><span>This month</span><span>Prior</span><span>Change</span><span>Change %</span></div>
      {rows.map((r) => {
        const pct = Number(r.change_pct ?? 0)
        const good = costs.has(String(r.node)) ? pct <= 0 : pct >= 0
        return (
          <div key={String(r.node)} className="tree-row">
            <span style={{ paddingLeft: Number(r.depth) * 16, fontWeight: Number(r.depth) < 2 ? 600 : 400 }}>{String(r.label)}</span>
            <span>{show(r, 'value')}</span>
            <span className="muted">{show(r, 'prior')}</span>
            <span>{r.unit === 'usd' ? signed(Number(r.change)) : show(r, 'change')}</span>
            <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span className="tree-bar" style={{ width: `${Math.round((Math.abs(pct) / maxPct) * 60)}px`, background: good ? 'var(--good)' : 'var(--bad)' }} />
              {r.change_pct == null ? '—' : `${(pct * 100).toFixed(1)}%`}
            </span>
          </div>
        )
      })}
      <Source data={d.data} />
    </Card>
  )
}
