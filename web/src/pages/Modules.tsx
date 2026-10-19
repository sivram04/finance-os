// Module pages. Each reads the same read-only tools the assistant uses, so both always show the same numbers.
import { useState } from 'react'
import { fmt, type Row } from '../api'
import { AskButton, Card, Chip, DataTable, Loading, Source, useTool, useWorkspace } from '../components/common'

function Head({ title, sub, ask }: { title: string; sub: string; ask: string }) {
  return (
    <div className="page-head">
      <div><h1>{title}</h1><p>{sub}</p></div>
      <AskButton text={ask}>Ask the assistant</AskButton>
    </div>
  )
}

export function Revenue() {
  const ue = useTool('get_unit_economics')
  const mv = useTool('get_revenue_movements')
  const { ask } = useWorkspace()
  const bridge = mv.data?.rows[0]
  return (
    <div className="page">
      <Head title="Revenue & margins" sub="Customer margins against product floors, and how MRR moved this month."
        ask="Which customers are below their margin floor and why? What drove MRR this month?" />
      <div className="grid cols-2" style={{ alignItems: 'start' }}>
        <Card title="MRR bridge" sub={mv.data ? String(mv.data.month) : ''}>
          {bridge ? <DataTable rows={['opening_mrr', 'new_mrr', 'expansion_mrr', 'contraction_mrr', 'churned_mrr', 'reactivation_mrr', 'closing_mrr']
            .map((k) => ({ movement: k.replace('_mrr', ''), amount: bridge[k] }))} columns={[{ key: 'movement' }, { key: 'amount', unit: 'usd' }]} /> : <Loading state={mv} />}
          <Source data={mv.data} />
        </Card>
        <Card title="Biggest movers">
          {mv.data ? <DataTable rows={mv.data.biggest_movers as Row[]} columns={[{ key: 'customer_id' }, { key: 'movement', chip: true }, { key: 'prior_revenue', unit: 'usd' }, { key: 'revenue', unit: 'usd' }]}
            onRow={(r) => ask(`What happened to ${r.customer_id}'s revenue?`)} /> : <Loading state={mv} />}
        </Card>
      </div>
      <Card title="Cost to serve by product">
        {ue.data ? <DataTable rows={ue.data.by_product as Row[]} columns={[{ key: 'product_id' }, { key: 'revenue', unit: 'usd' }, { key: 'cogs', unit: 'usd' }, { key: 'gross_margin_pct', unit: 'ratio' }, { key: 'cost_to_serve_per_hour', label: 'Cost / audio hour', render: (r) => `$${(r.cost_to_serve_per_hour as number).toFixed(4)}` }]} /> : <Loading state={ue} />}
      </Card>
      <Card title="Customer margins" sub="Lowest margin first · click a row to ask about it">
        {ue.data ? <DataTable rows={ue.data.rows} onRow={(r) => ask(`Explain ${r.customer_id}'s margin this month.`)} columns={[
          { key: 'customer_id' }, { key: 'segment', chip: true }, { key: 'revenue', unit: 'usd' }, { key: 'gross_margin_pct', unit: 'ratio' },
          { key: 'gross_margin_floor_pct', label: 'Floor', unit: 'ratio' }, { key: 'contribution_margin', unit: 'usd' }, { key: 'is_below_floor', label: 'Below floor', flag: 'bad' }]} /> : <Loading state={ue} />}
        <Source data={ue.data} />
      </Card>
    </div>
  )
}

