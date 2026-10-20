// Module pages. Each reads the same read-only tools the assistant uses, so both always show the same numbers.
import { useMemo, useState } from 'react'
import { Bars, Bridge, Columns, Dash, Donut, GroupedBars, KpiRow, Trend, useFiltered } from '../components/Dash'
import { fmt, type Row } from '../api'
import { AskButton, Card, Chip, DataTable, Loading, Source, useTool, useWorkspace } from '../components/common'
import { SpendEfficiency } from './Insights'
import { VarianceCase } from '../components/VarianceCase'

function Head({ title, sub, ask }: { title: string; sub: string; ask: string }) {
  return (
    <div className="page-head">
      <div><h1>{title}</h1><p>{sub}</p></div>
      <AskButton text={ask}>Ask the assistant</AskButton>
    </div>
  )
}

// Revenue & margins: which customers make money? Whale curve: customers sorted by gross margin, cumulative
// share of total gross margin (Pragmatic Institute, Tempo). Above 100% means the tail loses money.
export function Revenue() {
  return <Dash><RevenueBody /></Dash>
}

function RevenueBody() {
  const ue = useTool('get_unit_economics')
  const mv = useTool('get_revenue_movements')
  const { ask } = useWorkspace()
  const all = (ue.data?.rows ?? []) as Row[]
  const rows = useFiltered(all)
  const sum = (rs: Row[], k: string) => rs.reduce((a, r) => a + Number(r[k] ?? 0), 0)
  const usd = (v: number) => fmt('amount', v, 'usd')
  const rev = sum(rows, 'revenue'), gm = sum(rows, 'gross_margin'), cm = sum(rows, 'contribution_margin')
  const below = rows.filter((r) => r.is_below_floor)
  const sorted = [...rows].sort((a, b) => Number(b.gross_margin) - Number(a.gross_margin))
  let run = 0
  const whale = [{ pct: 0, cum: 0 }, ...sorted.map((r, i) => { run += Number(r.gross_margin); return { pct: ((i + 1) / sorted.length) * 100, cum: gm ? run / gm : 0 } })]
  const top20 = whale[Math.max(1, Math.ceil(sorted.length * 0.2))]?.cum ?? 0
  const losing = rows.filter((r) => Number(r.contribution_margin) < 0)
  const b = mv.data?.rows[0]
  if (!ue.data) return <div className="page"><Loading state={ue} /></div>
  return (
    <div className="page">
      <Head title="Revenue & margins" sub={`Which customers make money? ${String(ue.data.month ?? '')} · click a segment or customer to filter`}
        ask="Which customers make and lose money, why (pricing, product mix, cost to serve), and what should we do about the tail?" />
      <KpiRow items={[
        { label: 'Revenue', value: usd(rev), note: `${rows.length} customers` },
        { label: 'Gross margin', value: rev ? `${((gm / rev) * 100).toFixed(1)}%` : '—', note: usd(gm), tone: rev && gm / rev >= 0.62 ? 'good' : 'bad', title: 'Usage-priced SaaS median 62% (Aleph x Benchmarkit 2026)' },
        { label: 'Contribution margin', value: rev ? `${((cm / rev) * 100).toFixed(1)}%` : '—', note: 'after payment fees, support and success' },
        { label: 'Top 20% of customers', value: `${Math.round(top20 * 100)}%`, note: 'of all gross margin', tone: top20 > 1 ? 'bad' : null },
        { label: 'Below margin floor', value: String(below.length), note: `${usd(sum(below, 'revenue'))} of revenue`, tone: below.length ? 'bad' : 'good' },
        { label: 'Losing money', value: String(losing.length), note: `contribution ${usd(sum(losing, 'contribution_margin'))}`, tone: losing.length ? 'bad' : 'good' },
      ]} />
      <div className="grid cols-3">
        <Card title="Where the profit comes from" sub="Cumulative share of gross margin, customers sorted best to worst">
          <Trend rows={whale} x="pct" unit="ratio" format={(v) => `${Math.round(v * 100)}%`} xTicks={[0, 20, 40, 60, 80, 100]} xFormat={(v) => `${Math.round(v)}%`} xLabel="Customers, most profitable first" yLabel="Share of gross margin" series={[{ key: 'cum', label: 'Cumulative gross margin', color: '#2f9e6b' }]} refs={[{ y: 1, label: '100%' }]} />
        </Card>
        <Card title="Revenue by segment" sub="Click to filter"><Donut rows={all} dim="segment" measure="revenue" /></Card>
        <Card title="Contribution by customer" sub="Largest gains and losses · click to filter">
          <Bars rows={all} dim="customer_id" measure="contribution_margin" signed top={10} />
        </Card>
      </div>
      <div className="grid cols-2">
        <Card title="How MRR moved" sub={mv.data ? `${String(mv.data.month)}: opening to closing (company-wide)` : ''}>
          {b ? <Bridge start={{ name: 'Opening', value: Number(b.opening_mrr) }} end={{ name: 'Closing', value: Number(b.closing_mrr) }}
            steps={[{ name: 'New', value: Number(b.new_mrr) }, { name: 'Expansion', value: Number(b.expansion_mrr) }, { name: 'Reactivation', value: Number(b.reactivation_mrr) },
              { name: 'Contraction', value: Number(b.contraction_mrr) }, { name: 'Churn', value: Number(b.churned_mrr) }]} /> : <Loading state={mv} />}
        </Card>
        <Card title="Cost to serve by product" sub="Company-wide">
          <DataTable rows={(ue.data.by_product ?? []) as Row[]} columns={[{ key: 'product_id' }, { key: 'revenue', unit: 'usd' }, { key: 'cogs', unit: 'usd' }, { key: 'gross_margin_pct', unit: 'ratio' }, { key: 'cost_to_serve_per_hour', label: 'Cost / audio hour', render: (r) => `$${(r.cost_to_serve_per_hour as number).toFixed(4)}` }]} />
        </Card>
      </div>
      <Card title="Customers" sub="Lowest margin first · click a row to ask about it">
        <DataTable title="customer_margins" rows={all} onRow={(r) => ask(`Explain ${r.customer_id}'s margin this month.`)} columns={[
          { key: 'customer_id' }, { key: 'segment', chip: true }, { key: 'revenue', unit: 'usd' }, { key: 'gross_margin_pct', unit: 'ratio' },
          { key: 'gross_margin_floor_pct', label: 'Floor', unit: 'ratio' }, { key: 'contribution_margin', unit: 'usd' }, { key: 'is_below_floor', label: 'Below floor', flag: 'bad' }]} />
        <Source data={ue.data} />
      </Card>
      <Card title="Biggest movers" sub="Company-wide · this month">
        {mv.data ? <DataTable rows={mv.data.biggest_movers as Row[]} columns={[{ key: 'customer_id' }, { key: 'movement', chip: true }, { key: 'prior_revenue', unit: 'usd' }, { key: 'revenue', unit: 'usd' }, { key: 'revenue_change', unit: 'usd' }]} /> : <Loading state={mv} />}
      </Card>
    </div>
  )
}

