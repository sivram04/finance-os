// FP&A, treasury, close, pricing, capital and tax pages. Like the module pages, each reads the same read-only
// tools the assistant uses, so a number on a page and in an answer always agree.
import { useEffect, useState } from 'react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, fmt, type Row } from '../api'
import { AskButton, Card, Chip, DataTable, Loading, Source, useTool, useWorkspace, type Page } from '../components/common'

const AXIS = { tick: { fontSize: 11, fill: 'var(--faint)' }, tickLine: false, axisLine: false } as const
const TIP = { contentStyle: { background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 } }
const usd = (v: unknown) => fmt('amount', v as number, 'usd')
const SCENARIO_COLOR: Record<string, string> = { base: 'var(--accent)', upside: 'var(--good, #2f9e6b)', downside: 'var(--bad, #d1495b)' }

function Head({ title, sub, ask }: { title: string; sub: string; ask: string }) {
  return (
    <div className="page-head">
      <div><h1>{title}</h1><p>{sub}</p></div>
      <AskButton text={ask}>Ask the assistant</AskButton>
    </div>
  )
}

function Kpi({ label, value, note, tone }: { label: string; value: string; note?: string; tone?: 'bad' | 'good' }) {
  return (
    <div className="card kpi">
      <div className="label">{label}</div>
      <div className="value" style={tone ? { color: tone === 'bad' ? 'var(--bad, #d1495b)' : 'var(--good, #2f9e6b)' } : undefined}>{value}</div>
      {note && <div className="note">{note}</div>}
    </div>
  )
}

// ---- Plan: forecast, scenarios, accuracy, headcount, budget build, allocation -------------------------