export function Spend() {
  const [by, setBy] = useState('vendor')
  const ts = useTool('get_tech_spend', { group_by: by })
  const gpu = useTool('get_gpu_capacity_and_forecast')
  const tag = (ts.data?.tagging as Row[] | undefined)?.[0]
  return (
    <div className="page">
      <Head title="Tech spend" sub="GPU and cloud cost, tagging, reserved capacity and the 3-month forecast."
        ask="Summarize tech spend this month: biggest costs, tagging coverage, GPU commitment use and the forecast." />
      <div className="grid cols-4">
        <div className="card kpi"><div className="label">Total this month</div><div className="value">{ts.data ? `$${((ts.data.rows.reduce((a, r) => a + (r.cost as number), 0)) / 1000).toFixed(1)}K` : '…'}</div></div>
        <div className="card kpi"><div className="label">Tagging coverage</div><div className="value">{tag ? `${((tag.tagging_coverage_pct as number) * 100).toFixed(1)}%` : '…'}</div></div>
        <div className="card kpi"><div className="label">Untagged</div><div className="value">{tag ? `$${(tag.untagged_cost as number).toLocaleString()}` : '…'}</div></div>
        <div className="card kpi"><div className="label">Vendor renewals due</div><div className="value">{gpu.data ? (gpu.data.vendor_contracts as Row[]).filter((r) => r.is_renewal_due).length : '…'}</div></div>
      </div>
      <Card title="Spend this month" right={<div className="segmented">{['vendor', 'team', 'category', 'model'].map((k) => <button key={k} className={by === k ? 'on' : ''} onClick={() => setBy(k)}>{k}</button>)}</div>}>
        {ts.data ? <DataTable rows={ts.data.rows} columns={[{ key: by }, { key: 'cost', unit: 'usd' }]} /> : <Loading state={ts} />}
        <Source data={ts.data} />
      </Card>
      <div className="grid cols-2" style={{ alignItems: 'start' }}>
        <Card title="Reserved GPU use vs. commit">
          {gpu.data ? <DataTable rows={gpu.data.rows.slice(-8)} columns={[{ key: 'month' }, { key: 'gpu_type' }, { key: 'used_hours', unit: 'count' }, { key: 'committed_hours', unit: 'count' }, { key: 'commit_utilization_pct', unit: 'ratio' }, { key: 'shortfall_cost', unit: 'usd' }]} /> : <Loading state={gpu} />}
        </Card>
        <Card title="3-month forecast">
          {gpu.data ? <DataTable rows={gpu.data.forecast as Row[]} columns={[{ key: 'month' }, { key: 'vendor_id' }, { key: 'line_type' }, { key: 'gpu_type' }, { key: 'forecast_amount', unit: 'usd' }]} /> : <Loading state={gpu} />}
        </Card>
      </div>
      <Card title="Vendor contracts">
        {gpu.data ? <DataTable rows={gpu.data.vendor_contracts as Row[]} columns={[{ key: 'vendor_name' }, { key: 'category' }, { key: 'end_date' }, { key: 'days_to_end', unit: 'count' }, { key: 'avg_monthly_spend_t3m', label: 'Avg monthly spend (3m)', unit: 'usd' }, { key: 'is_renewal_due', label: 'Renewal due', flag: 'warn' }]} /> : <Loading state={gpu} />}
      </Card>
    </div>
  )
}

export function Budget() {
  const s = useTool('get_budget_vs_actual')
  const [alert, setAlert] = useState<string | null>(null)
  const drivers = useTool('get_variance_drivers', { alert_id: alert ?? '' })
  const { ask } = useWorkspace()
  return (
    <div className="page">
      <Head title="Budget vs. actual" sub="This month by department and account, full-year forecast, and the transactions behind each alert."
        ask="Where are we over or under budget this month and for the full year, and why?" />
      <Card title="Alerts" sub="Unfavorable by more than 10% and $5K · click to see the driving transactions">
        {s.data ? <DataTable rows={s.data.alerts as Row[]} empty="No budget alerts this month." onRow={(r) => setAlert(r.alert_id as string)}
          columns={[{ key: 'department_id', label: 'Dept' }, { key: 'account_id' }, { key: 'message' }, { key: 'route_to' }]} /> : <Loading state={s} />}
      </Card>
      {alert && (
        <Card title={`Drivers · ${alert}`} right={<button className="btn small" onClick={() => ask(`Explain budget alert ${alert} from its driving transactions.`)}>Explain this variance</button>}>
          {drivers.data ? <DataTable rows={drivers.data.rows} columns={[{ key: 'driver_rank', label: '#' }, { key: 'entry_date' }, { key: 'entry_type', chip: true }, { key: 'memo' }, { key: 'amount', unit: 'usd' }, { key: 'share_of_actual', unit: 'ratio' }]} /> : <Loading state={drivers} />}
        </Card>
      )}
      <Card title="All lines" sub={s.data ? `Month ${s.data.month}` : ''}>
        {s.data ? <DataTable rows={s.data.rows} columns={[{ key: 'department_id', label: 'Dept' }, { key: 'account_name' }, { key: 'actual', unit: 'usd' }, { key: 'budget', unit: 'usd' }, { key: 'variance', unit: 'usd' }, { key: 'variance_pct', unit: 'ratio' }, { key: 'fy_forecast_variance', label: 'FY forecast vs. budget', unit: 'usd' }, { key: 'is_alert', label: 'Alert', flag: 'bad' }]} /> : <Loading state={s} />}
        <Source data={s.data} />
      </Card>
    </div>
  )
}