export function Spend() {
  return <Dash><SpendBody /></Dash>
}

function SpendBody() {
  const d = useTool('get_spend_dashboard', { months: 12 })
  const all = (d.data?.rows ?? []) as Row[]
  const rows = useFiltered(all)
  const trend = (d.data?.trend ?? []) as Row[]
  const cap = ((d.data?.capacity ?? []) as Row[]).filter((r) => r.gpu_type === 'H100')
  const last = trend.at(-1), prev = trend.at(-2), lastCap = cap.at(-1)
  const total = rows.reduce((a, r) => a + Number(r.cost), 0)
  const tagged = rows.filter((r) => r.tagging === 'tagged').reduce((a, r) => a + Number(r.cost), 0)
  const fc = ((d.data?.forecast ?? []) as Row[])[0]
  const contracts = (d.data?.contracts ?? []) as Row[]
  const usd = (v: number) => fmt('amount', v, 'usd')
  const pctc = (a?: number, b?: number) => (a != null && b ? `${((a / b - 1) * 100).toFixed(1)}%` : '—')
  const util = lastCap ? Number(lastCap.commit_utilization_pct) : null
  if (!d.data) return <div className="page"><Loading state={d} /></div>
  return (
    <div className="page">
      <Head title="Tech spend" sub={`Is spend under control relative to usage? ${String(d.data.month)} · click a slice or bar to filter`}
        ask="Is our GPU and cloud spend under control? Cover unit cost per audio hour, commitment use, who is spending and the renewal decision." />
      <KpiRow items={[
        { label: 'Spend this month', value: usd(total), note: last && prev ? `${pctc(Number(last.cost), Number(prev.cost))} vs last month` : '' },
        { label: 'Cost per audio hour', value: last ? `$${Number(last.cost_per_hour).toFixed(4)}` : '—', note: last && prev ? `${pctc(Number(last.cost_per_hour), Number(prev.cost_per_hour))} vs last month` : '', tone: last && prev && Number(last.cost_per_hour) > Number(prev.cost_per_hour) * 1.03 ? 'bad' : 'good', title: 'Company-wide' },
        { label: 'H100 commit utilization', value: util != null ? `${Math.round(util * 100)}%` : '—', note: util != null ? (util > 1 ? 'usage above commitment: overage at on-demand rate' : 'target 80%+') : '', tone: util == null ? null : util < 0.7 ? 'bad' : util < 0.8 ? 'ok' : 'good' },
        { label: 'Unused commitment', value: usd(Number(lastCap?.shortfall_cost ?? 0)), note: 'paid for, not used, this month', tone: Number(lastCap?.shortfall_cost ?? 0) > 0 ? 'bad' : 'good' },
        { label: 'Tagging coverage', value: total ? `${((tagged / total) * 100).toFixed(1)}%` : '—', note: `${usd(total - tagged)} untagged`, tone: total && tagged / total < 0.95 ? 'bad' : 'good' },
        { label: 'Next month forecast', value: fc ? usd(Number(fc.forecast)) : '—', note: fc ? `${String(fc.month)} · ${pctc(Number(fc.forecast), total)} vs this month` : '' },
      ]} />
      <div className="grid cols-3">
        <Card title="By vendor"><Donut rows={all} dim="vendor_id" measure="cost" /></Card>
        <Card title="By team" sub="Who owns the spend"><Bars rows={all} dim="team" measure="cost" /></Card>
        <Card title="By model" sub="Which product drives GPU cost"><Bars rows={all} dim="model" measure="cost" /></Card>
      </div>
      <div className="grid cols-3">
        <Card title="Is spend growing faster than usage?" sub="Cost per audio hour by month (company-wide)">
          <Trend rows={trend} x="month" unit="usd" format={(v) => `$${v.toFixed(3)}`} series={[{ key: 'cost_per_hour', label: 'Cost / audio hour' }]} />
        </Card>
        <Card title="H100 commitment use" sub="Used hours as % of committed · 80% target">
          <Trend rows={cap} x="month" unit="ratio" format={(v) => `${Math.round(v * 100)}%`} series={[{ key: 'commit_utilization_pct', label: 'Utilization', color: '#8a63d2' }]} refs={[{ y: 0.8, label: '80% target' }, { y: 1, label: '100%' }]} />
        </Card>
        <Card title="Spend and forecast" sub="Actual by month, then the 3-month forecast">
          <Columns rows={[...trend.map((t) => ({ month: t.month, amount: t.cost })), ...((d.data.forecast ?? []) as Row[]).map((f) => ({ month: `${f.month} (f)`, amount: f.forecast }))]} x="month" y="amount" />
        </Card>
      </div>
      <SpendEfficiency />
      <Card title="Vendor contracts" sub="Renewal flagged inside the notice period plus 30 days">
        <DataTable rows={contracts} columns={[{ key: 'vendor_name' }, { key: 'contract_id' }, { key: 'committed_gpu_type', label: 'GPU' }, { key: 'committed_gpu_hours_month', label: 'Committed h / month', unit: 'count' },
          { key: 'end_date' }, { key: 'days_to_end', unit: 'count' }, { key: 'avg_monthly_spend_t3m', label: 'Avg monthly spend (3m)', unit: 'usd' }, { key: 'is_renewal_due', label: 'Renewal due', flag: 'warn' }]} />
      </Card>
      <Card title="Spend lines" sub="This month, filtered with the page">
        <DataTable title="tech_spend" rows={all} columns={[{ key: 'vendor_id' }, { key: 'team' }, { key: 'category', chip: true }, { key: 'model' }, { key: 'tagging', chip: true }, { key: 'cost', unit: 'usd' }]} />
        <Source data={d.data} />
      </Card>
    </div>
  )
}

