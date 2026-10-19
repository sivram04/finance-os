// FP&A, treasury, close, pricing, capital and tax pages. Like the module pages, each reads the same read-only
// tools the assistant uses, so a number on a page and in an answer always agree.
import { useEffect, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, fmt, type Row } from '../api'
import { Bars, Columns, Dash, Donut, GroupedBars, KpiRow, Trend, useFiltered } from '../components/Dash'
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
  const [withRaise, setWithRaise] = useState(true)
  const f = useTool('get_forecast', { scenario })
  const all = [useTool('get_forecast', { scenario: 'base' }), useTool('get_forecast', { scenario: 'upside' }), useTool('get_forecast', { scenario: 'downside' })]
  const acc = useTool('get_forecast_accuracy')
  const hc = useTool('get_headcount_plan', { scenario })
  const bb = useTool('get_budget_build')
  const alloc = useTool('get_shared_cost_allocation')
  const summary = (f.data?.scenarios as Row[] | undefined) ?? []
  const cur = summary.find((s) => s.scenario === scenario)
  const cash = all.every((s) => s.data)
    ? (all[0].data!.rows as Row[]).map((r, i) => {
        const k = withRaise ? 'closing_cash_with_raise' : 'closing_cash'
        return { month: r.month, base: r[k], upside: all[1].data!.rows[i]?.[k], downside: all[2].data!.rows[i]?.[k] }
      })
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
      <Card title="Cash by scenario"
        sub={withRaise
          ? "Closing cash including each scenario's planned round: base $30M Series B in Jun 2027, upside $40M in Mar 2027, downside $10M bridge in Mar 2027 (Capital page)"
          : "Closing cash on today's plan with no new money. Below zero means the company must raise or cut before then."}
        right={<div className="segmented"><button className={withRaise ? 'on' : ''} onClick={() => setWithRaise(true)}>With planned raise</button><button className={!withRaise ? 'on' : ''} onClick={() => setWithRaise(false)}>No new money</button></div>}>
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
      <div className="grid cols-2">
        <Card title="Forecast accuracy" sub="Past base forecasts vs what actually closed · positive = forecast too high">
          {acc.data ? <DataTable rows={acc.data.rows} columns={[{ key: 'line' }, { key: 'months_ahead', label: 'Months ahead' }, { key: 'n', label: 'Versions' }, { key: 'avg_error_pct', label: 'Avg error (bias)', unit: 'ratio' }, { key: 'avg_abs_error_pct', label: 'Avg abs error', unit: 'ratio' }]} /> : <Loading state={acc} />}
        </Card>
        <Card title="Hiring plan" sub={`${scenario} scenario · fully loaded cost`}>
          {hc.data ? <DataTable rows={hc.data.planned_roles as Row[]} empty="No roles in this scenario." columns={[{ key: 'role_id' }, { key: 'department_id', label: 'Dept' }, { key: 'title' }, { key: 'start_month' }, { key: 'status', chip: true }, { key: 'monthly_loaded_cost', label: 'Loaded / month', unit: 'usd' }]} /> : <Loading state={hc} />}
        </Card>
      </div>
      <div className="grid cols-2">
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
        <Kpi label="Cash today" value={weeks[0] ? usd(weeks[0].opening_cash) : '…'} note="live books, not month end" />
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
      <div className="grid cols-2">
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

// Close (docs/dashboard_spec.md section 5): will we close on time, and what's blocking it?
const STATE_COLORS: Record<string, string> = { complete: '#2f9e6b', review: '#c98a1b', in_progress: '#3b6fd8', blocked: '#d1495b', overdue: '#d1495b', exceptions: '#d1495b', not_started: '#7a8699' }

export function Close() {
  return <Dash><CloseBody /></Dash>
}