export function Projects() {
  const p = useTool('get_projects')
  const f = useTool('get_contract_funding')
  const { ask } = useWorkspace()
  return (
    <div className="page">
      <Head title="Projects" sub="Estimate at completion, % complete, earned vs. billed, and federal funding."
        ask="Which projects are at risk (budget, cap, funding, unbilled work) and what should we do?" />
      <Card title="Project financials" sub="Click a project to ask about it">
        {p.data ? <DataTable rows={p.data.rows} onRow={(r) => ask(`What's the status of ${r.project_id} and what should we do about it?`)} columns={[
          { key: 'project_id' }, { key: 'project_type', chip: true }, { key: 'budget', unit: 'usd' }, { key: 'eac', label: 'EAC', unit: 'usd' },
          { key: 'eac_pct_of_budget', label: 'EAC / budget', unit: 'ratio' }, { key: 'pct_complete', unit: 'ratio' }, { key: 'earned_to_date', unit: 'usd' },
          { key: 'billed_to_date', unit: 'usd' }, { key: 'unbilled', unit: 'usd' }, { key: 'is_over_budget', label: 'Over budget', flag: 'bad' }, { key: 'is_cap_alert', label: 'Near cap', flag: 'warn' }]} /> : <Loading state={p} />}
        <Source data={p.data} />
      </Card>
      <div className="grid cols-2" style={{ alignItems: 'start' }}>
        <Card title="Contract funding" sub="Federal contracts get Limitation of Funds alerts at 75% and 90%">
          {f.data ? <DataTable rows={f.data.rows} columns={[{ key: 'contract_id' }, { key: 'clin_id', label: 'CLIN' }, { key: 'funded', unit: 'usd' }, { key: 'billed_to_date', unit: 'usd' }, { key: 'funding_used_pct', unit: 'ratio' }, { key: 'is_funding_alert_75', label: '75% notice', flag: 'warn' }]} /> : <Loading state={f} />}
        </Card>
        <Card title="Exceptions">
          {p.data ? <DataTable rows={p.data.exceptions as Row[]} columns={[{ key: 'exception_type', chip: true }, { key: 'project_id' }, { key: 'detail' }, { key: 'amount', unit: 'usd' }]} /> : <Loading state={p} />}
        </Card>
      </div>
    </div>
  )
}