// Budget vs actual (docs/dashboard_spec.md section 2): are we on plan, and why not? Variances are signed so
// positive is always favorable (revenue above budget, costs below).
export function Budget() {
  return <Dash><BudgetBody /></Dash>
}

function BudgetBody() {
  const s = useTool('get_budget_dashboard')
  const [alert, setAlert] = useState<string | null>(() => new URLSearchParams(location.hash.split('?')[1] ?? '').get('alert'))
  useWorkspace()
  const all = (s.data?.rows ?? []) as Row[]
  const rows = useFiltered(all)
  const sum = (rs: Row[], k: string) => rs.reduce((a, r) => a + Number(r[k] ?? 0), 0)
  const rev = rows.filter((r) => r.account_type === 'revenue'), cost = rows.filter((r) => r.account_type !== 'revenue')
  const ebitdaA = sum(rev, 'actual') - sum(cost.filter((r) => r.account_id !== '6600'), 'actual')
  const ebitdaB = sum(rev, 'budget') - sum(cost.filter((r) => r.account_id !== '6600'), 'budget')
  const usd = (v: number) => fmt('amount', v, 'usd')
  const signed = (v: number) => `${v >= 0 ? '+' : '−'}${usd(Math.abs(v))}`
  const tone = (v: number, base: number) => (Math.abs(v) < Math.abs(base) * 0.02 ? 'ok' : v >= 0 ? 'good' : 'bad') as 'ok' | 'good' | 'bad'
  const byRollup = Object.entries(rows.filter((r) => r.account_id !== '6600').reduce<Record<string, number>>((a, r) => {
    const k = String(r.rollup); a[k] = (a[k] ?? 0) + Number(r.fav_variance); return a }, {})).map(([name, value]) => ({ name, value }))
    .sort((a, b) => (a.name === 'Revenue' ? -1 : b.name === 'Revenue' ? 1 : Math.abs(b.value) - Math.abs(a.value)))
    // the four largest steps by size, the rest as one "Other" step, so the bridge stays readable
    .reduce<{ name: string; value: number }[]>((acc, st, i) => (i < 5 ? [...acc, st] : (acc.at(-1)?.name === 'Other' ? (acc.at(-1)!.value += st.value, acc) : [...acc, { name: 'Other', value: st.value }])), [])
  if (!s.data) return <div className="page"><Loading state={s} /></div>
  return (
    <div className="page">
      <Head title="Budget vs. actual" sub={`Are we on plan, and why not? ${String(s.data.month)} · green is favorable for revenue and costs alike · click a bar to filter`}
        ask="Where are we off budget this month, year to date and for the full year, and what is driving it? Give owners and actions." />
      <KpiRow items={[
        { label: 'Revenue vs budget', value: signed(sum(rev, 'fav_variance')), note: `${usd(sum(rev, 'actual'))} vs ${usd(sum(rev, 'budget'))}`, tone: tone(sum(rev, 'fav_variance'), sum(rev, 'budget')) },
        { label: 'Costs vs budget', value: signed(sum(cost, 'fav_variance')), note: `${usd(sum(cost, 'actual'))} vs ${usd(sum(cost, 'budget'))}`, tone: tone(sum(cost, 'fav_variance'), sum(cost, 'budget')) },
        { label: 'EBITDA vs budget', value: signed(ebitdaA - ebitdaB), note: `${usd(ebitdaA)} vs ${usd(ebitdaB)}`, tone: tone(ebitdaA - ebitdaB, ebitdaB || 1) },
        { label: 'Year to date', value: signed(sum(rows, 'ytd_fav_variance')), note: 'all lines, favorable +', tone: sum(rows, 'ytd_fav_variance') >= 0 ? 'good' : 'bad' },
        { label: 'Full-year forecast vs budget', value: signed(sum(rows, 'fy_fav_variance')), note: 'where the year lands at the current run rate', tone: sum(rows, 'fy_fav_variance') >= 0 ? 'good' : 'bad' },
        { label: 'Variances to explain', value: String(rows.filter((r) => r.is_alert).length), note: 'beyond the materiality threshold', tone: rows.some((r) => r.is_alert) ? 'bad' : 'good' },
      ]} />
      <div className="grid cols-2">
        <Card title="From budget to actual EBITDA" sub="Each step is a line's favorable (+) or unfavorable (−) variance">
          <Bridge start={{ name: 'Budget EBITDA', value: ebitdaB }} steps={byRollup} end={{ name: 'Actual EBITDA', value: ebitdaA }} />
        </Card>
        <Card title="Variance by department" sub="Favorable + / unfavorable − · click a department to filter">
          <Bars rows={all} dim="department" measure="fav_variance" signed top={10} valueFormat={signed} />
        </Card>
      </div>
      <div className="grid cols-2">
        <Card title="Is it a trend or a one-off?" sub="EBITDA, actual vs budget, by month (company-wide)">
          <Trend rows={(s.data.trend ?? []) as Row[]} x="month" series={[{ key: 'ebitda_actual', label: 'Actual' }, { key: 'ebitda_budget', label: 'Budget', color: '#7a8699', dashed: true }]} refs={[{ y: 0, label: 'breakeven' }]} />
        </Card>
        <Card title="Revenue, actual vs budget" sub="By month (company-wide)">
          <Trend rows={(s.data.trend ?? []) as Row[]} x="month" series={[{ key: 'revenue_actual', label: 'Actual', color: '#2f9e6b' }, { key: 'revenue_budget', label: 'Budget', color: '#7a8699', dashed: true }]} />
        </Card>
      </div>
      <Card title="Lines by variance" sub="Largest first · owners are department heads · click a material variance for its full case: source data, reconciliation, root cause, owner, action and the CFO decision"
        right={<button className="btn small" onClick={() => { const top = [...all].filter((r) => r.alert_id).sort((a, b) => Math.abs(Number(b.fav_variance)) - Math.abs(Number(a.fav_variance)))[0]; if (top) setAlert(String(top.alert_id)) }}>Open the largest variance</button>}>
        <DataTable title="budget_vs_actual" rows={all} onRow={(r) => r.alert_id && setAlert(String(r.alert_id))} columns={[
          { key: 'department' }, { key: 'owner' }, { key: 'account_name' }, { key: 'actual', unit: 'usd' }, { key: 'budget', unit: 'usd' },
          { key: 'fav_variance', label: 'Variance (fav +)', render: (r) => <span style={{ color: (r.fav_variance as number) >= 0 ? 'var(--good)' : 'var(--bad)' }}>{signed(r.fav_variance as number)}</span> },
          { key: 'variance_pct', unit: 'ratio' }, { key: 'fy_fav_variance', label: 'Full year (fav +)', render: (r) => signed(r.fy_fav_variance as number) },
          { key: 'direction', chip: true }, { key: 'is_alert', label: 'To explain', flag: 'bad' }, { key: 'commentary_status', label: 'Commentary', chip: true }]} />
        <Source data={s.data} />
      </Card>
      {alert && <VarianceCase alertId={alert} onClose={() => setAlert(null)} />}
    </div>
  )
}