export function Plan() {
  const [scenario, setScenario] = useState('base')
  const f = useTool('get_forecast', { scenario })
  const all = [useTool('get_forecast', { scenario: 'base' }), useTool('get_forecast', { scenario: 'upside' }), useTool('get_forecast', { scenario: 'downside' })]
  const acc = useTool('get_forecast_accuracy')
  const hc = useTool('get_headcount_plan', { scenario })
  const bb = useTool('get_budget_build')
  const alloc = useTool('get_shared_cost_allocation')
  const summary = (f.data?.scenarios as Row[] | undefined) ?? []
  const cur = summary.find((s) => s.scenario === scenario)
  const cash = all.every((s) => s.data)
    ? (all[0].data!.rows as Row[]).map((r, i) => ({ month: r.month, base: r.closing_cash, upside: all[1].data!.rows[i]?.closing_cash, downside: all[2].data!.rows[i]?.closing_cash }))
    : null
  return (
    <div className="page">
      <Head title="Plan & forecast" sub="Driver-based 18-month forecast by scenario, how accurate past forecasts were, the hiring plan and next year's budget."
        ask="Walk me through the forecast: base vs upside vs downside, when cash runs out in each, and what drives the difference." />
      <div className="grid cols-4">
        <Kpi label="Revenue, next 12 months" value={cur ? usd(cur.revenue_next_12m) : '…'} note={`${scenario} scenario`} />
        <Kpi label="EBITDA, next 12 months" value={cur ? usd(cur.ebitda_next_12m) : '…'} tone={cur && (cur.ebitda_next_12m as number) < 0 ? 'bad' : undefined} />
        <Kpi label="Runway" value={cur?.runway_months != null ? `${(cur.runway_months as number).toFixed(1)} mo` : '…'} tone={cur && (cur.runway_months as number) < 12 ? 'bad' : undefined} />
        <Kpi label="Cash runs out" value={cur ? (cur.cash_out_month ? String(cur.cash_out_month).slice(0, 7) : 'Not in 18 mo') : '…'} tone={cur?.cash_out_month ? 'bad' : 'good'} />
      </div>
      <Card title="Cash by scenario" sub="Closing cash, 18 months from the last closed month">
        {cash ? (
          <div style={{ height: 260 }}>
            <ResponsiveContainer>
              <LineChart data={cash} margin={{ left: 8, right: 8, top: 8 }}>
                <CartesianGrid stroke="var(--border)" vertical={false} />
                <XAxis dataKey="month" {...AXIS} />
                <YAxis tickFormatter={usd} width={70} {...AXIS} />
                <Tooltip formatter={usd} {...TIP} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <ReferenceLine y={0} stroke="var(--faint)" strokeDasharray="4 4" />
                {['base', 'upside', 'downside'].map((s) => <Line key={s} dataKey={s} stroke={SCENARIO_COLOR[s]} strokeWidth={s === scenario ? 2.5 : 1.5} dot={false} />)}
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : <Loading state={all.find((s) => !s.data) ?? all[0]} />}
      </Card>
      <Card title="Monthly forecast" right={<div className="segmented">{['base', 'upside', 'downside'].map((s) => <button key={s} className={scenario === s ? 'on' : ''} onClick={() => setScenario(s)}>{s}</button>)}</div>}>
        {f.data ? <DataTable rows={f.data.rows} columns={[{ key: 'month' }, { key: 'revenue', unit: 'usd' }, { key: 'gross_margin_pct', unit: 'ratio' }, { key: 'payroll', unit: 'usd' }, { key: 'other_opex', unit: 'usd' }, { key: 'ebitda', unit: 'usd' }, { key: 'closing_cash', unit: 'usd' }]} /> : <Loading state={f} />}
        <Source data={f.data} />
      </Card>
      <div className="grid cols-2" style={{ alignItems: 'start' }}>
        <Card title="Forecast accuracy" sub="Past base forecasts vs what actually closed · positive = forecast too high">
          {acc.data ? <DataTable rows={acc.data.rows} columns={[{ key: 'line' }, { key: 'months_ahead', label: 'Months ahead' }, { key: 'n', label: 'Versions' }, { key: 'avg_error_pct', label: 'Avg error (bias)', unit: 'ratio' }, { key: 'avg_abs_error_pct', label: 'Avg abs error', unit: 'ratio' }]} /> : <Loading state={acc} />}
        </Card>
        <Card title="Hiring plan" sub={`${scenario} scenario · fully loaded cost`}>
          {hc.data ? <DataTable rows={hc.data.planned_roles as Row[]} empty="No roles in this scenario." columns={[{ key: 'role_id' }, { key: 'department_id', label: 'Dept' }, { key: 'title' }, { key: 'start_month' }, { key: 'status', chip: true }, { key: 'monthly_loaded_cost', label: 'Loaded / month', unit: 'usd' }]} /> : <Loading state={hc} />}
        </Card>
      </div>
      <div className="grid cols-2" style={{ alignItems: 'start' }}>
        <Card title="Next year's budget" sub="Bottom-up (department asks) vs top-down (board targets)">
          {bb.data ? <DataTable rows={bb.data.rows} columns={[{ key: 'line' }, { key: 'department_id', label: 'Dept' }, { key: 'bottom_up', unit: 'usd' }, { key: 'top_down', unit: 'usd' }, { key: 'gap', unit: 'usd' }, { key: 'gap_pct', unit: 'ratio' }]} /> : <Loading state={bb} />}
          <Source data={bb.data} />
        </Card>
        <Card title="Shared costs by department" sub={alloc.data ? `Allocated by headcount · ${alloc.data.month}` : ''}>
          {alloc.data ? <DataTable rows={alloc.data.rows} columns={[{ key: 'pool' }, { key: 'department_id', label: 'Dept' }, { key: 'headcount', unit: 'count' }, { key: 'headcount_share', label: 'Share', unit: 'ratio' }, { key: 'allocated_amount', unit: 'usd' }]} /> : <Loading state={alloc} />}
        </Card>
      </div>
    </div>
  )
}

// ---- Cash: 13-week forecast, accounts, covenants, payment runs, working capital ------------------------

export function Cash() {
  const c = useTool('get_cash_forecast')
  const runs = useTool('get_payment_runs')
  const wc = useTool('get_working_capital')
  const { ask } = useWorkspace()
  const weeks = (c.data?.rows ?? []) as Row[]
  const low = weeks.length ? weeks.reduce((a, r) => ((r.closing_cash as number) < (a.closing_cash as number) ? r : a)) : null
  const breaches = (c.data?.covenant_breaches ?? []) as Row[]
  const lastWc = (wc.data?.rows as Row[] | undefined)?.[0]
  return (
    <div className="page">
      <Head title="Cash & treasury" sub="13-week cash forecast, cash by account, covenants, vendor payment runs and working capital."
        ask="What does the 13-week cash forecast show, when do we breach minimum cash, and what can we do about it?" />
      <div className="grid cols-4">
        <Kpi label="Cash today" value={weeks[0] ? usd(weeks[0].opening_cash) : '…'} />
        <Kpi label="Lowest in 13 weeks" value={low ? usd(low.closing_cash) : '…'} note={low ? `week ${low.week}` : ''} tone={low?.is_below_min_cash ? 'bad' : undefined} />
        <Kpi label="Covenants breached" value={c.data ? String(breaches.length) : '…'} tone={breaches.length ? 'bad' : 'good'} />
        <Kpi label="Cash conversion cycle" value={lastWc ? `${(lastWc.cash_conversion_cycle_days as number).toFixed(1)} days` : '…'} note={lastWc ? `DSO ${lastWc.dso_days} · DPO ${lastWc.dpo_days}` : ''} />
      </div>
      <Card title="13-week cash forecast" sub="Closing cash per week · dashed line = $3M minimum (policy MIN-CASH)">
        {c.data ? (
          <div style={{ height: 240 }}>
            <ResponsiveContainer>
              <AreaChart data={weeks} margin={{ left: 8, right: 8, top: 8 }}>
                <defs><linearGradient id="cashg" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--accent)" stopOpacity={0.25} /><stop offset="100%" stopColor="var(--accent)" stopOpacity={0} /></linearGradient></defs>
                <CartesianGrid stroke="var(--border)" vertical={false} />
                <XAxis dataKey="week_start" {...AXIS} />
                <YAxis tickFormatter={usd} width={70} {...AXIS} domain={['auto', 'auto']} />
                <Tooltip formatter={usd} {...TIP} />
                <ReferenceLine y={3000000} stroke="var(--bad, #d1495b)" strokeDasharray="4 4" />
                <Area type="monotone" dataKey="closing_cash" stroke="var(--accent)" strokeWidth={2} fill="url(#cashg)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        ) : <Loading state={c} />}
      </Card>
      <Card title="Week by week">
        {c.data ? <DataTable rows={weeks} columns={[{ key: 'week' }, { key: 'week_start' }, { key: 'opening_cash', unit: 'usd' }, { key: 'inflows', unit: 'usd' }, { key: 'payroll', unit: 'usd' }, { key: 'vendors', unit: 'usd' }, { key: 'other_opex', unit: 'usd' }, { key: 'closing_cash', unit: 'usd' }, { key: 'is_below_min_cash', label: 'Below minimum', flag: 'bad' }]} /> : <Loading state={c} />}
        <Source data={c.data} />
      </Card>
      <div className="grid cols-2" style={{ alignItems: 'start' }}>
        <Card title="Covenants and policies" sub="First month each is breached (actuals, then base forecast)">
          {c.data ? <DataTable rows={breaches} empty="All covenants pass." onRow={(r) => ask(`Explain covenant ${r.rule_id} and what it would take to stay compliant.`)}
            columns={[{ key: 'rule_id' }, { key: 'description' }, { key: 'first_breach_month' }, { key: 'breached_in_actuals', label: 'Already breached', flag: 'bad' }]} /> : <Loading state={c} />}
        </Card>
        <Card title="Cash by account">
          {c.data ? <DataTable rows={c.data.cash_by_account as Row[]} columns={[{ key: 'bank' }, { key: 'account_type', chip: true }, { key: 'balance', unit: 'usd' }, { key: 'annual_yield', unit: 'ratio' }, { key: 'monthly_interest', unit: 'usd' }, { key: 'weeks_of_outflows', label: 'Weeks covered' }]} /> : <Loading state={c} />}
        </Card>
      </div>
      <Card title="Proposed vendor payment runs" sub="Thursday runs · early-pay discounts taken when worth it · proposal only">
        {runs.data ? <DataTable rows={runs.data.rows} empty="No unpaid vendor bills." columns={[{ key: 'payment_run_date', label: 'Run' }, { key: 'bill_ref' }, { key: 'vendor_id' }, { key: 'due_date' }, { key: 'amount', unit: 'usd' }, { key: 'discount_captured', unit: 'usd' }, { key: 'priority', chip: true }, { key: 'is_overdue', label: 'Overdue', flag: 'bad' }]} /> : <Loading state={runs} />}
      </Card>
      <Card title="Working capital" sub="Last 12 closed months">
        {wc.data ? <DataTable rows={wc.data.rows} columns={[{ key: 'month' }, { key: 'ar_balance', unit: 'usd' }, { key: 'ap_balance', unit: 'usd' }, { key: 'net_working_capital', unit: 'usd' }, { key: 'dso_days', unit: 'days' }, { key: 'dpo_days', unit: 'days' }, { key: 'cash_conversion_cycle_days', label: 'CCC days', unit: 'days' }]} /> : <Loading state={wc} />}
      </Card>
    </div>
  )
}

// ---- Close: checklist, accruals, prepaids, revenue recognition ----------------------------------------

export function Close() {
  const cs = useTool('get_close_status')
  const rr = useTool('get_revenue_recognition')
  const { ask } = useWorkspace()
  const tasks = (cs.data?.rows ?? []) as Row[]
  const done = tasks.filter((t) => t.status === 'complete' || t.status === 'not_applicable').length
  return (
    <div className="page">
      <Head title="Month-end close" sub="Close checklist driven by the reconciliations, accruals, prepaid amortization and ASC 606 revenue."
        ask="Where are we in the month-end close? What's blocking sign-off and what entries still need to be booked?" />
      <div className="grid cols-4">
        <Kpi label="Close period" value={cs.data ? String(cs.data.month).slice(0, 7) : '…'} />
        <Kpi label="Tasks complete" value={cs.data ? `${done} / ${tasks.length}` : '…'} tone={cs.data && done === tasks.length ? 'good' : undefined} />
        <Kpi label="Accrued, not yet billed" value={cs.data ? usd((cs.data.accruals as Row[]).reduce((a, r) => a + (r.accrued_amount as number), 0)) : '…'} />
        <Kpi label="ASC 606 adjustment" value={rr.data ? usd((rr.data.rows as Row[])[0]?.revenue_adjustment) : '…'} note="vs revenue booked in the GL" />
      </div>
      <Card title="Checklist" sub="Status comes from the evidence (reconciliations, schedules, BvA alerts) · click a task to ask about it">
        {cs.data ? <DataTable rows={tasks} onRow={(r) => ask(`Close task ${r.task_id} (${r.task}) is ${r.status}. What does it need?`)}
          columns={[{ key: 'task_id', label: '#' }, { key: 'due_date' }, { key: 'owner' }, { key: 'task' }, { key: 'status', render: (r) => <Chip value={String(r.status)} kind={r.status === 'complete' ? 'good' : r.status === 'exceptions' || r.status === 'blocked' ? 'bad' : r.status === 'not_applicable' ? undefined : 'warn'} /> }, { key: 'open_items', unit: 'count' }]} /> : <Loading state={cs} />}
        <Source data={cs.data} />
      </Card>
      <div className="grid cols-2" style={{ alignItems: 'start' }}>
        <Card title="Accruals" sub="Costs booked before the invoice arrived">
          {cs.data ? <DataTable rows={cs.data.accruals as Row[]} empty="No accruals this month." columns={[{ key: 'vendor_id' }, { key: 'bill_id' }, { key: 'accrued_amount', unit: 'usd' }, { key: 'true_up', unit: 'usd' }]} /> : <Loading state={cs} />}
        </Card>
        <Card title="Prepaid amortization">
          {cs.data ? <DataTable rows={cs.data.prepaid_amortization as Row[]} empty="Nothing to amortize this month." columns={[{ key: 'prepaid_id' }, { key: 'vendor' }, { key: 'amortization', unit: 'usd' }, { key: 'closing_balance', unit: 'usd' }]} /> : <Loading state={cs} />}
        </Card>
      </div>
      <Card title="Deferred revenue roll-forward (ASC 606)" sub="Opening + billings − revenue = closing">
        {rr.data ? <DataTable rows={rr.data.rows} columns={[{ key: 'month' }, { key: 'opening_net_deferred', label: 'Opening', unit: 'usd' }, { key: 'billings', unit: 'usd' }, { key: 'asc606_revenue', label: 'ASC 606 revenue', unit: 'usd' }, { key: 'closing_net_deferred', label: 'Closing', unit: 'usd' }, { key: 'contract_asset', unit: 'usd' }, { key: 'gl_revenue', label: 'GL revenue', unit: 'usd' }, { key: 'revenue_adjustment', label: 'Adjustment', unit: 'usd' }]} /> : <Loading state={rr} />}
      </Card>
      <Card title="Project revenue detail" sub={rr.data ? `Month ${rr.data.month}` : ''}>
        {rr.data ? <DataTable rows={rr.data.project_detail as Row[]} empty="No project activity." columns={[{ key: 'project_id' }, { key: 'obligation', chip: true }, { key: 'billed', unit: 'usd' }, { key: 'asc606_revenue', label: 'Earned', unit: 'usd' }, { key: 'adjustment_needed', unit: 'usd' }, { key: 'contract_asset', unit: 'usd' }, { key: 'contract_liability', unit: 'usd' }]} /> : <Loading state={rr} />}
        <Source data={rr.data} />
      </Card>
    </div>
  )
}

// ---- Pricing ---------------------------------------------------------------------------------------------

export function Pricing() {
  const p = useTool('get_pricing_analysis')
  const sims = (p.data?.rows ?? []) as Row[]
  return (
    <div className="page">
      <Head title="Pricing" sub="What a price change does to revenue and margin (with volume elasticity), and where discounts leak."
        ask="Which price change should we make and why? What's the risk if customers are more price-sensitive than assumed?" />
      <Card title="Price-change scenarios" sub="Annualized on the last 3 months · gross margin change after volume response">
        {p.data ? (
          <div style={{ height: 220 }}>
            <ResponsiveContainer>
              <BarChart data={sims} margin={{ left: 8, right: 8, top: 8 }}>
                <CartesianGrid stroke="var(--border)" vertical={false} />
                <XAxis dataKey="scenario" {...AXIS} />
                <YAxis tickFormatter={usd} width={70} {...AXIS} />
                <Tooltip formatter={usd} {...TIP} />
                <ReferenceLine y={0} stroke="var(--faint)" />
                <Bar dataKey="delta_gross_margin" name="Δ gross margin" fill="var(--accent)" radius={[4, 4, 0, 0]} />
                <Bar dataKey="delta_revenue" name="Δ revenue" fill="var(--faint)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : <Loading state={p} />}
        {p.data && <DataTable rows={sims} columns={[{ key: 'scenario' }, { key: 'product_id' }, { key: 'note' }, { key: 'price_change_pct', label: 'Price change', unit: 'ratio' }, { key: 'volume_elasticity', label: 'Elasticity' }, { key: 'delta_revenue', unit: 'usd' }, { key: 'delta_gross_margin', unit: 'usd' }]} />}
        <Source data={p.data} />
      </Card>
      <Card title="Discounts, last 12 months" sub="Volume-tier discounts by segment, against policy">
        {p.data ? <DataTable rows={p.data.discounts_last_12m as Row[]} columns={[{ key: 'segment', chip: true }, { key: 'list_revenue', unit: 'usd' }, { key: 'discount_amount', unit: 'usd' }, { key: 'over_policy', label: 'Months over policy', unit: 'count' }, { key: 'near_tier_cliff', label: 'Months on a tier cliff', unit: 'count' }]} /> : <Loading state={p} />}
      </Card>
    </div>
  )
}

// ---- Capital ---------------------------------------------------------------------------------------------

export function Capital() {
  const c = useTool('get_cap_table_and_fundraise')
  const rounds = (c.data?.fundraise_scenarios ?? []) as Row[]
  return (
    <div className="page">
      <Head title="Cap table & fundraising" sub="Who owns what today, and what each fundraising scenario does to price, dilution and runway."
        ask="Given our runway, which fundraising scenario makes sense, when do we need to start, and what does it cost the founders?" />
      {rounds.some((r) => r.runs_out_before_close) && (
        <div className="error">Cash runs out before the round closes in {rounds.filter((r) => r.runs_out_before_close).map((r) => r.scenario).join(', ')}: a bridge, debt or cuts are needed first.</div>
      )}
      <Card title="Fundraise scenarios" sub="Option pool topped up pre-money to the target · runway from the base forecast">
        {c.data ? <DataTable rows={rounds} columns={[{ key: 'scenario' }, { key: 'round_name', chip: true }, { key: 'close_month' }, { key: 'pre_money', unit: 'usd' }, { key: 'raise_amount', unit: 'usd' }, { key: 'price_per_share', render: (r) => `$${(r.price_per_share as number).toFixed(2)}` }, { key: 'new_investor_pct', unit: 'ratio' }, { key: 'founders_pct_after', label: 'Founders after', unit: 'ratio' }, { key: 'forecast_cash_before_close', label: 'Cash at close', unit: 'usd' }, { key: 'runs_out_before_close', label: 'Too late', flag: 'bad' }]} /> : <Loading state={c} />}
        <Source data={c.data} />
      </Card>
      <Card title="Cap table (fully diluted)">
        {c.data ? <DataTable rows={c.data.rows} columns={[{ key: 'holder' }, { key: 'security_class', chip: true }, { key: 'shares', unit: 'count' }, { key: 'fully_diluted_pct', label: 'Ownership', unit: 'ratio' }, { key: 'invested', unit: 'usd' }, { key: 'issue_date' }]} /> : <Loading state={c} />}
      </Card>
    </div>
  )
}

// ---- Tax & FX ----------------------------------------------------------------------------------------------

export function TaxFx() {
  const t = useTool('get_tax_and_fx')
  return (
    <div className="page">
      <Head title="Tax & FX" sub="Sales tax, VAT and GST collected and due, and FX gains and losses on receivables, by billing currency."
        ask="How much indirect tax do we owe this month, by regime, and how exposed are we to FX on open receivables?" />
      <Card title="This month" sub={t.data ? `Invoices in ${String(t.data.month).slice(0, 7)}` : ''}>
        {t.data ? <DataTable rows={t.data.rows} empty="No invoices this month." columns={[{ key: 'currency', chip: true }, { key: 'tax_regime' }, { key: 'invoices', unit: 'count' }, { key: 'billings_usd', label: 'Billings (USD)', unit: 'usd' }, { key: 'billings_local', label: 'Billings (local)', render: (r) => (r.billings_local as number).toLocaleString(undefined, { maximumFractionDigits: 2 }) }, { key: 'tax_collected_usd', label: 'Tax to remit', unit: 'usd' }, { key: 'tax_remit_due', label: 'Due' }, { key: 'realized_fx', unit: 'usd' }]} /> : <Loading state={t} />}
        <Source data={t.data} />
      </Card>
      <Card title="All time by currency">
        {t.data ? <DataTable rows={t.data.all_time_by_currency as Row[]} columns={[{ key: 'currency', chip: true }, { key: 'billings_usd', label: 'Billings (USD)', unit: 'usd' }, { key: 'tax_collected_usd', label: 'Tax collected', unit: 'usd' }, { key: 'realized_fx', unit: 'usd' }, { key: 'unrealized_fx', label: 'Unrealized FX (open AR)', unit: 'usd' }]} /> : <Loading state={t} />}
      </Card>
    </div>
  )
}

// ---- Alerts --------------------------------------------------------------------------------------------------

export function Alerts() {
  const [status, setStatus] = useState('open')
  const [rows, setRows] = useState<Row[] | null>(null)
  const [error, setError] = useState<string>()
  const { go, refreshKey } = useWorkspace()
  const load = () => api.alerts(status === 'all' ? undefined : status).then(setRows).catch((e) => setError(String(e)))
  useEffect(() => { load() }, [status, refreshKey])  // eslint-disable-line react-hooks/exhaustive-deps
  const ack = (key: string) => api.ackAlert(key).then(load).catch((e) => setError(String(e)))
  return (
    <div className="page">
      <Head title="Alerts" sub="What the morning run flagged: delivered once as a digest (Slack, email or Telegram), logged here until acknowledged or resolved."
        ask="Which alerts need action today, and what should each owner do?" />
      <Card title="Alert log" right={<div className="segmented">{['open', 'acknowledged', 'resolved', 'all'].map((s) => <button key={s} className={status === s ? 'on' : ''} onClick={() => setStatus(s)}>{s}</button>)}</div>}>
        {error && <div className="error">{error}</div>}
        {rows ? <DataTable rows={rows} empty="No alerts here." columns={[
          { key: 'severity', chip: true }, { key: 'rule_id', label: 'Rule' }, { key: 'message' }, { key: 'recipients', label: 'For' },
          { key: 'first_seen', render: (r) => String(r.first_seen ?? '').slice(0, 10) },
          { key: 'page', label: '', render: (r) => <button className="btn small" onClick={() => go(r.page as Page)}>Open</button> },
          { key: 'status', render: (r) => r.status === 'open'
              ? <button className="btn small" onClick={() => ack(String(r.alert_key))}>Acknowledge</button>
              : <Chip value={String(r.status)} kind={r.status === 'resolved' ? 'good' : undefined} /> }]} /> : <div className="muted">Loading…</div>}
      </Card>
    </div>
  )
}

// ---- Deal desk -----------------------------------------------------------------------------------------------

const PRODUCTS = ['batch_base', 'batch_pro', 'stream']

export function DealDesk() {
  const [customer, setCustomer] = useState('New Co')
  const [hours, setHours] = useState<Record<string, number>>({ batch_base: 0, batch_pro: 20000, stream: 10000 })
  const [discount, setDiscount] = useState(10)
  const [term, setTerm] = useState(24)
  const [commit, setCommit] = useState(5000)
  const [ev, setEv] = useState<Row | null>(null)
  const [msg, setMsg] = useState<string>()
  const [deals, setDeals] = useState<Row[]>([])
  const { refreshKey, refresh } = useWorkspace()
  const body = () => ({ customer, discount_pct: discount / 100, term_months: term, monthly_commit: commit,
    lines: PRODUCTS.filter((p) => hours[p] > 0).map((p) => ({ product_id: p, hours_per_month: hours[p] })) })
  const post = (url: string) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body()) }).then((r) => r.json())
  const check = () => post('/api/deals/evaluate').then(setEv)
  const submit = () => post('/api/deals').then((r) => { setMsg(`${r.deal_id}: ${r.status}`); refresh() })
  useEffect(() => { fetch('/api/deals').then((r) => r.json()).then(setDeals) }, [refreshKey])
  const num = (v: number, set: (n: number) => void) => <input type="number" value={v} onChange={(e) => set(Number(e.target.value))} style={{ width: 110 }} />
  const checks = (ev?.checks ?? []) as Row[]
  return (
    <div className="page">
      <Head title="Deal desk" sub="Price a deal with real unit costs, check it against the guardrails, route it for approval and print the quote."
        ask="What's the most discount we can give a 50,000-hour/month streaming deal and stay above the margin floor?" />
      <Card title="Deal">
        <div className="grid cols-3" style={{ gap: 10, alignItems: 'end' }}>
          <label>Customer<br /><input value={customer} onChange={(e) => setCustomer(e.target.value)} /></label>
          {PRODUCTS.map((p) => <label key={p}>{p} hours / month<br />{num(hours[p], (n) => setHours({ ...hours, [p]: n }))}</label>)}
          <label>Discount %<br />{num(discount, setDiscount)}</label>
          <label>Term (months)<br />{num(term, setTerm)}</label>
          <label>Monthly minimum commit $<br />{num(commit, setCommit)}</label>
        </div>
        <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
          <button className="btn" onClick={check}>Check deal</button>
          <button className="btn" onClick={submit} disabled={!ev}>Submit for approval</button>
          {msg && <span className="muted">{msg}</span>}
        </div>
      </Card>
      {ev && !ev.error ? (
        <>
          <div className="grid cols-4">
            <Kpi label="Monthly revenue" value={usd(ev.monthly_revenue)} />
            <Kpi label="Gross margin" value={`${((ev.gross_margin_pct as number) * 100).toFixed(1)}%`} note={`floor ${((ev.floor_pct as number) * 100).toFixed(1)}%`}
              tone={(ev.gross_margin_pct as number) < (ev.floor_pct as number) ? 'bad' : 'good'} />
            <Kpi label="Contract value" value={usd(ev.contract_value)} note={`${ev.term_months} months`} />
            <Kpi label="Routing" value={ev.route === 'auto_approve' ? 'Auto-approve' : 'Finance review'} tone={ev.route === 'auto_approve' ? 'good' : 'bad'} />
          </div>
          <div className="grid cols-2" style={{ alignItems: 'start' }}>
            <Card title="Guardrails">
              <DataTable rows={checks} columns={[{ key: 'rule' }, { key: 'passed', render: (r) => <Chip value={r.passed ? 'pass' : 'fail'} /> }, { key: 'detail' }]} />
            </Card>
            <Card title="Pricing by product">
              <DataTable rows={ev.lines as Row[]} columns={[{ key: 'product_id' }, { key: 'hours_per_month', unit: 'count' }, { key: 'net_price', label: '$/hr', render: (r) => (r.net_price as number).toFixed(4) },
                { key: 'monthly_revenue', unit: 'usd' }, { key: 'gross_margin_pct', unit: 'ratio' }, { key: 'floor_pct', label: 'Floor', unit: 'ratio' }]} />
            </Card>
          </div>
        </>
      ) : null}
      {ev?.error ? <div className="error">{String(ev.error)}</div> : null}
      <Card title="Deals" sub="Approval status comes from the approval card (audited)">
        <DataTable rows={deals} empty="No deals yet." columns={[{ key: 'id' }, { key: 'customer' }, { key: 'route', chip: true },
          { key: 'approval_status', label: 'Status', chip: true }, { key: 'created_at', render: (r) => String(r.created_at).slice(0, 10) },
          { key: 'quote', label: '', render: (r) => <a className="btn small" href={`/api/deals/${r.id}/quote.pdf`} target="_blank" rel="noreferrer">Quote PDF</a> }]} />
      </Card>
    </div>
  )
}

// ---- Commissions -----------------------------------------------------------------------------------------------

export function Commissions() {
  const c = useTool('get_commissions')
  const { ask } = useWorkspace()
  return (
    <div className="page">
      <Head title="Sales commissions" sub="Monthly statements from billed revenue: credited ARR above each account's previous peak, quota attainment, accelerators and clawbacks."
        ask="Summarize this month's commission statements: who earned what, who is above quota, and why." />
      <Card title="Year to date" sub={c.data ? `Through ${String(c.data.month).slice(0, 7)}` : ''}>
        {c.data ? <DataTable rows={c.data.year_to_date as Row[]} columns={[{ key: 'rep_id' }, { key: 'rep_name' }, { key: 'commission_ytd', unit: 'usd' }, { key: 'attainment', label: 'Quota attainment', unit: 'ratio' }]} /> : <Loading state={c} />}
      </Card>
      <Card title="This month's statements" sub="Click a rep to ask about their statement">
        {c.data ? <DataTable rows={c.data.rows} onRow={(r) => ask(`Explain ${r.rep_id}'s commission statement for ${String(r.month).slice(0, 7)}.`)}
          columns={[{ key: 'rep_id' }, { key: 'segment_focus', chip: true }, { key: 'new_arr', unit: 'usd' }, { key: 'expansion_arr', unit: 'usd' }, { key: 'clawback_arr', unit: 'usd' },
            { key: 'quota_attainment_pct', label: 'YTD attainment', unit: 'ratio' }, { key: 'commission_base', unit: 'usd' }, { key: 'commission_accelerator', unit: 'usd' }, { key: 'commission_total', unit: 'usd' }]} /> : <Loading state={c} />}
        <Source data={c.data} />
      </Card>
      <Card title="Credits behind this month">
        {c.data ? <DataTable rows={c.data.credits as Row[]} empty="No credits this month." columns={[{ key: 'rep_id' }, { key: 'customer_id' }, { key: 'credit_type', chip: true }, { key: 'billed_revenue', unit: 'usd' }, { key: 'credited_arr', unit: 'usd' }]} /> : <Loading state={c} />}
      </Card>
    </div>
  )
}