function CloseBody() {
  const cd = useTool('get_close_dashboard')
  const cs = useTool('get_close_status')
  const rr = useTool('get_revenue_recognition')
  const { ask } = useWorkspace()
  const all = (cd.data?.rows ?? []) as Row[]
  const rows = useFiltered(all)
  const recon = (cd.data?.recon ?? []) as Row[]
  const passing = recon.filter((r) => r.status === 'pass').length
  const done = rows.filter((t) => t.state === 'complete').length
  const stuck = rows.filter((t) => t.state !== 'complete')
  const lastWorkday = Math.max(0, ...all.filter((t) => t.state !== 'complete').map((t) => Number(t.workday)))
  if (!cd.data) return <div className="page"><Loading state={cd} /></div>
  return (
    <div className="page">
      <Head title="Month-end close" sub={`Will we close ${String(cd.data.month)} on time, and what's blocking it? Click a slice or bar to filter`}
        ask="Where are we in the month-end close? What's blocking sign-off, who owns it, and what entries still need to be booked?" />
      <KpiRow items={[
        { label: 'Close period', value: String(cd.data.month), note: `books as of ${String(cd.data.as_of)}` },
        { label: 'Tasks complete', value: `${done} / ${rows.length}`, note: `${rows.length ? Math.round((done / rows.length) * 100) : 0}% done`, tone: done === rows.length ? 'good' : 'ok' },
        { label: 'Blocked or overdue', value: String(stuck.filter((t) => t.state === 'blocked' || t.state === 'overdue').length), note: 'need a decision today', tone: stuck.some((t) => t.state === 'blocked' || t.state === 'overdue') ? 'bad' : 'good' },
        { label: 'Open items', value: String(rows.reduce((a, t) => a + Number(t.open_items ?? 0), 0)), note: 'exceptions inside open tasks' },
        { label: 'Reconciliations', value: `${passing} / ${recon.length}`, note: 'passing for the period', tone: passing === recon.length ? 'good' : 'bad' },
        { label: 'Critical path', value: lastWorkday ? `WD ${lastWorkday}` : 'done', note: 'latest workday with open work', tone: lastWorkday > 5 ? 'bad' : null },
      ]} />
      <div className="grid cols-3">
        <Card title="Where the close stands" sub="Tasks by status · click to filter"><Donut rows={all} dim="state" colors={STATE_COLORS} /></Card>
        <Card title="Who has open work" sub="Open tasks by owner · click an owner to filter">
          <Bars rows={all.filter((t) => t.state !== 'complete')} dim="owner"
            stack={{ key: 'state', values: ['blocked', 'overdue', 'review', 'in_progress', 'not_started', 'exceptions'], colors: STATE_COLORS }} />
        </Card>
        <Card title="Workdays to close" sub="Last workday with a completed task, past closes">
          <Columns rows={(cd.data.history ?? []) as Row[]} x="month" y="last_workday_done" unit="count" color="#3b6fd8" />
        </Card>
      </div>
      <Card title="Checklist" sub="Status comes from the evidence (reconciliations, schedules, BvA alerts) · click a task to ask about it">
        <DataTable title="close_checklist" rows={all} onRow={(r) => ask(`Close task ${r.task_id} (${r.task}) is ${r.state}. What does it need and who should act?`)}
          columns={[{ key: 'task_id', label: '#' }, { key: 'workday', label: 'WD' }, { key: 'due_date' }, { key: 'owner' }, { key: 'task' },
            { key: 'state', label: 'Status', render: (r) => <Chip value={String(r.state).replace('_', ' ')} kind={r.state === 'complete' ? 'good' : r.state === 'blocked' || r.state === 'overdue' || r.state === 'exceptions' ? 'bad' : 'warn'} /> },
            { key: 'open_items', unit: 'count' }, { key: 'evidence' }]} />
        <Source data={cd.data} />
      </Card>
      <div className="grid cols-3">
        <Card title="Reconciliations" sub="This period">
          <DataTable rows={recon} columns={[{ key: 'check_name' }, { key: 'status', chip: true }]} />
        </Card>
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

// ---- Capital: fully diluted ownership by default, pre/post-round dilution per scenario --------------------

export function Capital() {
  return <Dash><CapitalBody /></Dash>
}

function CapitalBody() {
  const c = useTool('get_cap_table_and_fundraise')
  const all = (c.data?.rows ?? []) as Row[]
  const rows = useFiltered(all)
  const sc = (c.data?.fundraise_scenarios ?? []) as Row[]
  const fd = all.reduce((a, r) => a + Number(r.shares), 0)
  const share = (pred: (r: Row) => boolean) => all.filter(pred).reduce((a, r) => a + Number(r.shares), 0) / (fd || 1)
  const base = sc.find((s) => s.scenario === 'base')
  const lastPrice = Math.max(0, ...all.map((r) => Number(r.price_per_share ?? 0)))
  if (!c.data) return <div className="page"><Loading state={c} /></div>
  return (
    <div className="page">
      <Head title="Cap table & fundraising" sub="Who owns what (fully diluted, the basis investors price on), and what each round does to ownership and runway · click to filter"
        ask="Walk me through our ownership and each fundraise scenario: price, dilution, the option pool shuffle and runway." />
      <KpiRow items={[
        { label: 'Fully diluted shares', value: fd.toLocaleString(), note: `${rows.length} holdings shown` },
        { label: 'Founders', value: `${(share((r) => String(r.holder).startsWith('Founder')) * 100).toFixed(1)}%`, note: 'fully diluted' },
        { label: 'Investors', value: `${(share((r) => String(r.security_class).startsWith('series')) * 100).toFixed(1)}%` },
        { label: 'Option pool unallocated', value: `${(share((r) => r.security_class === 'options unallocated' || r.security_class === 'options_unallocated') * 100).toFixed(1)}%`, note: 'room to hire before the next round' },
        { label: 'Last price per share', value: lastPrice ? `$${lastPrice.toFixed(2)}` : '—' },
        { label: 'Base case: Series B', value: base ? fmt('amount', Number(base.raise_amount), 'usd') : '—', note: base ? `at ${fmt('amount', Number(base.pre_money), 'usd')} pre · founders → ${(Number(base.founders_pct_after) * 100).toFixed(1)}%` : '' },
      ]} />
      <div className="grid cols-3">
        <Card title="Ownership by holder" sub="Fully diluted · click to filter"><Donut rows={all} dim="holder" measure="shares" unit="count" /></Card>
        <Card title="By security class"><Donut rows={all} dim="security_class" measure="shares" unit="count" /></Card>
        <Card title="Founders before and after each round" sub="Includes the option pool top-up (the shuffle)">
          <GroupedBars rows={sc} dim="scenario" unit="ratio" series={[{ key: 'founders_pct_before', label: 'Founders before', color: '#3b6fd8' }, { key: 'founders_pct_after', label: 'Founders after', color: '#c98a1b' }, { key: 'new_investor_pct', label: 'New investor', color: '#2f9e6b' }]} />
        </Card>
      </div>
      <Card title="Fundraise scenarios" sub="Option pool topped up pre-money to the target · runway from the base forecast">
        <DataTable rows={sc} columns={[{ key: 'scenario', chip: true }, { key: 'round_name' }, { key: 'close_month' }, { key: 'pre_money', unit: 'usd' }, { key: 'raise_amount', unit: 'usd' }, { key: 'price_per_share', unit: 'usd' }, { key: 'option_pool_topup', label: 'Pool top-up', unit: 'count' }, { key: 'new_investor_pct', unit: 'ratio' }, { key: 'founders_pct_after', label: 'Founders after', unit: 'ratio' }, { key: 'forecast_cash_before_close', label: 'Cash at close', unit: 'usd' }, { key: 'runs_out_before_close', label: 'Too late', flag: 'bad' }]} />
      </Card>
      <Card title="Cap table (fully diluted)">
        <DataTable title="cap_table" rows={all} columns={[{ key: 'holder' }, { key: 'security_class', chip: true }, { key: 'shares', unit: 'count' }, { key: 'fully_diluted_pct', label: 'Ownership', unit: 'ratio' }, { key: 'invested', unit: 'usd' }, { key: 'issue_date' }]} />
        <Source data={c.data} />
      </Card>
    </div>
  )
}

// ---- Tax & FX: what we owe each tax authority and what currencies cost us ---------------------------------------

export function TaxFx() {
  return <Dash><TaxBody /></Dash>
}

function TaxBody() {
  const t = useTool('get_tax_dashboard')
  const all = (t.data?.rows ?? []) as Row[]
  const rows = useFiltered(all)
  const months = [...new Set(rows.map((r) => String(r.month)))].sort()
  const last = months.at(-1), year = last?.slice(0, 4)
  const sum = (rs: Row[], k: string) => rs.reduce((a, r) => a + Number(r[k] ?? 0), 0)
  const ytd = rows.filter((r) => String(r.month).startsWith(year ?? '')), lm = rows.filter((r) => r.month === last)
  const usd = (v: number) => fmt('amount', v, 'usd')
  const byMonth = months.map((m) => { const rs = rows.filter((r) => r.month === m); return { month: m, tax: sum(rs, 'tax_collected_usd'), realized: sum(rs, 'realized_fx'), unrealized: sum(rs, 'unrealized_fx_on_open_ar') } })
  const nonUsd = sum(lm.filter((r) => r.currency !== 'USD'), 'billings_usd')
  if (!t.data) return <div className="page"><Loading state={t} /></div>
  return (
    <div className="page">
      <Head title="Tax & FX" sub={`What we owe each tax authority, and what currencies cost us · ${last ?? ''} · click a currency or regime to filter`}
        ask="What sales tax, VAT and GST do we owe and to whom, and how much did FX cost or earn us this year?" />
      <KpiRow items={[
        { label: 'Tax to remit', value: usd(sum(lm, 'tax_collected_usd')), note: `collected in ${last ?? ''} · due by ${String(lm[0]?.tax_remit_due ?? '—')}`, tone: sum(lm, 'tax_collected_usd') > 0 ? 'ok' : null },
        { label: 'Tax collected YTD', value: usd(sum(ytd, 'tax_collected_usd')), note: `${year ?? ''}` },
        { label: 'Billings outside USD', value: usd(nonUsd), note: `${sum(lm, 'billings_usd') ? ((nonUsd / sum(lm, 'billings_usd')) * 100).toFixed(1) : 0}% of last month` },
        { label: 'Realized FX YTD', value: usd(sum(ytd, 'realized_fx')), tone: sum(ytd, 'realized_fx') < 0 ? 'bad' : 'good' },
        { label: 'Unrealized FX on open AR', value: usd(sum(lm, 'unrealized_fx_on_open_ar')), note: 'if rates stay where they are', tone: sum(lm, 'unrealized_fx_on_open_ar') < 0 ? 'bad' : 'good' },
        { label: 'Currencies', value: String(new Set(rows.map((r) => r.currency)).size) },
      ]} />
      <div className="grid cols-3">
        <Card title="Billings by currency" sub="Click to filter"><Donut rows={all} dim="currency" measure="billings_usd" /></Card>
        <Card title="Tax collected by regime" sub="Sales tax, VAT, GST · click to filter"><Bars rows={all} dim="tax_regime" measure="tax_collected_usd" /></Card>
        <Card title="FX gains and losses" sub="By month">
          <Trend rows={byMonth} x="month" series={[{ key: 'realized', label: 'Realized', color: '#3b6fd8' }, { key: 'unrealized', label: 'Unrealized on open AR', color: '#c98a1b', dashed: true }]} refs={[{ y: 0, label: '' }]} />
        </Card>
      </div>
      <Card title="Tax collected by month" sub="Filtered with the page"><Columns rows={byMonth} x="month" y="tax" color="#8a63d2" /></Card>
      <Card title="By month, currency and regime">
        <DataTable title="tax_fx" rows={all} columns={[{ key: 'month' }, { key: 'currency', chip: true }, { key: 'tax_regime', chip: true }, { key: 'invoices', unit: 'count' }, { key: 'billings_usd', unit: 'usd' }, { key: 'tax_collected_usd', unit: 'usd' }, { key: 'tax_remit_due', label: 'Remit by' }, { key: 'realized_fx', unit: 'usd' }, { key: 'unrealized_fx_on_open_ar', label: 'Unrealized FX', unit: 'usd' }]} />
        <Source data={t.data} />
      </Card>
    </div>
  )
}

// ---- Alerts: what needs action, by severity and age ---------------------------------------------------------

export function Alerts() {
  return <Dash><AlertsBody /></Dash>
}

function AlertsBody() {
  const [status, setStatus] = useState('open')
  const [rowsAll, setRows] = useState<Row[] | null>(null)
  const [error, setError] = useState<string>()
  const { go, refreshKey } = useWorkspace()
  const load = () => api.alerts(status === 'all' ? undefined : status).then(setRows).catch((e) => setError(String(e)))
  useEffect(() => { load() }, [status, refreshKey])  // eslint-disable-line react-hooks/exhaustive-deps
  const ack = (key: string) => api.ackAlert(key).then(load).catch((e) => setError(String(e)))
  const all = useMemo(() => (rowsAll ?? []).map((r) => ({ ...r, area: String(r.page ?? 'other'), week: String(r.first_seen ?? '').slice(0, 10) })), [rowsAll])
  const rows = useFiltered(all)
  const now = Date.now()
  const age = (r: Row) => Math.floor((now - new Date(String(r.first_seen)).getTime()) / 864e5)
  const open = rows.filter((r) => r.status === 'open')
  const ruleCounts = rows.reduce<Record<string, number>>((a, r) => { a[String(r.rule_id)] = (a[String(r.rule_id)] ?? 0) + 1; return a }, {})
  return (
    <div className="page">
      <Head title="Alerts" sub="What needs action today? Flagged by the morning run, delivered once as a digest, logged here until acknowledged or resolved · click to filter"
        ask="Which alerts need action today, and what should each owner do?" />
      <KpiRow items={[
        { label: 'Open', value: String(open.length), tone: open.length ? 'ok' : 'good' },
        { label: 'High severity open', value: String(open.filter((r) => r.severity === 'high').length), tone: open.some((r) => r.severity === 'high') ? 'bad' : 'good' },
        { label: 'Oldest open', value: open.length ? `${Math.max(...open.map(age))} d` : '—', note: 'escalate past 30 days', tone: open.some((r) => age(r) > 30) ? 'bad' : null },
        { label: 'Recurring rules', value: String(Object.values(ruleCounts).filter((n) => n > 1).length), note: 'the same rule firing more than once' },
        { label: 'Showing', value: String(rows.length), note: `${status} alerts` },
      ]} />
      <div className="grid cols-3">
        <Card title="By severity" sub="Click to filter"><Donut rows={all} dim="severity" colors={{ high: '#d1495b', medium: '#c98a1b', low: '#7a8699' }} /></Card>
        <Card title="By area" sub="Which page owns it · click to filter"><Bars rows={all} dim="area" /></Card>
        <Card title="By rule" sub="Click to filter"><Bars rows={all} dim="rule_id" top={10} /></Card>
      </div>
      <Card title="Alert log" right={<div className="segmented">{['open', 'acknowledged', 'resolved', 'all'].map((s) => <button key={s} className={status === s ? 'on' : ''} onClick={() => setStatus(s)}>{s}</button>)}</div>}>
        {error && <div className="error">{error}</div>}
        {rowsAll ? <DataTable title="alerts" rows={all} empty="No alerts here." columns={[
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
          <div className="grid cols-2">
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

// ---- Commissions: are we paying for the right results? Attainment, effective rate, clawbacks ------------------

export function Commissions() {
  return <Dash><CommissionsBody /></Dash>
}

function CommissionsBody() {
  const c = useTool('get_commissions_dashboard')
  const all = (c.data?.rows ?? []) as Row[]
  const rows = useFiltered(all)
  const months = [...new Set(all.map((r) => String(r.month)))].sort()
  const last = months.at(-1), year = last?.slice(0, 4)
  const lm = rows.filter((r) => r.month === last), ytd = rows.filter((r) => String(r.month).startsWith(year ?? ''))
  const sum = (rs: Row[], k: string) => rs.reduce((a, r) => a + Number(r[k] ?? 0), 0)
  const usd = (v: number) => fmt('amount', v, 'usd')
  const credited = sum(lm, 'ytd_credited_arr'), paid = sum(ytd, 'commission_total')
  const byMonth = months.filter((m) => m.startsWith(year ?? '')).map((m) => { const rs = rows.filter((r) => r.month === m); return { month: m, commission: sum(rs, 'commission_total') } })
  const lmAll = all.filter((r) => r.month === last)
  if (!c.data) return <div className="page"><Loading state={c} /></div>
  return (
    <div className="page">
      <Head title="Sales commissions" sub={`Are we paying for the right results? ${last ?? ''} · statements from billed revenue · click a rep to filter`}
        ask="Are commissions paying for the right results? Cover attainment by rep, the effective rate, accelerators and clawbacks." />
      <KpiRow items={[
        { label: 'Commission YTD', value: usd(paid), note: `${year ?? ''}` },
        { label: 'Credited ARR YTD', value: usd(credited) },
        { label: 'Effective rate', value: credited ? `${((paid / credited) * 100).toFixed(1)}%` : '—', note: 'commission / credited ARR (not the headline rate)' },
        { label: 'Average attainment', value: lm.length ? `${((sum(lm, 'quota_attainment_pct') / lm.length) * 100).toFixed(0)}%` : '—', note: 'year to date vs annual quota' },
        { label: 'Reps at or above quota', value: `${lm.filter((r) => Number(r.quota_attainment_pct) >= 1).length} / ${lm.length}` },
        { label: 'Clawbacks YTD', value: usd(-sum(ytd, 'commission_clawback')), note: 'churn inside the clawback window', tone: sum(ytd, 'commission_clawback') < 0 ? 'bad' : null },
      ]} />
      <div className="grid cols-3">
        <Card title="Attainment by rep" sub="Year to date vs annual quota · click to filter">
          <Bars rows={lmAll} dim="rep_id" measure="quota_attainment_pct" valueFormat={(v) => `${Math.round(v * 100)}%`} refX={[{ x: 1, label: '100%' }]} />
        </Card>
        <Card title="Commission by month" sub="Filtered with the page"><Columns rows={byMonth} x="month" y="commission" color="#8a63d2" /></Card>
        <Card title="Credits by type" sub="New logos vs expansion, this year"><Donut rows={(c.data.credits ?? []) as Row[]} dim="credit_type" measure="credited_arr" /></Card>
      </div>
      <Card title="Statements" sub="Latest month · filtered with the page">
        <DataTable title="commission_statements" rows={lmAll} columns={[{ key: 'rep_id' }, { key: 'rep_name' }, { key: 'segment_focus', chip: true }, { key: 'new_arr', unit: 'usd' }, { key: 'expansion_arr', unit: 'usd' }, { key: 'clawback_arr', unit: 'usd' },
          { key: 'ytd_credited_arr', unit: 'usd' }, { key: 'annual_quota_arr', unit: 'usd' }, { key: 'quota_attainment_pct', label: 'Attainment', unit: 'ratio' }, { key: 'commission_total', unit: 'usd' }]} />
        <Source data={c.data} />
      </Card>
      <Card title="Credits this year" sub="Which customers earned the credit">
        <DataTable rows={(c.data.credits ?? []) as Row[]} columns={[{ key: 'rep_id' }, { key: 'customer_id' }, { key: 'credit_type', chip: true }, { key: 'billed_revenue', unit: 'usd' }, { key: 'credited_arr', unit: 'usd' }]} />
      </Card>
    </div>
  )
}

// ---- Recurring reports ---------------------------------------------------------------------------------------

export function Reports() {
  const [data, setData] = useState<{ schedule: Row[]; saved: Row[] } | null>(null)
  const [open, setOpen] = useState<Row | null>(null)
  const [md, setMd] = useState<string>('')
  const [busy, setBusy] = useState<string>()
  const load = () => fetch('/api/reports').then((r) => r.json()).then(setData)
  useEffect(() => { load() }, [])
  useEffect(() => {
    if (open) fetch(`/api/reports/${open.period}/${open.report_id}`).then((r) => r.json()).then((j) => setMd(String(j.markdown ?? '')))
  }, [open])
  const runNow = (id: string) => { setBusy(id); fetch(`/api/reports/${id}/run`, { method: 'POST' }).then(load).finally(() => setBusy(undefined)) }
  return (
    <div className="page">
      <Head title="Reports" sub="Recurring reports, built from the warehouse every morning and delivered on schedule (Slack, email or Telegram when configured)."
        ask="Summarize this week's reports: what changed and what needs action?" />
      <Card title="Schedule" sub="seeds/report_schedule.csv">
        {data ? <DataTable rows={data.schedule} columns={[{ key: 'name' }, { key: 'cadence', chip: true }, { key: 'recipients' }, { key: 'description' },
          { key: 'run', label: '', render: (r) => <button className="btn small" disabled={busy === r.report_id} onClick={() => runNow(String(r.report_id))}>{busy === r.report_id ? 'Running…' : 'Run now'}</button> }]} /> : <div className="muted">Loading…</div>}
      </Card>
      <div className="grid cols-2">
        <Card title="Sent reports" sub="Click one to read it">
          {data ? <DataTable rows={data.saved} empty="Nothing sent yet." onRow={setOpen} columns={[{ key: 'name' }, { key: 'period' }, { key: 'saved_at', label: 'Saved' }]} /> : null}
        </Card>
        <Card title={open ? `${open.name} · ${open.period}` : 'Report'}>
          {open ? <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{md}</ReactMarkdown></div> : <div className="muted">Pick a report.</div>}
        </Card>
      </div>
    </div>
  )
}


// ---- Financials: the three statements as a spreadsheet, and the whole workbook as .xlsx ---------------------

const SHEETS = ['Income statement', 'Balance sheet', 'Cash flow'] as const
const colName = (i: number) => (i >= 26 ? String.fromCharCode(64 + Math.floor(i / 26)) : '') + String.fromCharCode(65 + (i % 26))

function cell(v: unknown, unit: string) {
  if (v == null) return ''
  const n = v as number
  if (unit === 'ratio') return `${(n * 100).toFixed(1)}%`
  if (Math.abs(n) < 0.5) return '–'
  const s = Math.round(Math.abs(n)).toLocaleString('en-US')
  return n < 0 ? `(${s})` : s
}

export function Financials() {
  const [period, setPeriod] = useState<'month' | 'quarter' | 'year'>('month')
  const [sheet, setSheet] = useState<(typeof SHEETS)[number]>('Income statement')
  const [sel, setSel] = useState<{ r: number; c: number } | null>(null)
  const count = period === 'month' ? 12 : period === 'quarter' ? 8 : 3
  const d = useTool('get_financial_statements', { period, periods: count })
  const periods = (d.data?.periods as string[] | undefined) ?? []
  const rows = ((d.data?.rows ?? []) as Row[]).filter((r) => r.sheet === sheet)
  const selRow = sel ? rows[sel.r] : undefined
  const selVal = sel && selRow ? (sel.c === 0 ? String(selRow.line) : selRow[periods[sel.c - 1]]) : undefined
  const shown = selVal == null ? '' : typeof selVal === 'number'
    ? (selRow?.unit === 'ratio' ? `${(selVal * 100).toFixed(2)}%` : (Math.abs(selVal) < 0.005 ? 0 : selVal).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }))
    : String(selVal)
  return (
    <div className="page">
      <Head title="Financials" sub="Income statement, balance sheet and cash flow from the general ledger, closed months only. Download the full workbook for Excel."
        ask="Walk me through the financial statements: what changed this quarter in revenue, margins, cash and working capital?" />
      <Card
        title={<div className="segmented">{SHEETS.map((s) => <button key={s} className={sheet === s ? 'on' : ''} onClick={() => { setSheet(s); setSel(null) }}>{s}</button>)}</div>}
        right={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <div className="segmented">{(['month', 'quarter', 'year'] as const).map((p) => <button key={p} className={period === p ? 'on' : ''} onClick={() => { setPeriod(p); setSel(null) }}>{p === 'month' ? 'Monthly' : p === 'quarter' ? 'Quarterly' : 'Annual'}</button>)}</div>
            <a className="btn small primary" href={`/api/financials.xlsx?period=${period}&periods=${count}`}>Download Excel</a>
          </div>}>
        <div className="formula-bar">
          <span className="ref">{sel ? `${colName(sel.c)}${sel.r + 1}` : ''}</span>
          <span className="fx">fx</span>
          <span>{shown}{sel && sel.c > 0 && selRow ? <span className="faint"> · {String(selRow.line)}, {periods[sel.c - 1]}</span> : null}</span>
        </div>
        {d.data ? (
          <div className="sheet-wrap">
            <table className="sheet">
              <thead>
                <tr><th className="corner" />{['', ...periods].map((_, i) => <th key={i} className="col-letter">{colName(i)}</th>)}</tr>
                <tr><th className="rownum" /><th className="line">{sheet}</th>{periods.map((p) => <th key={p} className="num">{p}</th>)}</tr>
              </thead>
              <tbody>
                {rows.map((r, ri) => (
                  <tr key={ri} className={`s-${r.style}`}>
                    <td className="rownum">{ri + 1}</td>
                    <td className={`line ${sel?.r === ri && sel.c === 0 ? 'sel' : ''}`} onClick={() => setSel({ r: ri, c: 0 })}>{String(r.line)}</td>
                    {periods.map((p, ci) => {
                      const v = r[p] as number | null
                      return <td key={p} className={`num ${v != null && v < 0 ? 'neg' : ''} ${sel?.r === ri && sel.c === ci + 1 ? 'sel' : ''}`}
                        onClick={() => setSel({ r: ri, c: ci + 1 })}>{r.style === 'header' ? '' : cell(v, String(r.unit))}</td>
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Loading state={d} />}
        <Source data={d.data} />
      </Card>
    </div>
  )
}


// ---- Analysis: unit economics, cost structure, price/volume/mix, sensitivity, long-range plan, business cases ----

const pct = (v: unknown) => (v == null ? '—' : `${((v as number) * 100).toFixed(1)}%`)

function BusinessCase() {
  const [mode, setMode] = useState<'campaign' | 'investment'>('campaign')
  const [spend, setSpend] = useState(500000)
  const [customers, setCustomers] = useState(40)
  const [years, setYears] = useState(3)
  const [inflows, setInflows] = useState('200000, 250000, 250000')
  const [rate, setRate] = useState(15)
  const [out, setOut] = useState<Row | null>(null)
  const [err, setErr] = useState<string>()
  const run = () => {
    setErr(undefined)
    const args = mode === 'campaign'
      ? { tool: 'evaluate_marketing_campaign', a: { spend, new_customers: customers, years, discount_rate: rate / 100 } }
      : { tool: 'evaluate_business_case', a: { investment: spend, annual_inflows: inflows.split(',').map((x) => Number(x.trim())).filter((x) => !Number.isNaN(x)), discount_rate: rate / 100 } }
    api.data(args.tool, args.a).then((r) => setOut(r as unknown as Row)).catch((e) => setErr(String(e)))
  }
  useEffect(run, [])  // eslint-disable-line react-hooks/exhaustive-deps
  const num = (v: number, set: (n: number) => void, step = 1000) => <input type="number" className="table-search" style={{ width: 130 }} step={step} value={v} onChange={(e) => set(Number(e.target.value))} />
  return (
    <Card title="Business case" sub="NPV, IRR and payback at the hurdle rate. A campaign uses what recently won customers pay, today's gross margin and churn."
      right={<div className="segmented"><button className={mode === 'campaign' ? 'on' : ''} onClick={() => setMode('campaign')}>Marketing campaign</button><button className={mode === 'investment' ? 'on' : ''} onClick={() => setMode('investment')}>Investment</button></div>}>
      <div className="form-row">
        <label>{mode === 'campaign' ? 'Spend' : 'Investment today'} ($){num(spend, setSpend)}</label>
        {mode === 'campaign'
          ? <><label>New customers{num(customers, setCustomers, 1)}</label><label>Years{num(years, setYears, 1)}</label></>
          : <label>Net cash back each year ($, comma separated)<input className="table-search" style={{ width: 260 }} value={inflows} onChange={(e) => setInflows(e.target.value)} /></label>}
        <label>Hurdle rate (%){num(rate, setRate, 1)}</label>
        <button className="btn primary" onClick={run}>Evaluate</button>
      </div>
      {err && <div className="muted">{err}</div>}
      {out && (
        <>
          <div className="grid cols-4" style={{ margin: '12px 0' }}>
            <Kpi label="NPV" value={usd(out.npv)} tone={(out.npv as number) > 0 ? 'good' : 'bad'} />
            <Kpi label="IRR" value={out.irr == null ? 'n/a' : pct(out.irr)} />
            <Kpi label="Payback" value={out.payback_years == null ? 'Never' : `${(out.payback_years as number).toFixed(1)} yrs`} />
            <Kpi label="Verdict" value={(out.npv as number) > 0 ? 'Invest' : "Don't"} note={String(out.verdict)} tone={(out.npv as number) > 0 ? 'good' : 'bad'} />
          </div>
          <DataTable rows={out.rows as unknown as Row[]} columns={[{ key: 'year' }, { key: 'cash_flow', unit: 'usd' }, { key: 'discounted', label: 'Discounted', unit: 'usd' }, { key: 'cumulative', unit: 'usd' }]} />
        </>
      )}
    </Card>
  )
}

export function Analysis() {
  const saas = useTool('get_saas_metrics', { months: 12 })
  const cost = useTool('get_cost_behavior', { months: 12 })
  const pvm = useTool('get_revenue_pvm')
  const sens = useTool('get_runway_sensitivity')
  const lrp = useTool('get_long_range_plan')
  const last = (saas.data?.rows as Row[] | undefined)?.at(-1)
  const lc = (cost.data?.rows as Row[] | undefined)?.at(-1)
  const tot = (pvm.data?.total ?? {}) as Row
  const bridge = pvm.data ? [{ step: 'Price', v: tot.price_effect }, { step: 'Volume', v: tot.volume_effect }, { step: 'Mix', v: tot.mix_effect }, { step: 'Total change', v: tot.revenue_change }] : []
  return (
    <div className="page">
      <Head title="Analysis" sub="Unit economics, cost structure and breakeven, revenue bridge, runway sensitivity, the five-year plan and business cases."
        ask="Give me a CFO read of our unit economics: CAC, LTV:CAC, payback, Rule of 40, breakeven and where the leverage is." />
      <div className="grid cols-4">
        <Kpi label="LTV : CAC" value={last?.ltv_to_cac != null ? `${(last.ltv_to_cac as number).toFixed(1)}x` : '—'} note={last ? `LTV ${usd(last.ltv)} · CAC ${usd(last.cac)}` : ''} tone={last && (last.ltv_to_cac as number) >= 3 ? 'good' : 'bad'} />
        <Kpi label="CAC payback" value={last?.cac_payback_months != null ? `${(last.cac_payback_months as number).toFixed(1)} mo` : '—'} tone={last && (last.cac_payback_months as number) <= 18 ? 'good' : 'bad'} />
        <Kpi label="Rule of 40" value={last ? `${((last.rule_of_40 as number) * 100).toFixed(0)}` : '—'} note={last ? `growth ${pct(last.revenue_growth_yoy)} + EBITDA margin ${pct(last.ebitda_margin)}` : ''} tone={last && (last.rule_of_40 as number) >= 0.4 ? 'good' : 'bad'} />
        <Kpi label="Breakeven revenue / month" value={lc ? usd(lc.breakeven_revenue) : '—'} note={lc ? `revenue ${usd(lc.revenue)} · margin of safety ${pct(lc.margin_of_safety)}` : ''} />
      </div>

      <Card title="SaaS unit economics" sub="CAC on trailing 3 months; LTV = ARPA × gross margin / monthly churn">
        {saas.data ? <DataTable title="saas_metrics" rows={[...saas.data.rows].reverse()} columns={[{ key: 'month' }, { key: 'arr', unit: 'usd' }, { key: 'new_customers', label: 'New' }, { key: 'cac', label: 'CAC', unit: 'usd' }, { key: 'arpa', label: 'ARPA', unit: 'usd' }, { key: 'ltv', label: 'LTV', unit: 'usd' }, { key: 'ltv_to_cac', label: 'LTV:CAC' }, { key: 'cac_payback_months', label: 'Payback (mo)' }, { key: 'revenue_growth_yoy', label: 'Growth YoY', unit: 'ratio' }, { key: 'rule_of_40', label: 'Rule of 40', unit: 'ratio' }, { key: 'free_cash_flow', label: 'Free cash flow', unit: 'usd' }]} /> : <Loading state={saas} />}
      </Card>

      <div className="grid cols-2">
        <Card title="Cost structure and breakeven" sub="Fixed vs variable (seeds/cost_behavior.csv), contribution margin, operating leverage">
          {cost.data ? (
            <>
              <div style={{ height: 220 }}>
                <ResponsiveContainer>
                  <BarChart data={cost.data.rows} margin={{ left: 8, right: 8, top: 8 }}>
                    <CartesianGrid stroke="var(--border)" vertical={false} />
                    <XAxis dataKey="month" {...AXIS} />
                    <YAxis tickFormatter={usd} width={64} {...AXIS} />
                    <Tooltip formatter={usd} {...TIP} />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Bar dataKey="variable_costs" name="Variable costs" stackId="c" fill="var(--accent)" fillOpacity={0.55} />
                    <Bar dataKey="fixed_costs" name="Fixed costs" stackId="c" fill="var(--faint)" fillOpacity={0.6} radius={[3, 3, 0, 0]} />
                    <Line dataKey="revenue" name="Revenue" stroke="var(--good, #2f9e6b)" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <DataTable rows={[...cost.data.rows].reverse()} columns={[{ key: 'month' }, { key: 'contribution_margin', unit: 'usd' }, { key: 'cm_ratio', label: 'CM %', unit: 'ratio' }, { key: 'breakeven_revenue', label: 'Breakeven', unit: 'usd' }, { key: 'operating_leverage', label: 'Op. leverage' }]} />
            </>
          ) : <Loading state={cost} />}
        </Card>
        <Card title="Revenue bridge: price, volume, mix" sub={pvm.data ? `Usage revenue, ${String(pvm.data.month).slice(0, 7)} vs the month before` : ''}>
          {pvm.data ? (
            <>
              <div style={{ height: 220 }}>
                <ResponsiveContainer>
                  <BarChart data={bridge} margin={{ left: 8, right: 8, top: 8 }}>
                    <CartesianGrid stroke="var(--border)" vertical={false} />
                    <XAxis dataKey="step" {...AXIS} />
                    <YAxis tickFormatter={usd} width={64} {...AXIS} />
                    <Tooltip formatter={usd} {...TIP} />
                    <ReferenceLine y={0} stroke="var(--faint)" />
                    <Bar dataKey="v" name="Effect" fill="var(--accent)" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <DataTable rows={pvm.data.rows} columns={[{ key: 'product_id' }, { key: 'revenue', unit: 'usd' }, { key: 'revenue_change', label: 'Change', unit: 'usd' }, { key: 'price_effect', label: 'Price', unit: 'usd' }, { key: 'volume_effect', label: 'Volume', unit: 'usd' }, { key: 'mix_effect', label: 'Mix', unit: 'usd' }]} />
            </>
          ) : <Loading state={pvm} />}
        </Card>
      </div>

      <Card title="Runway sensitivity" sub={sens.data ? `Months until cash runs out with no new money. Rows: monthly revenue growth (today ${pct((sens.data.base as Row).revenue_growth_monthly)}). Columns: change in opex.` : ''}>
        {sens.data ? <DataTable rows={sens.data.rows} columns={Object.keys(sens.data.rows[0] ?? {}).map((k) => k === 'revenue_growth_monthly'
          ? { key: k, label: 'Revenue growth / month', unit: 'ratio' as const }
          : { key: k, label: k, render: (r: Row) => (typeof r[k] === 'number' ? `${r[k]} months` : `${String(r[k])} months`) })} /> : <Loading state={sens} />}
      </Card>

      <Card title="Five-year plan" sub="From the trailing 12 months; assumptions in seeds/lrp_assumptions.csv; base-case raise included">
        {lrp.data ? (
          <>
            <div style={{ height: 240 }}>
              <ResponsiveContainer>
                <BarChart data={lrp.data.rows} margin={{ left: 8, right: 8, top: 8 }}>
                  <CartesianGrid stroke="var(--border)" vertical={false} />
                  <XAxis dataKey="year" {...AXIS} />
                  <YAxis tickFormatter={usd} width={70} {...AXIS} />
                  <Tooltip formatter={usd} {...TIP} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <ReferenceLine y={0} stroke="var(--faint)" />
                  <Bar dataKey="revenue" name="Revenue" fill="var(--accent)" radius={[3, 3, 0, 0]} />
                  <Bar dataKey="ebitda" name="EBITDA" fill="var(--good, #2f9e6b)" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <DataTable rows={lrp.data.rows} columns={[{ key: 'year' }, { key: 'revenue', unit: 'usd' }, { key: 'revenue_growth', label: 'Growth', unit: 'ratio' }, { key: 'gross_margin_pct', label: 'GM %', unit: 'ratio' }, { key: 'ebitda', unit: 'usd' }, { key: 'ebitda_margin', label: 'EBITDA %', unit: 'ratio' }, { key: 'free_cash_flow', unit: 'usd' }, { key: 'financing', unit: 'usd' }, { key: 'closing_cash', unit: 'usd' }, { key: 'rule_of_40', label: 'Rule of 40', unit: 'ratio' }]} />
          </>
        ) : <Loading state={lrp} />}
      </Card>

      <BusinessCase />
    </div>
  )
}