// Projects (docs/dashboard_spec.md section 6): which projects lose money or cash?
export function Projects() {
  return <Dash><ProjectsBody /></Dash>
}

function ProjectsBody() {
  const d = useTool('get_projects_dashboard')
  const { ask } = useWorkspace()
  const all = (d.data?.rows ?? []) as Row[]
  const rows = useFiltered(all)
  const sum = (k: string) => rows.reduce((a, r) => a + Number(r[k] ?? 0), 0)
  const usd = (v: number) => fmt('amount', v, 'usd')
  const funding = ((d.data?.funding ?? []) as Row[]).filter((f) => f.clin_id === 'TOTAL')
  const fundingAll = (d.data?.funding ?? []) as Row[]
  if (!d.data) return <div className="page"><Loading state={d} /></div>
  return (
    <div className="page">
      <Head title="Projects" sub="Which projects lose money or cash? Estimate at completion, earned vs billed, and federal funding · click a project or type to filter"
        ask="Which projects are at risk (budget, unbilled work, funding) and what should we do about each?" />
      <KpiRow items={[
        { label: 'Contract value', value: usd(sum('contract_value')), note: `${rows.length} projects` },
        { label: 'Forecast overrun', value: usd(-sum('variance_at_completion')), note: 'EAC above budget, all projects', tone: sum('variance_at_completion') < 0 ? 'bad' : 'good' },
        { label: 'Over budget', value: String(rows.filter((r) => r.is_over_budget).length), note: 'projects with EAC > budget', tone: rows.some((r) => r.is_over_budget) ? 'bad' : 'good' },
        { label: 'Unbilled WIP', value: usd(sum('unbilled')), note: 'earned, not yet invoiced', tone: sum('unbilled') > 20000 ? 'bad' : 'ok' },
        { label: 'Billed ahead', value: usd(sum('deferred')), note: 'invoiced, not yet earned' },
        { label: 'Funding notices', value: String(funding.filter((f) => f.is_funding_alert_75).length), note: 'contracts past 75% of funding', tone: funding.some((f) => f.is_funding_alert_90) ? 'bad' : funding.some((f) => f.is_funding_alert_75) ? 'ok' : 'good' },
      ]} />
      <div className="grid cols-3">
        <Card title="Estimate at completion vs budget" sub="Over 100% loses money against plan">
          <Bars rows={all} dim="project_id" measure="eac_pct_of_budget" valueFormat={(v) => `${Math.round(v * 100)}%`} refX={[{ x: 1, label: '100%' }]} />
        </Card>
        <Card title="Earned vs billed" sub="Earned above billed = cash not invoiced yet">
          <GroupedBars rows={all} dim="project_id" series={[{ key: 'earned_to_date', label: 'Earned', color: '#2f9e6b' }, { key: 'billed_to_date', label: 'Billed', color: '#3b6fd8' }]} />
        </Card>
        <Card title="Contract value by type" sub="Fixed fee carries the overrun risk"><Donut rows={all} dim="project_type" measure="contract_value" /></Card>
      </div>
      <div className="grid cols-2">
        <Card title="Federal funding used" sub="Limitation of Funds notices at 75% and 90%">
          <Bars rows={funding} dim="contract_id" measure="funding_used_pct" valueFormat={(v) => `${Math.round(v * 100)}%`} refX={[{ x: 0.75, label: '75%' }, { x: 0.9, label: '90%' }]} />
        </Card>
        <Card title="Exceptions" sub="Unbilled milestones, rate mismatches, bills without PO">
          <DataTable rows={(d.data.exceptions ?? []) as Row[]} empty="No exceptions." columns={[{ key: 'exception_type', chip: true }, { key: 'project_id' }, { key: 'amount', unit: 'usd' }, { key: 'detail' }]} />
        </Card>
      </div>
      <Card title="Projects" sub="Click a project to ask about it">
        <DataTable title="projects" rows={all} onRow={(r) => ask(`What's the status of ${r.project_id} and what should we do about it?`)} columns={[
          { key: 'project_id' }, { key: 'project_name' }, { key: 'project_type', chip: true }, { key: 'customer_id' }, { key: 'contract_value', unit: 'usd' },
          { key: 'budget', unit: 'usd' }, { key: 'eac', label: 'EAC', unit: 'usd' }, { key: 'pct_complete', unit: 'ratio' }, { key: 'forecast_margin_pct', label: 'Forecast margin', unit: 'ratio' },
          { key: 'unbilled', unit: 'usd' }, { key: 'billing_position', chip: true }, { key: 'is_over_budget', label: 'Over budget', flag: 'bad' }]} />
        <Source data={d.data} />
      </Card>
      <Card title="Funding by CLIN" sub="Ceiling, funded and billed per contract line item">
        <DataTable rows={fundingAll.filter((f) => f.clin_id !== 'TOTAL')} empty="No CLINs." columns={[{ key: 'contract_id' }, { key: 'clin_id', label: 'CLIN' }, { key: 'ceiling', unit: 'usd' }, { key: 'funded', unit: 'usd' }, { key: 'billed_to_date', unit: 'usd' }, { key: 'funding_remaining', unit: 'usd' }, { key: 'funding_used_pct', unit: 'ratio' }, { key: 'is_funding_alert_75', label: '75% notice', flag: 'warn' }]} />
      </Card>
    </div>
  )
}