export function Billing() {
  const s = useTool('get_billing_status')
  return (
    <div className="page">
      <Head title="Billing" sub="Status per project, the next billing run, and validation of every invoice line."
        ask="What's ready to bill, what's blocked, and are there any invoice errors?" />
      <Card title="Billing status">
        {s.data ? <DataTable rows={s.data.rows} columns={[{ key: 'project_id' }, { key: 'billing_status', label: 'Status', chip: true }, { key: 'billed_total', unit: 'usd' }, { key: 'open_ar', unit: 'usd' }, { key: 'ready_to_bill', unit: 'usd' }, { key: 'oldest_unbilled_days', unit: 'count' }, { key: 'has_unbilled_alert', label: 'Unbilled alert', flag: 'bad' }]} /> : <Loading state={s} />}
      </Card>
      <div className="grid cols-2" style={{ alignItems: 'start' }}>
        <Card title="Next billing run (drafts)">
          {s.data ? <DataTable rows={s.data.next_billing_run as Row[]} columns={[{ key: 'project_id' }, { key: 'item_type', chip: true }, { key: 'reference' }, { key: 'amount', unit: 'usd' }, { key: 'days_unbilled', unit: 'count' }, { key: 'validation_status', label: 'Validation', chip: true }]} /> : <Loading state={s} />}
        </Card>
        <Card title="Validation exceptions on issued invoices">
          {s.data ? <DataTable rows={s.data.validation_exceptions as Row[]} empty="No exceptions." columns={[{ key: 'exception_type', chip: true }, { key: 'invoice_id' }, { key: 'detail' }, { key: 'amount_at_risk', unit: 'usd' }]} /> : <Loading state={s} />}
        </Card>
      </div>
    </div>
  )
}

export function AR() {
  const aging = useTool('get_ar_aging')
  const queue = useTool('get_collections_queue', { limit: 20 })
  const ex = useTool('get_ar_exceptions')
  const { ask } = useWorkspace()
  const recent = (aging.data?.recent_months as Row[] | undefined)?.[0]
  return (
    <div className="page">
      <Head title="Receivables" sub="Aging, DSO and collection effectiveness, the collections queue, and anything on hold."
        ask="Who should we chase for payment first, and is anything on hold that needs fixing first?" />
      <div className="grid cols-4">
        <div className="card kpi"><div className="label">Ending AR</div><div className="value">{recent ? `$${((recent.ending_ar as number) / 1000).toFixed(1)}K` : '…'}</div></div>
        <div className="card kpi"><div className="label">Over 60 days</div><div className="value">{recent ? `$${(recent.ar_over_60 as number).toLocaleString()}` : '…'}</div></div>
        <div className="card kpi"><div className="label">DSO (days)</div><div className="value">{recent ? String(recent.dso_days) : '…'}</div></div>
        <div className="card kpi"><div className="label">CEI</div><div className="value">{recent ? `${((recent.cei as number) * 100).toFixed(1)}%` : '…'}</div></div>
      </div>
      <div className="grid cols-2" style={{ alignItems: 'start' }}>
        <Card title="Aging">
          {aging.data ? <DataTable rows={aging.data.rows} columns={[{ key: 'aging_bucket', label: 'Bucket', chip: true }, { key: 'invoices', unit: 'count' }, { key: 'balance', unit: 'usd' }]} /> : <Loading state={aging} />}
          <Source data={aging.data} />
        </Card>
        <Card title="On hold" sub="Not chased until fixed">
          {queue.data ? <DataTable rows={queue.data.on_hold as Row[]} empty="Nothing on hold." columns={[{ key: 'invoice_ref' }, { key: 'customer_id' }, { key: 'balance', unit: 'usd' }, { key: 'recommended_action' }]} /> : <Loading state={queue} />}
        </Card>
      </div>
      <Card title="Collections queue" sub="Invoices worth a person's time, ranked by balance × days overdue × segment weight · click to ask">
        {queue.data && (queue.data.by_route as Row[] | undefined)?.length ? (
          <div className="muted" style={{ marginBottom: 8 }}>
            {(queue.data.by_route as Row[]).map((r) => `${String(r.route).replace('_', ' ')}: ${r.invoices} invoices (${fmt('balance', r.balance as number, 'usd')})`).join(' · ')}
            {' '}— card customers are retried automatically (dunning); small balances roll into the next statement.
          </div>) : null}
        {queue.data ? <DataTable rows={queue.data.rows as Row[]} empty="No invoice needs a person to chase right now." onRow={(r) => ask(`Should we chase ${r.invoice_ref}? Review the reminder draft if there is one.`)} columns={[
          { key: 'queue_rank', label: '#' }, { key: 'invoice_ref' }, { key: 'customer_id' }, { key: 'segment', chip: true }, { key: 'balance', unit: 'usd' }, { key: 'days_past_due', unit: 'count' }, { key: 'recommended_action' }]} /> : <Loading state={queue} />}
      </Card>
      <div className="grid cols-2" style={{ alignItems: 'start' }}>
        <Card title="Cash application exceptions">
          {ex.data ? <DataTable rows={ex.data.rows} empty="None." columns={[{ key: 'exception_type', chip: true }, { key: 'customer_id' }, { key: 'detail' }]} /> : <Loading state={ex} />}
        </Card>
        <Card title="Disputes">
          {ex.data ? <DataTable rows={ex.data.disputes as Row[]} empty="No disputes." columns={[{ key: 'customer_id' }, { key: 'invoice_ref' }, { key: 'status', chip: true }, { key: 'days_open', unit: 'count' }, { key: 'note' }]} /> : <Loading state={ex} />}
        </Card>
      </div>
    </div>
  )
}