// Billing: are we invoicing everything we earned, correctly and on time? (invoice accuracy, leakage, unbilled time)
export function Billing() {
  return <Dash><BillingBody /></Dash>
}

function BillingBody() {
  const s = useTool('get_billing_status')
  const all = (s.data?.rows ?? []) as Row[]
  const run = (s.data?.next_billing_run ?? []) as Row[]
  const ex = (s.data?.validation_exceptions ?? []) as Row[]
  const rows = useFiltered(all), frun = useFiltered(run), fex = useFiltered(ex)
  const sum = (rs: Row[], k: string) => rs.reduce((a, r) => a + Number(r[k] ?? 0), 0)
  const usd = (v: number) => fmt('amount', v, 'usd')
  const billed = sum(rows, 'billed_total')
  const atRisk = sum(fex, 'amount_at_risk')
  if (!s.data) return <div className="page"><Loading state={s} /></div>
  return (
    <div className="page">
      <Head title="Billing" sub="Are we invoicing everything we earned, correctly and on time? Click a project or item type to filter"
        ask="What is ready to bill, what is blocked, which invoices have errors, and how much revenue is leaking?" />
      <KpiRow items={[
        { label: 'Ready to bill', value: usd(sum(rows, 'ready_to_bill')), note: `${frun.length} items in the next run` },
        { label: 'Oldest unbilled', value: `${Math.max(0, ...rows.map((r) => Number(r.oldest_unbilled_days ?? 0)))} d`, note: 'earned but not invoiced', tone: rows.some((r) => r.has_unbilled_alert) ? 'bad' : 'good' },
        { label: 'Unbilled alerts', value: String(rows.filter((r) => r.has_unbilled_alert).length), note: 'projects past the billing window', tone: rows.some((r) => r.has_unbilled_alert) ? 'bad' : 'good' },
        { label: 'Invoice accuracy', value: billed ? `${(100 - (atRisk / billed) * 100).toFixed(1)}%` : '—', note: 'billed value without a validation error · 98%+ target', tone: billed && atRisk / billed > 0.02 ? 'bad' : 'good' },
        { label: 'At risk on issued invoices', value: usd(atRisk), note: `${fex.length} validation exceptions`, tone: atRisk ? 'bad' : 'good' },
        { label: 'Open AR on projects', value: usd(sum(rows, 'open_ar')) },
      ]} />
      <div className="grid cols-3">
        <Card title="Ready to bill by project" sub="Click to filter"><Bars rows={all} dim="project_id" measure="ready_to_bill" /></Card>
        <Card title="Next run by item type" sub="Milestones, time and materials, expenses"><Donut rows={run} dim="item_type" measure="amount" /></Card>
        <Card title="Billing status" sub="Projects by status"><Donut rows={all} dim="billing_status" /></Card>
      </div>
      <Card title="Projects">
        <DataTable title="billing_status" rows={all} columns={[{ key: 'project_id' }, { key: 'project_name' }, { key: 'billing_status', label: 'Status', chip: true }, { key: 'billed_total', unit: 'usd' }, { key: 'open_ar', unit: 'usd' }, { key: 'ready_to_bill', unit: 'usd' }, { key: 'oldest_unbilled_days', unit: 'count' }, { key: 'has_unbilled_alert', label: 'Unbilled alert', flag: 'bad' }]} />
        <Source data={s.data} />
      </Card>
      <div className="grid cols-2">
        <Card title="Next billing run (drafts)">
          <DataTable rows={run} columns={[{ key: 'project_id' }, { key: 'item_type', chip: true }, { key: 'reference' }, { key: 'amount', unit: 'usd' }, { key: 'days_unbilled', unit: 'count' }, { key: 'validation_status', label: 'Validation', chip: true }]} />
        </Card>
        <Card title="Validation exceptions on issued invoices" sub="Rate or hours that don't match the contract">
          <DataTable rows={ex} empty="No exceptions." columns={[{ key: 'exception_type', chip: true }, { key: 'project_id' }, { key: 'invoice_id' }, { key: 'detail' }, { key: 'amount_at_risk', unit: 'usd' }]} />
        </Card>
      </div>
    </div>
  )
}

const BUCKETS = ['current', '1-30', '31-60', '61-90', '90+']
const BUCKET_COLORS: Record<string, string> = { current: '#2f9e6b', '1-30': '#9bbf4a', '31-60': '#c98a1b', '61-90': '#e07a3a', '90+': '#d1495b' }

// Receivables (docs/dashboard_spec.md section 1): will the cash come in, and who do we chase?
export function AR() {
  return <Dash><ARBody /></Dash>
}

function ARBody() {
  const d = useTool('get_receivables_dashboard')
  const ex = useTool('get_ar_exceptions')
  const { ask } = useWorkspace()
  const all = useMemo(() => ((d.data?.rows ?? []) as Row[]).map((r) => ({ ...r, due_status: (r.days_past_due as number) > 0 ? 'past_due' : 'not_yet_due' })), [d.data])
  const rows = useFiltered(all)
  const trend = (d.data?.trend ?? []) as Row[]
  const last = trend.at(-1)
  const cei3 = trend.slice(-3).reduce((a, r) => a + (r.cei as number), 0) / Math.max(1, trend.slice(-3).length)
  const open = rows.reduce((a, r) => a + (r.balance as number), 0)
  const late = rows.filter((r) => (r.days_past_due as number) > 0)
  const lateAmt = late.reduce((a, r) => a + (r.balance as number), 0)
  const disputed = rows.filter((r) => r.is_disputed).reduce((a, r) => a + (r.balance as number), 0)
  const addDays = lateAmt ? late.reduce((a, r) => a + (r.balance as number) * (r.days_past_due as number), 0) / lateAmt : 0
  const usd = (v: number) => fmt('amount', v, 'usd')
  if (!d.data) return <div className="page"><Loading state={d} /></div>
  return (
    <div className="page">
      <Head title="Receivables" sub="Will the cash come in, and who do we chase? Click any slice or bar to filter the page."
        ask="Walk me through receivables like a controller: what is late, who to chase first, what is blocked, and when the cash lands." />
      <KpiRow items={[
        { label: 'Open AR', value: usd(open), note: `${rows.length} open invoices` },
        { label: 'Past due', value: usd(lateAmt), note: `${open ? ((lateAmt / open) * 100).toFixed(1) : 0}% of open AR · ${late.length} invoices`, tone: open && lateAmt / open > 0.15 ? 'bad' : lateAmt ? 'ok' : 'good' },
        { label: 'DSO (last closed month)', value: last ? `${(last.dso_days as number).toFixed(1)} d` : '—', note: last ? `best possible ${last.best_possible_dso} d · terms 30-45 d` : '', tone: last && (last.dso_days as number) > 60 ? 'bad' : 'ok', title: 'Company-wide, at month end; page filters do not change it' },
        { label: 'CEI (3 months)', value: `${(cei3 * 100).toFixed(1)}%`, note: 'share of collectible AR collected · 80%+ good', tone: cei3 >= 0.8 ? 'good' : cei3 >= 0.7 ? 'ok' : 'bad', title: 'Company-wide' },
        { label: 'Days delinquent', value: `${addDays.toFixed(0)} d`, note: 'balance-weighted, past-due invoices', tone: addDays > 30 ? 'bad' : addDays > 0 ? 'ok' : 'good' },
        { label: 'Disputed', value: usd(disputed), note: 'not chased until resolved', tone: disputed ? 'bad' : 'good' },
      ]} />
      <div className="grid cols-3">
        <Card title="Open AR by age" sub="How late the money is"><Donut rows={all} dim="aging_bucket" measure="balance" order={BUCKETS} colors={BUCKET_COLORS} /></Card>
        <Card title="Open AR by segment" sub="Enterprise is on 45-day terms; self-serve is charged by card"><Donut rows={all} dim="segment" measure="balance" /></Card>
        <Card title="Who owes the most" sub="Top customers by open balance · click one to filter">
          <Bars rows={all} dim="customer_id" measure="balance" top={8}
            stack={{ key: 'due_status', values: ['not_yet_due', 'past_due'], labels: { not_yet_due: 'Not yet due', past_due: 'Past due' }, colors: { not_yet_due: '#3b6fd8', past_due: '#d1495b' } }} />
        </Card>
      </div>
      <div className="grid cols-3">
        <Card title="Are we collecting slower?" sub="DSO vs best possible DSO (the gap is lateness), by month">
          <Trend rows={trend} x="month" unit="days" format={(v) => `${v.toFixed(0)} d`}
            series={[{ key: 'dso_days', label: 'DSO' }, { key: 'best_possible_dso', label: 'Best possible', color: '#7a8699', dashed: true }]} />
        </Card>
        <Card title="Collection effectiveness" sub="CEI by month · 80% is a common bar">
          <Trend rows={trend} x="month" unit="ratio" format={(v) => `${Math.round(v * 100)}%`} series={[{ key: 'cei', label: 'CEI', color: '#2f9e6b' }]} refs={[{ y: 0.8, label: '80%' }]} />
        </Card>
        <Card title="When the cash lands" sub="Predicted from each customer's own payment history (due date + their average days late), by week">
          <Columns rows={(d.data.predicted_receipts ?? []) as Row[]} x="week_start" y="amount" color="#2f9e6b" xFormat={(v) => v.slice(5)} />
        </Card>
      </div>
      <Card title="Open invoices" sub="Filtered with the page · click a row to ask about it">
        <DataTable title="open_invoices" rows={all} onRow={(r) => ask(`What's the status of invoice ${r.invoice_ref} for ${r.customer_id}, and should we chase it?`)} columns={[
          { key: 'invoice_ref' }, { key: 'customer_id' }, { key: 'segment', chip: true }, { key: 'invoice_date' }, { key: 'due_date' }, { key: 'balance', unit: 'usd' },
          { key: 'days_past_due', label: 'Days late', unit: 'count' }, { key: 'aging_bucket', label: 'Age', chip: true }, { key: 'is_disputed', label: 'Disputed', flag: 'bad' },
          { key: 'predicted_pay_date', label: 'Expected payment' }, { key: 'prediction_basis', label: 'Based on' }, { key: 'recommended_action' }]} />
        <Source data={d.data} />
      </Card>
      <div className="grid cols-2">
        <Card title="Disputes and holds" sub="Fix these before anyone chases">
          {ex.data ? <DataTable rows={ex.data.disputes as Row[]} empty="No open disputes." columns={[{ key: 'customer_id' }, { key: 'invoice_ref' }, { key: 'disputed_amount', unit: 'usd' }, { key: 'days_open', unit: 'count' }, { key: 'root_cause' }, { key: 'note' }]} /> : <Loading state={ex} />}
        </Card>
        <Card title="Cash application exceptions" sub="Payments applied to the wrong invoice">
          {ex.data ? <DataTable rows={ex.data.rows} empty="None." columns={[{ key: 'exception_type', chip: true }, { key: 'customer_id' }, { key: 'amount', unit: 'usd' }, { key: 'detail' }]} /> : <Loading state={ex} />}
        </Card>
      </div>
    </div>
  )
}