export function AP() {
  const s = useTool('get_ap_review_queue')
  const { ask } = useWorkspace()
  const routing = Object.fromEntries(((s.data?.routing as Row[]) ?? []).map((r) => [r.route, r.documents]))
  return (
    <div className="page">
      <Head title="AP inbox" sub="Vendor bills read from PDF by AI, then checked against POs and the ledger by rules."
        ask="Review the AP inbox and recommend what to approve or reject, with reasons." />
      <div className="grid cols-3">
        <div className="card kpi"><div className="label">Auto-approved</div><div className="value">{String(routing.auto_approve ?? '…')}</div><div className="note">passed every check</div></div>
        <div className="card kpi"><div className="label">Needs review</div><div className="value">{String(s.data?.documents_needing_review ?? '…')}</div><div className="note">a person decides</div></div>
        <div className="card kpi"><div className="label">How bills are read</div><div className="value" style={{ fontSize: 15, marginTop: 8 }}>PDF → AI extraction → rule checks</div></div>
      </div>
      <Card title="Needs review" sub="Click a bill to have the assistant prepare a decision for your approval">
        {s.data ? <DataTable rows={s.data.rows} onRow={(r) => ask(`Review vendor bill ${r.doc_file} and prepare an approve or reject decision with a reason.`)} columns={[
          { key: 'doc_file', label: 'Document' }, { key: 'vendor_id' }, { key: 'invoice_number' }, { key: 'total', unit: 'usd' },
          { key: 'reasons', render: (r) => <span style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>{(r.reasons as string[]).map((x) => <Chip key={x} value={x} kind="bad" />)}</span> },
          { key: 'details', render: (r) => <span className="muted">{(r.details as string[]).join(' · ')}</span> }]} /> : <Loading state={s} />}
        <Source data={s.data} />
      </Card>
    </div>
  )
}

export function Trust() {
  const s = useTool('get_reconciliation_status')
  return (
    <div className="page">
      <Head title="Trust" sub="Every key number is reconciled to an independent source. If a check fails, the assistant says the number is not trusted."
        ask="Are all reconciliations passing? Is any number untrusted right now?" />
      <Card title="Reconciliation checks" right={s.data ? <Chip value={s.data.all_passing ? 'all passing' : 'failures'} kind={s.data.all_passing ? 'good' : 'bad'} /> : null}>
        {s.data ? <DataTable rows={s.data.rows} columns={[{ key: 'check_name' }, { key: 'periods', unit: 'count' }, { key: 'passing', unit: 'count' }, { key: 'failing', unit: 'count' }]} /> : <Loading state={s} />}
        <Source data={s.data} />
      </Card>
      {s.data && (s.data.failures as Row[]).length > 0 && (
        <Card title="Failures"><DataTable rows={s.data.failures as Row[]} columns={[{ key: 'check_name' }, { key: 'period' }, { key: 'entity_id' }, { key: 'variance', unit: 'usd' }, { key: 'explanation' }]} /></Card>
      )}
    </div>
  )
}