// AP inbox (docs/dashboard_spec.md section 4): are we paying the right bills at the right time?
export function AP() {
  return <Dash><APBody /></Dash>
}

function APBody() {
  const d = useTool('get_ap_dashboard')
  const q = useTool('get_ap_review_queue')
  const { ask } = useWorkspace()
  const docs = (d.data?.rows ?? []) as Row[]
  const bills = (d.data?.open_bills ?? []) as Row[]
  const fdocs = useFiltered(docs), fbills = useFiltered(bills)
  const dpo = (d.data?.dpo ?? []) as Row[]
  const usd = (v: number) => fmt('amount', v, 'usd')
  const auto = fdocs.filter((r) => r.route === 'auto_approve').length
  const openAp = fbills.reduce((a, r) => a + Number(r.amount), 0)
  const asOf = new Date()
  const soon = fbills.filter((r) => (new Date(String(r.due_date)).getTime() - asOf.getTime()) / 864e5 <= 14).reduce((a, r) => a + Number(r.amount), 0)
  const disc = fbills.reduce((a, r) => a + Number(r.discount_captured ?? 0), 0)
  const byWeek = Object.values(fbills.reduce<Record<string, Row>>((a, r) => { const k = String(r.due_week); a[k] ??= { week: k, amount: 0 }; a[k].amount = Number(a[k].amount) + Number(r.amount); return a }, {}))
    .sort((a, b) => String(a.week).localeCompare(String(b.week)))
  const lastDpo = dpo.at(-1)
  if (!d.data) return <div className="page"><Loading state={d} /></div>
  return (
    <div className="page">
      <Head title="AP inbox" sub="Are we paying the right bills at the right time? Bills are read from PDF by AI and checked by rules · click a slice or bar to filter"
        ask="Review the AP inbox: what needs a decision, why, and what is due soon. Prepare approve or reject decisions with reasons." />
      <KpiRow items={[
        { label: 'Open AP', value: usd(openAp), note: `${fbills.length} bills awaiting payment` },
        { label: 'Due in 14 days', value: usd(soon), note: 'plan the next payment runs' },
        { label: 'Touchless rate', value: fdocs.length ? `${((auto / fdocs.length) * 100).toFixed(0)}%` : '—', note: `${auto} of ${fdocs.length} bills auto-approved`, tone: fdocs.length && auto / fdocs.length >= 0.8 ? 'good' : 'ok' },
        { label: 'Exceptions', value: String(fdocs.length - auto), note: 'a person decides', tone: fdocs.length - auto > 0 ? 'bad' : 'good' },
        { label: 'DPO (last closed month)', value: lastDpo ? `${Number(lastDpo.dpo_days).toFixed(0)} d` : '—', note: `vendor terms ${Number(d.data.avg_terms_days).toFixed(0)} d`, title: 'Company-wide' },
        { label: 'Early-pay discounts', value: usd(disc), note: 'captured in the proposed runs', tone: disc > 0 ? 'good' : null },
      ]} />
      <div className="grid cols-3">
        <Card title="Why bills stop" sub="Exceptions by reason · click to filter"><Donut rows={(d.data.issues ?? []) as Row[]} dim="issue" measure={undefined} /></Card>
        <Card title="Open AP by vendor" sub="Click a vendor to filter"><Bars rows={bills} dim="vendor_id" measure="amount" /></Card>
        <Card title="When it is due" sub="Open bills by due week"><Columns rows={byWeek} x="week" y="amount" color="#c98a1b" xFormat={(v) => v.slice(5)} /></Card>
      </div>
      <div className="grid cols-2">
        <Card title="Days payable outstanding" sub="By month (company-wide) · vs vendor terms">
          <Trend rows={dpo} x="month" unit="days" format={(v) => `${v.toFixed(0)} d`} series={[{ key: 'dpo_days', label: 'DPO', color: '#c98a1b' }]} refs={[{ y: Number(d.data.avg_terms_days), label: 'terms' }]} />
        </Card>
        <Card title="How bills are routed" sub="Auto-approved vs needs review"><Donut rows={docs} dim="route" /></Card>
      </div>
      <Card title="Needs review" sub="Click a bill to have the assistant prepare a decision for your approval">
        {q.data ? <DataTable rows={q.data.rows} onRow={(r) => ask(`Review vendor bill ${r.doc_file} and prepare an approve or reject decision with a reason.`)} columns={[
          { key: 'doc_file', label: 'Document' }, { key: 'vendor_id' }, { key: 'invoice_number' }, { key: 'total', unit: 'usd' },
          { key: 'reasons', render: (r) => <span style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>{(r.reasons as string[]).map((x) => <Chip key={x} value={x} kind="bad" />)}</span> },
          { key: 'details', render: (r) => <span className="muted">{(r.details as string[]).join(' · ')}</span> }]} /> : <Loading state={q} />}
      </Card>
      <div className="grid cols-2">
        <Card title="Proposed payment runs" sub="Thursday runs; early-pay discounts taken when worth it">
          <DataTable rows={bills} columns={[{ key: 'payment_run_date', label: 'Run' }, { key: 'bill_ref' }, { key: 'vendor_id' }, { key: 'due_date' }, { key: 'amount', unit: 'usd' }, { key: 'discount_captured', label: 'Discount', unit: 'usd' }, { key: 'priority', chip: true }]} />
        </Card>
        <Card title="All bill documents" sub="Filtered with the page">
          <DataTable title="ap_documents" rows={docs} columns={[{ key: 'doc_file' }, { key: 'vendor' }, { key: 'invoice_date' }, { key: 'total', unit: 'usd' }, { key: 'route', chip: true }, { key: 'issues' }]} />
          <Source data={d.data} />
        </Card>
      </div>
    </div>
  )
}

// Trust: can we rely on the numbers? Data quality score = checks passing / checks run, by period (Hyperbots).
export function Trust() {
  return <Dash><TrustBody /></Dash>
}

function TrustBody() {
  const t = useTool('get_trust_dashboard')
  const all = (t.data?.rows ?? []) as Row[]
  const rows = useFiltered(all)
  const trend = (t.data?.trend ?? []) as Row[]
  const latest = trend.at(-1)
  const failing = rows.filter((r) => r.status !== 'pass')
  const checks = new Set(rows.map((r) => r.check_name)).size
  if (!t.data) return <div className="page"><Loading state={t} /></div>
  return (
    <div className="page">
      <Head title="Trust" sub="Can we rely on the numbers? Every key number is reconciled to an independent source; if a check fails, the assistant says the number is not trusted"
        ask="Are all reconciliations passing? Is any number untrusted right now, and what would fix it?" />
      <KpiRow items={[
        { label: 'Data quality score', value: rows.length ? `${((1 - failing.length / rows.length) * 100).toFixed(1)}%` : '—', note: `${rows.length - failing.length} of ${rows.length} checks pass`, tone: failing.length ? 'bad' : 'good' },
        { label: 'Failing now', value: String(failing.length), note: 'numbers the assistant will not vouch for', tone: failing.length ? 'bad' : 'good' },
        { label: 'Latest period', value: latest ? String(latest.period) : '—', note: latest ? `${latest.passing} / ${latest.checks} passing` : '' },
        { label: 'Checks', value: String(checks), note: 'independent reconciliations' },
        { label: 'Periods covered', value: String(trend.length) },
      ]} />
      <div className="grid cols-3">
        <Card title="Pass rate by period" sub="Company-wide">
          <Trend rows={trend} x="period" unit="ratio" format={(v) => `${Math.round(v * 100)}%`} series={[{ key: 'pass_rate', label: 'Passing', color: '#2f9e6b' }]} refs={[{ y: 1, label: '100%' }]} />
        </Card>
        <Card title="Results by check" sub="Click a check to filter"><Bars rows={all} dim="check_name" stack={{ key: 'status', values: ['pass', 'fail'], colors: { pass: '#2f9e6b', fail: '#d1495b' } }} top={12} /></Card>
        <Card title="Status" sub="All checks, all periods"><Donut rows={all} dim="status" colors={{ pass: '#2f9e6b', fail: '#d1495b' }} /></Card>
      </div>
      <Card title="Failures" sub="Expected vs actual, and why">
        <DataTable rows={(t.data.failures ?? []) as Row[]} empty="Nothing failing: every number is reconciled." columns={[{ key: 'check_name' }, { key: 'period' }, { key: 'entity_id' }, { key: 'expected', unit: 'usd' }, { key: 'actual', unit: 'usd' }, { key: 'variance', unit: 'usd' }, { key: 'explanation' }]} />
      </Card>
      <Card title="All results" sub="Filtered with the page">
        <DataTable title="reconciliations" rows={all} columns={[{ key: 'check_name' }, { key: 'period' }, { key: 'entity_id' }, { key: 'expected', unit: 'usd' }, { key: 'actual', unit: 'usd' }, { key: 'variance', unit: 'usd' }, { key: 'status', chip: true }]} />
        <Source data={t.data} />
      </Card>
    </div>
  )
}
