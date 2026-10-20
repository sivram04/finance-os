// FP&A, treasury, close, pricing, capital and tax pages. Like the module pages, each reads the same read-only
// tools the assistant uses, so a number on a page and in an answer always agree.
import { useEffect, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, fmt, type Row } from '../api'
import { Bars, Columns, Dash, Donut, GroupedBars, KpiRow, Trend, useFiltered } from '../components/Dash'
import { AskButton, Card, Chip, DataTable, Loading, Source, useTool, useWorkspace, type Page } from '../components/common'
import { ForecastErrorByDriver } from './Insights'
import { CountText } from '../components/Motion'

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
      <div className="value" style={tone ? { color: tone === 'bad' ? 'var(--bad, #d1495b)' : 'var(--good, #2f9e6b)' } : undefined}><CountText text={value} /></div>
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
        <Kpi label="Runway (no new money)" value={cur ? (cur.runway_months != null ? `${String(cur.runway_months)} mo` : '5+ years') : '…'} note="months until projected cash goes below zero" tone={cur && cur.runway_months != null && (cur.runway_months as number) < 18 ? 'bad' : cur ? 'good' : undefined} />
        <Kpi label="Cash runs out" value={cur ? (cur.cash_out_month ? String(cur.cash_out_month).slice(0, 7) : 'Not within 5 years') : '…'} tone={cur?.cash_out_month ? 'bad' : 'good'} />
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
      <ForecastChanges scenario={scenario} />
      <ForecastErrorByDriver />
      <div className="grid cols-2">
        <Card title="Forecast accuracy" sub="Past base forecasts vs what actually closed · positive = forecast too high">
          {acc.data ? <DataTable rows={acc.data.rows} columns={[{ key: 'line' }, { key: 'months_ahead', label: 'Months ahead' }, { key: 'n', label: 'Versions' }, { key: 'avg_error_pct', label: 'Avg error (bias)', unit: 'ratio' }, { key: 'avg_abs_error_pct', label: 'Avg abs error', unit: 'ratio' }]} /> : <Loading state={acc} />}
        </Card>
        <Card title="Hiring plan" sub={`${scenario} scenario · fully loaded cost`}>
          {hc.data ? <DataTable rows={hc.data.planned_roles as Row[]} empty="No roles in this scenario." columns={[{ key: 'role_id' }, { key: 'department_id', label: 'Dept' }, { key: 'title' }, { key: 'start_month' }, { key: 'status', chip: true }, { key: 'monthly_loaded_cost', label: 'Loaded / month', unit: 'usd' }]} /> : <Loading state={hc} />}
        </Card>
      </div>
      {hc.data?.workforce ? (
        <Card title="Workforce plan, risk-adjusted" sub={`Base plan vs what is likely: hiring odds and slippage by req status, attrition with backfill lag, April merit, recruiting and equipment · next 12 months ${usd((hc.data.workforce_next_12m as Row).expected_people_cost)} vs plan ${usd((hc.data.workforce_next_12m as Row).plan_payroll)}`}>
          <div className="grid cols-2">
            <Trend rows={hc.data.workforce as Row[]} x="month" series={[{ key: 'plan_payroll', label: 'Plan payroll', color: '#7a8699', dashed: true }, { key: 'expected_people_cost', label: 'Expected people cost' }]} />
            <DataTable rows={hc.data.workforce_by_department as Row[]} columns={[{ key: 'department_id', label: 'Dept' }, { key: 'attrition_rate', label: 'Attrition (planning)', unit: 'ratio' }, { key: 'measured_attrition', label: 'Measured', unit: 'ratio' }, { key: 'plan_headcount', label: 'Plan heads (12 mo)', unit: 'count' }, { key: 'expected_headcount', label: 'Expected heads' }, { key: 'variance_to_plan', label: 'Monthly cost vs plan', unit: 'usd' }]} />
          </div>
          <Source data={hc.data} />
        </Card>
      ) : null}
      {hc.data?.employees ? (
        <Card title="By employee and open role" sub={`Next 12 months, probability-weighted · promotions ${usd((hc.data.workforce_next_12m as Row).promotion_cost)} · employer tax on vesting equity ${usd((hc.data.workforce_next_12m as Row).equity_employer_cost)} · all-in people cost ${usd((hc.data.workforce_next_12m as Row).expected_people_cost_all_in)}`}>
          <DataTable title="workforce_employees" rows={hc.data.employees as Row[]} columns={[{ key: 'employee_id', label: 'ID' }, { key: 'employee_name', label: 'Name' }, { key: 'department_id', label: 'Dept', chip: true }, { key: 'title' }, { key: 'kind', chip: true },
            { key: 'stay_or_fill_probability', label: 'Stay / fill prob.', unit: 'ratio' }, { key: 'salary_after_review', label: 'Salary after review', unit: 'usd' }, { key: 'expected_cost_12m', label: 'Expected cost (12 mo)', unit: 'usd' },
            { key: 'promotion_cost_12m', label: 'Promotions', unit: 'usd' }, { key: 'equity_employer_cost_12m', label: 'Equity tax', unit: 'usd' }]} />
        </Card>
      ) : null}
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

// This close's forecast vs the forecast as it stood at the previous close: same engine and levers, so every change
// comes from the data (the starting-point table says which).
function ForecastChanges({ scenario }: { scenario: string }) {
  const c = useTool('get_forecast_changes', { scenario })
  if (!c.data) return <Card title="Forecast vs last close"><Loading state={c} /></Card>
  const sm = c.data.summary as { now: Row; prior_close: Row; revenue_next_12m_change: number }
  const snaps = (c.data.snapshots ?? []) as Row[]
  return (
    <Card title="Forecast vs last close" sub={`${scenario} scenario as of ${String(c.data.as_of)} vs as of ${String(c.data.prior_as_of)} · next-12-month revenue ${sm.revenue_next_12m_change >= 0 ? '+' : '−'}${usd(Math.abs(sm.revenue_next_12m_change))}${snaps.length ? ` · ${snaps.length} daily snapshot(s) stored` : ''}`}>
      <div className="grid cols-2">
        <Trend rows={c.data.rows as Row[]} x="month" series={[{ key: 'revenue', label: 'This close' }, { key: 'prior_revenue', label: 'Last close', color: '#7a8699', dashed: true }]} />
        <DataTable rows={c.data.starting_point as Row[]} columns={[{ key: 'driver', label: 'Starting point' }, { key: 'now', render: (r) => fmtDriver(r, 'now') }, { key: 'prior_close', label: 'Last close', render: (r) => fmtDriver(r, 'prior_close') }, { key: 'change', render: (r) => fmtDriver(r, 'change') }]} />
      </div>
      <Source data={c.data} />
    </Card>
  )
}

function fmtDriver(r: Row, k: string) {
  const v = Number(r[k])
  return ['cogs_pct', 'existing_net_monthly'].includes(String(r.driver)) ? `${(v * 100).toFixed(2)}%` : usd(v)
}

// ---- Cash: 13-week forecast, accounts, covenants, payment runs, working capital ------------------------


function SweepCard() {
  const sw = useTool('get_treasury_sweep')
  const d = sw.data
  return (
    <Card title="Cash sweeps (simulated)" sub={d ? `Operating account held at ${String((d.policy as Row).target_weeks)} weeks of outflows (never below ${String((d.policy as Row).floor_weeks)}); excess to the money market; surplus into T-bills · interest over 13 weeks ${usd(d.interest_13w)} (${usd(d.interest_annualized)} a year)` : ''}>
      {d ? (
        <div className="grid cols-2">
          <Trend rows={d.rows as Row[]} x="week_start" series={[{ key: 'operating', label: 'Operating', color: '#7a8699' }, { key: 'money_market', label: 'Money market', color: '#3b6fd8' }, { key: 'treasury_bills', label: 'T-bills', color: '#2f9e6b' }]} />
          <div>
            <DataTable rows={(d.by_entity ?? []) as Row[]} columns={[{ key: 'entity_name', label: 'Entity (bank)' }, { key: 'currency' }, { key: 'cash_local', label: 'Cash, local', render: (r) => `${Number(r.cash_local).toLocaleString('en-US', { maximumFractionDigits: 0 })} ${String(r.currency)}` }, { key: 'cash_usd', label: 'Cash, USD', unit: 'usd' }]} />
            <DataTable rows={(d.rows as Row[]).slice(0, 6)} columns={[{ key: 'week_start', label: 'Week' }, { key: 'net_flow', unit: 'usd' }, { key: 'sweep_to_mmf', label: 'Sweep (+ out / − in)', unit: 'usd' }, { key: 'to_tbills', label: 'To T-bills', unit: 'usd' }, { key: 'operating_weeks', label: 'Operating (weeks)' }]} />
          </div>
        </div>
      ) : <Loading state={sw} />}
    </Card>
  )
}

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
        <SweepCard />
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

// Close: the controller's review (docs/dashboard_spec.md section 5). Is every number booked (accruals, prepaids,
// depreciation), does every balance sheet account tie to its support, and why did each line move (flux)? The task
// checklist supports this; it is not the headline.

export function Close() {
  return <Dash><CloseBody /></Dash>
}

function CloseBody() {
  const cr = useTool('get_close_review')
  const { ask } = useWorkspace()
  const d = cr.data
  const usd = (v: unknown) => fmt('amount', v as number, 'usd')
  const flux: Row[] = ((d?.rows ?? []) as Row[]).map((f) => ({ ...f, flag: f.needs_explanation ? 'needs explanation' : f.material ? 'material, explained' : 'below threshold' }))
  const recs = (d?.reconciliations ?? []) as Row[]
  const acc = (d?.accruals ?? []) as Row[]
  const tasks = ((d?.tasks ?? []) as Row[]).map((t) => ({ ...t, state: t.status === 'complete' ? 'complete' : String(t.status) }))
  const journals = (d?.journals ?? []) as Row[]
  const rr = d?.revenue_rollforward as Row | null | undefined
  const thisMonth = acc.filter((a) => a.month === d?.month), lastMonth = acc.filter((a) => a.month === d?.prior_month)
  const trueUp = lastMonth.reduce((x, a) => x + Math.abs(Number(a.true_up ?? 0)), 0), lastAcc = lastMonth.reduce((x, a) => x + Number(a.accrued_amount), 0)
  const recOk = recs.filter((r) => r.status === 'reconciled' || r.status === 'no activity').length
  const toExplain = flux.filter((f) => f.needs_explanation).length
  const manual = journals.filter((j) => j.is_manual)
  const done = tasks.filter((t) => t.state === 'complete').length
  if (!d) return <div className="page"><Loading state={cr} /></div>
  return (
    <div className="page">
      <Head title={`Month-end close · ${String(d.month)}`} sub="Is every number booked, reconciled and explained? Accruals, balance sheet reconciliations and flux first; the task list supports them"
        ask={`Review the ${String(d.month)} close like a controller: what is not booked, which balance sheet accounts don't tie and why, which movements need explaining, and what blocks sign-off.`} />
      <KpiRow items={[
        { label: 'Accrued at month end', value: usd(thisMonth.reduce((x, a) => x + Number(a.accrued_amount), 0)), note: `${thisMonth.length} vendor accruals, auto-reversing` },
        { label: 'Accrual accuracy', value: lastAcc ? `${(100 - (trueUp / lastAcc) * 100).toFixed(1)}%` : '—', note: `last month's true-ups ${usd(trueUp)}`, tone: lastAcc && trueUp / lastAcc > 0.05 ? 'bad' : 'good' },
        { label: 'Balance sheet reconciled', value: `${recOk} / ${recs.length}`, note: `${recs.filter((r) => r.status === 'explained').length} explained differences`, tone: recs.some((r) => r.status === 'difference') ? 'bad' : recs.some((r) => r.status === 'explained') ? 'ok' : 'good' },
        { label: 'Flux to explain', value: String(toExplain), note: `material: |change| ≥ $25K and ≥ 10% · ${flux.filter((f) => f.material).length} material`, tone: toExplain ? 'bad' : 'good' },
        { label: 'Manual journals', value: String(manual.reduce((x, j) => x + Number(j.entries), 0)), note: manual.length ? usd(manual.reduce((x, j) => x + Number(j.amount), 0)) : 'none this month', tone: manual.length ? 'ok' : 'good' },
        { label: 'ASC 606 entry to book', value: rr ? usd(rr.revenue_adjustment) : '—', note: 'recognized vs billed on projects' },
      ]} />

      <Card title="Balance sheet reconciliations" sub="Each account's GL balance against its independent support · differences must be explained before sign-off">
        <DataTable rows={recs} columns={[{ key: 'account' }, { key: 'gl_balance', label: 'GL balance', unit: 'usd' }, { key: 'support', label: 'Reconciled to' }, { key: 'support_balance', label: 'Support balance', unit: 'usd' },
          { key: 'difference', unit: 'usd' }, { key: 'status', render: (r) => <Chip value={String(r.status)} kind={r.status === 'reconciled' || r.status === 'no activity' ? 'good' : r.status === 'explained' ? 'warn' : 'bad'} /> },
          { key: 'explanation', render: (r) => <span className="muted" style={{ whiteSpace: 'normal' }}>{String(r.explanation ?? '')}</span> }]} />
      </Card>

      <div className="grid cols-2">
        <Card title={`What moved: ${String(d.prior_month)} to ${String(d.month)}`} sub="Largest movements, P&L and balance sheet · click an account to filter the flux table">
          <Bars rows={flux} dim="account_name" measure="change" signed top={10} />
        </Card>
        <Card title="Accruals" sub="Booked at month end before the invoice arrives, reversed when it does; true-up = invoice minus accrual">
          <GroupedBars rows={acc.map((a) => ({ ...a, key: `${a.vendor_id} ${String(a.month).slice(5)}` }))} dim="key"
            series={[{ key: 'accrued_amount', label: 'Accrued', color: '#3b6fd8' }, { key: 'billed_amount', label: 'Invoiced', color: '#2f9e6b' }]} height={190} />
          <DataTable rows={acc} columns={[{ key: 'month' }, { key: 'vendor_id', label: 'Vendor' }, { key: 'accrued_amount', label: 'Accrued', unit: 'usd' }, { key: 'billed_amount', label: 'Invoiced', unit: 'usd' }, { key: 'true_up', unit: 'usd' }, { key: 'status', chip: true }]} />
        </Card>
      </div>

      <Card title="Flux analysis" sub="Every line vs last month · material movements (|change| ≥ $25K and ≥ 10%) need an explanation before sign-off · click a row to ask">
        <DataTable title="flux" rows={flux} onRow={(r) => ask(`Explain the movement in ${r.account_name} from ${String(d.prior_month)} to ${String(d.month)}.`)} columns={[
          { key: 'account_name', label: 'Account' }, { key: 'account_type', label: 'Type', chip: true }, { key: 'prior', unit: 'usd' }, { key: 'current', unit: 'usd' }, { key: 'change', unit: 'usd' }, { key: 'change_pct', label: 'Change %', unit: 'ratio' },
          { key: 'flag', label: 'Materiality', render: (r) => <Chip value={String(r.flag)} kind={r.needs_explanation ? 'bad' : r.material ? 'warn' : undefined} /> },
          { key: 'explanation', render: (r) => <span className="muted" style={{ whiteSpace: 'normal' }}>{String(r.explanation ?? (r.material ? 'needs explanation' : ''))}</span> }]} />
      </Card>

      <div className="grid cols-3">
        <Card title="Prepaids and depreciation" sub="Amortized from the schedules">
          <DataTable rows={(d.prepaids ?? []) as Row[]} empty="No prepaid amortization this month." columns={[{ key: 'prepaid_id' }, { key: 'vendor' }, { key: 'amortization', unit: 'usd' }, { key: 'closing_balance', unit: 'usd' }]} />
          <div className="muted" style={{ marginTop: 8 }}>Depreciation booked: {usd(journals.find((j) => j.entry_type === 'depreciation')?.amount ?? 0)} ({String(journals.find((j) => j.entry_type === 'depreciation')?.entries ?? 0)} entries)</div>
        </Card>
        <Card title="Journal entries this month" sub="Amount by type · click a type to filter"><Bars rows={journals} dim="entry_type" measure="amount" top={10} /></Card>
        <Card title="Revenue recognition (ASC 606)" sub="Opening deferred + billings − revenue = closing">
          {rr ? <DataTable rows={[
            { line: 'Opening deferred', amount: rr.opening_net_deferred }, { line: 'Billings', amount: rr.billings }, { line: 'Recognized (ASC 606)', amount: rr.asc606_revenue },
            { line: 'Closing deferred', amount: rr.closing_net_deferred }, { line: 'GL revenue', amount: rr.gl_revenue }, { line: 'Entry to book', amount: rr.revenue_adjustment }]}
            columns={[{ key: 'line' }, { key: 'amount', unit: 'usd' }]} /> : <div className="muted">No roll-forward.</div>}
        </Card>
      </div>

      <Card title={`Close checklist · ${done} of ${tasks.length} done`} sub="Status comes from the evidence above · click a task to ask about it">
        <DataTable title="close_checklist" rows={tasks} onRow={(r) => ask(`Close task ${r.task_id} (${r.task}) is ${r.state}. What does it need and who should act?`)}
          columns={[{ key: 'workday', label: 'WD' }, { key: 'due_date' }, { key: 'owner' }, { key: 'task' },
            { key: 'state', label: 'Status', render: (r) => <Chip value={String(r.state).replace('_', ' ')} kind={r.state === 'complete' ? 'good' : r.state === 'blocked' || r.state === 'exceptions' ? 'bad' : 'warn'} /> }, { key: 'open_items', unit: 'count' }, { key: 'evidence' }]} />
      </Card>
      <Source data={d} />
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
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <a className="btn primary" href="/api/dataroom.zip">Download diligence data room (.zip)</a>
      </div>
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
  const [terms, setTerms] = useState({ payment_terms_days: 30, sla: 'standard', unlimited_usage: false, prepaid_credits: false, free_months: 0, custom_terms: '' })
  const [ev, setEv] = useState<Row | null>(null)
  const [msg, setMsg] = useState<string>()
  const [deals, setDeals] = useState<Row[]>([])
  const { refreshKey, refresh } = useWorkspace()
  const body = () => ({ customer, discount_pct: discount / 100, term_months: term, monthly_commit: commit, ...terms, custom_terms: terms.custom_terms || null,
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
          <label>Payment terms (days)<br />{num(terms.payment_terms_days, (n) => setTerms({ ...terms, payment_terms_days: n }))}</label>
          <label>SLA<br /><select value={terms.sla === 'standard' ? 'standard' : 'custom'} onChange={(e) => setTerms({ ...terms, sla: e.target.value === 'standard' ? 'standard' : '99.99% uptime with service credits' })}><option value="standard">Standard</option><option value="custom">Custom (uptime + credits)</option></select></label>
          <label>Free months<br />{num(terms.free_months, (n) => setTerms({ ...terms, free_months: n }))}</label>
          <label><input type="checkbox" checked={terms.unlimited_usage} onChange={(e) => setTerms({ ...terms, unlimited_usage: e.target.checked })} /> Unlimited usage</label>
          <label><input type="checkbox" checked={terms.prepaid_credits} onChange={(e) => setTerms({ ...terms, prepaid_credits: e.target.checked })} /> Prepaid credits (expire)</label>
          <label>Other non-standard terms<br /><input value={terms.custom_terms} placeholder="e.g. MFN pricing, termination for convenience" onChange={(e) => setTerms({ ...terms, custom_terms: e.target.value })} /></label>
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
            <Kpi label="Routing" value={ev.route === 'auto_approve' ? 'Auto-approve' : `Needs ${((ev.approvers ?? []) as string[]).join(', ')}`} tone={ev.route === 'auto_approve' ? 'good' : 'bad'} />
          </div>
          <div className="grid cols-2">
            <Card title="Guardrails">
              <DataTable rows={checks} columns={[{ key: 'rule' }, { key: 'passed', render: (r) => <Chip value={r.passed ? 'pass' : 'fail'} /> }, { key: 'approver', label: 'If not, approver', render: (r) => String(r.approver ?? 'Finance') }, { key: 'detail' }]} />
            </Card>
            <Card title="Pricing by product">
              <DataTable rows={ev.lines as Row[]} columns={[{ key: 'product_id' }, { key: 'hours_per_month', unit: 'count' }, { key: 'net_price', label: '$/hr', render: (r) => (r.net_price as number).toFixed(4) },
                { key: 'monthly_revenue', unit: 'usd' }, { key: 'gross_margin_pct', unit: 'ratio' }, { key: 'floor_pct', label: 'Floor', unit: 'ratio' }]} />
            </Card>
          </div>
          {((ev.revrec_flags ?? []) as Row[]).length ? (
            <Card title="Revenue recognition flags" sub="For the controller before signature (ASC 606)">
              <DataTable rows={ev.revrec_flags as Row[]} columns={[{ key: 'flag' }, { key: 'detail' }]} />
            </Card>
          ) : null}
          {ev.risk ? <DealRisk risk={ev.risk as Row} /> : null}
        </>
      ) : null}
      {ev?.error ? <div className="error">{String(ev.error)}</div> : null}
      <Card title="Deals" sub={`Approval status comes from the approval card (audited)${cycleNote(deals)}`}>
        <DataTable rows={deals} empty="No deals yet." columns={[{ key: 'id' }, { key: 'customer' }, { key: 'route', chip: true },
          { key: 'approval_status', label: 'Status', chip: true }, { key: 'created_at', render: (r) => String(r.created_at).slice(0, 10) },
          { key: 'cycle_minutes', label: 'Quote cycle', render: (r) => (r.decided_at || r.route === 'auto_approve' ? fmtMinutes(Number(r.cycle_minutes ?? 0)) : 'pending') },
          { key: 'quote', label: '', render: (r) => <a className="btn small" href={`/api/deals/${r.id}/quote.pdf`} target="_blank" rel="noreferrer">Quote PDF</a> }]} />
      </Card>
    </div>
  )
}

function fmtMinutes(m: number) {
  return m < 60 ? `${m} min` : m < 60 * 24 ? `${(m / 60).toFixed(1)} h` : `${(m / 1440).toFixed(1)} days`
}

function cycleNote(deals: Row[]) {
  const done = deals.filter((d) => d.decided_at || d.route === 'auto_approve').map((d) => Number(d.cycle_minutes ?? 0)).sort((a, b) => a - b)
  if (!done.length) return ''
  return ` · median quote cycle ${fmtMinutes(done[Math.floor((done.length - 1) / 2)])} over ${done.length} decided deal(s)`
}

// The deal desk's risk view: cost-to-serve range, credit exposure, commission impact and where the discount sits.
function DealRisk({ risk }: { risk: Row }) {
  const cr = risk.credit as Row, cm = risk.commission as Row, dd = risk.discounts as Row
  const pct = (v: unknown) => (v == null ? '—' : `${(Number(v) * 100).toFixed(1)}%`)
  return (
    <>
      <div className="grid cols-4">
        <Kpi label="Margin if cost hits P90" value={pct(risk.gross_margin_pct_at_p90_cost)} note="worst month in 10 for cost per hour" />
        <Kpi label="Peak credit exposure" value={usd(cr.peak_exposure)} note={`${String(cr.terms_days)}-day terms + ${usd(cr.open_ar)} open AR · limit ${usd(cr.credit_limit)}`} tone={cr.within_limit ? 'good' : 'bad'} />
        <Kpi label="First-year commission" value={usd(cm.first_year_commission)} note={`${pct(cm.rate)} on ${String(cm.plan_id)} · ${pct(cm.share_of_first_year_gross_margin)} of year-1 gross margin · payback ${String(cm.payback_months ?? '—')} mo`} />
        <Kpi label="Discount vs history" value={dd.this_deal_percentile == null ? '—' : `${Math.round(Number(dd.this_deal_percentile) * 100)}th pct`} note={`customers got: median ${pct(dd.median)}, P75 ${pct(dd.p75)}, max ${pct(dd.max)}`} />
      </div>
      <Card title="Cost to serve by product" sub="Cost per audio hour by month over the last 12 closed months: P10 / P50 / P90">
        <DataTable rows={risk.cost_to_serve as Row[]} columns={[{ key: 'product_id' }, { key: 'p10', label: 'P10 $/hr', render: (r) => Number(r.p10).toFixed(4) }, { key: 'p50', label: 'P50 $/hr', render: (r) => Number(r.p50).toFixed(4) }, { key: 'p90', label: 'P90 $/hr', render: (r) => Number(r.p90).toFixed(4) }, { key: 'months', unit: 'count' }]} />
      </Card>
    </>
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
          { key: 'ytd_credited_arr', unit: 'usd' }, { key: 'annual_quota_arr', unit: 'usd' }, { key: 'quota_attainment_pct', label: 'Attainment', unit: 'ratio' }, { key: 'plan_id', label: 'Plan' }, { key: 'spiff', label: 'SPIFF', unit: 'usd' }, { key: 'commission_total', unit: 'usd' }]} />
        <Source data={c.data} />
      </Card>
      <Card title="Credits this year" sub="Which customers earned the credit · split accounts show each rep's share">
        <DataTable rows={(c.data.credits ?? []) as Row[]} columns={[{ key: 'rep_id' }, { key: 'customer_id' }, { key: 'credit_type', chip: true }, { key: 'split_pct', label: 'Split', unit: 'ratio' }, { key: 'billed_revenue', unit: 'usd' }, { key: 'credited_arr', unit: 'usd' }, { key: 'comp_credit', label: 'Comp credit', unit: 'usd' }]} />
      </Card>
      <Disputes reps={[...new Set(all.map((r) => String(r.rep_id)))].sort()} months={months} credits={(c.data.credits ?? []) as Row[]} />
      <div className="grid cols-2">
        <Card title="Deferred commissions (ASC 340-40)" sub={`Capitalized when earned, amortized over 48 months (new logos, SPIFFs) or 36 (expansion) · balance ${usd(Number((c.data.deferred_summary as Row | undefined)?.balance ?? 0))}, current portion ${usd(Number((c.data.deferred_summary as Row | undefined)?.current_portion ?? 0))}`}>
          <Trend rows={(c.data.deferred ?? []) as Row[]} x="month" series={[{ key: 'deferred_commission_balance', label: 'Deferred balance' }, { key: 'amortization', label: 'Amortization (expense)', color: '#c98a1b' }]} />
        </Card>
        <Card title="Comp plans, splits and SPIFFs" sub="Plan versions by year; split accounts; SPIFF programs">
          <DataTable rows={(c.data.plans ?? []) as Row[]} columns={[{ key: 'plan_id' }, { key: 'rep_id' }, { key: 'effective_from' }, { key: 'annual_quota_arr', label: 'Quota', unit: 'usd' }, { key: 'base_rate', unit: 'ratio' }, { key: 'accelerator_rate', unit: 'ratio' }, { key: 'expansion_multiplier', label: 'Expansion credit', unit: 'ratio' }]} />
          <DataTable rows={(c.data.splits ?? []) as Row[]} columns={[{ key: 'customer_id' }, { key: 'rep_id' }, { key: 'split_pct', unit: 'ratio' }, { key: 'reason' }]} />
          <DataTable rows={(c.data.spiffs ?? []) as Row[]} columns={[{ key: 'spiff_id' }, { key: 'name' }, { key: 'start_month' }, { key: 'end_month' }, { key: 'amount_per_credit', label: 'Per credit', unit: 'usd' }, { key: 'paid', unit: 'usd' }]} />
        </Card>
      </div>
    </div>
  )
}

// Commission disputes: a rep raises one against a statement line; Finance reviews it with both sides on the card
// (the claim and what the statement credited) and records the resolution. Every step is in the audit log.
function Disputes({ reps, months, credits }: { reps: string[]; months: string[]; credits: Row[] }) {
  const [list, setList] = useState<Row[]>([])
  const [form, setForm] = useState({ rep_id: reps[0] ?? '', month: months.at(-1) ?? '', customer_id: '', claim: '', claimed_amount: '' })
  const [note, setNote] = useState<Record<string, string>>({})
  const [msg, setMsg] = useState<string>()
  const load = () => fetch('/api/commission-disputes').then((r) => r.json()).then(setList)
  useEffect(() => { load() }, [])
  useEffect(() => { if (!form.rep_id && reps[0]) setForm((f) => ({ ...f, rep_id: reps[0], month: months.at(-1) ?? '' })) }, [reps.length])  // eslint-disable-line react-hooks/exhaustive-deps
  const customers = [...new Set(credits.filter((c) => c.rep_id === form.rep_id).map((c) => String(c.customer_id)))].sort()
  const raise = () => fetch('/api/commission-disputes', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...form, claimed_amount: form.claimed_amount ? Number(form.claimed_amount) : null }) })
    .then(async (r) => { const j = await r.json(); setMsg(r.ok ? 'Dispute raised: it is waiting for Finance.' : String(j.detail)); load() })
  const decide = (id: string, d: 'approve' | 'reject') => fetch(`/api/actions/${id}/${d}`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ note: note[id] || (d === 'approve' ? 'Upheld: statement to be adjusted' : 'Not upheld: statement stands') }) }).then(load)
  return (
    <Card title="Commission disputes" sub="Reps raise a dispute against a statement line; Finance reviews both sides and records the resolution (audited)">
      <div className="explore-grid" style={{ marginBottom: 10 }}>
        <label className="explore-field">Rep<select value={form.rep_id} onChange={(e) => setForm({ ...form, rep_id: e.target.value, customer_id: '' })}>{reps.map((r) => <option key={r}>{r}</option>)}</select></label>
        <label className="explore-field">Statement month<select value={form.month} onChange={(e) => setForm({ ...form, month: e.target.value })}>{[...months].reverse().map((m) => <option key={m}>{m}</option>)}</select></label>
        <label className="explore-field">Customer<select value={form.customer_id} onChange={(e) => setForm({ ...form, customer_id: e.target.value })}><option value="">Pick…</option>{customers.map((c) => <option key={c}>{c}</option>)}</select></label>
        <label className="explore-field">Amount claimed $<input type="number" value={form.claimed_amount} onChange={(e) => setForm({ ...form, claimed_amount: e.target.value })} /></label>
        <label className="explore-field" style={{ gridColumn: 'span 2' }}>What is wrong<input value={form.claim} placeholder="e.g. expansion credited at 50%, my plan says 75%" onChange={(e) => setForm({ ...form, claim: e.target.value })} /></label>
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12 }}>
        <button className="btn" disabled={!form.customer_id || !form.claim} onClick={raise}>Raise dispute</button>
        {msg && <span className="muted">{msg}</span>}
      </div>
      <DataTable rows={list} empty="No disputes raised." columns={[{ key: 'raised_at', label: 'Raised', render: (r) => String(r.raised_at).slice(0, 10) }, { key: 'rep_id' }, { key: 'month' }, { key: 'customer_id' }, { key: 'claim' },
        { key: 'claimed_amount', label: 'Claimed', unit: 'usd' }, { key: 'credited_arr', label: 'Statement credit (ARR)', unit: 'usd' }, { key: 'status', chip: true },
        { key: 'resolution', label: 'Resolution', render: (r) => (r.status === 'pending'
          ? <span style={{ display: 'flex', gap: 4 }}>
              <input className="table-search" style={{ width: 160 }} placeholder="Resolution note" value={note[String(r.id)] ?? ''} onChange={(e) => setNote({ ...note, [String(r.id)]: e.target.value })} />
              <button className="btn small" onClick={() => decide(String(r.id), 'approve')}>Uphold</button>
              <button className="btn small" onClick={() => decide(String(r.id), 'reject')}>Reject</button>
            </span>
          : String(r.resolution ?? '')) }]} />
    </Card>
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
      <Head title="Financials" sub="Consolidated income statement, balance sheet and cash flow from the general ledger (intercompany eliminated), closed months only. Balances are as booked in USD; the translated consolidation (ASC 830) is on Close & control → Entities."
        ask="Walk me through the financial statements: what changed this quarter in revenue, margins, cash and working capital?" />
      <Card
        title={<div className="segmented">{SHEETS.map((s) => <button key={s} className={sheet === s ? 'on' : ''} onClick={() => { setSheet(s); setSel(null) }}>{s}</button>)}</div>}
        right={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <div className="segmented">{(['month', 'quarter', 'year'] as const).map((p) => <button key={p} className={period === p ? 'on' : ''} onClick={() => { setPeriod(p); setSel(null) }}>{p === 'month' ? 'Monthly' : p === 'quarter' ? 'Quarterly' : 'Annual'}</button>)}</div>
            <a className="btn small primary" href={`/api/financials.xlsx?period=${period}&periods=${count}`}>Download Excel</a>
            <a className="btn small" href="/api/dataroom.zip" title="Workbook, board pack and every table behind them as CSV, for investors, lenders or auditors">Data room</a>
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


function SegmentPnl() {
  const [dim, setDim] = useState<'region' | 'channel'>('region')
  const sp = useTool('get_segment_pnl', { dimension: dim })
  const rows = (sp.data?.rows ?? []) as Row[]
  const trend = (sp.data?.trend ?? []) as Row[]
  const segs = [...new Set(trend.map((t) => String(t.segment)))].filter((x) => !x.startsWith('Unallocated'))
  const byMonth = Object.values(trend.reduce<Record<string, Row>>((a, t) => { const k = String(t.month); a[k] ??= { month: k }; a[k][String(t.segment)] = t.operating_income; return a }, {}))
  return (
    <Card title="Segment P&L" sub={sp.data ? `${String(sp.data.month)} · cost to serve = payment fees, support and success; other opex allocated by revenue share · ties to the ledger` : ''}
      right={<div className="segmented"><button className={dim === 'region' ? 'on' : ''} onClick={() => setDim('region')}>By region</button><button className={dim === 'channel' ? 'on' : ''} onClick={() => setDim('channel')}>By channel</button></div>}>
      {sp.data ? (
        <div className="grid cols-2">
          <DataTable title={`segment_pnl_${dim}`} rows={rows} columns={[{ key: 'segment' }, { key: 'revenue', unit: 'usd' }, { key: 'gross_margin_pct', label: 'GM %', unit: 'ratio' },
            { key: 'cost_to_serve', unit: 'usd' }, { key: 'contribution_margin', unit: 'usd' }, { key: 'allocated_opex', unit: 'usd' }, { key: 'operating_income', unit: 'usd' }]} />
          <div style={{ height: 240 }}>
            <ResponsiveContainer>
              <LineChart data={byMonth} margin={{ left: 8, right: 8, top: 8 }}>
                <CartesianGrid stroke="var(--border)" vertical={false} />
                <XAxis dataKey="month" {...AXIS} />
                <YAxis tickFormatter={usd} width={70} {...AXIS} />
                <Tooltip formatter={usd} {...TIP} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <ReferenceLine y={0} stroke="var(--faint)" />
                {segs.map((sg, i) => <Line key={sg} dataKey={sg} name={`${sg} operating income`} stroke={['#3b6fd8', '#2f9e6b', '#c98a1b', '#8a63d2'][i % 4]} strokeWidth={2} dot={false} isAnimationActive animationDuration={700} />)}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      ) : <Loading state={sp} />}
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
        <Kpi label="LTV : CAC (fully burdened)" value={last?.ltv_to_cac_burdened != null ? `${(last.ltv_to_cac_burdened as number).toFixed(1)}x` : '—'} note={last ? `S&M only ${(last.ltv_to_cac as number).toFixed(1)}x · burdened CAC ${usd(last.cac_burdened)}` : ''} tone={last && (last.ltv_to_cac_burdened as number) >= 3 ? 'good' : 'bad'} />
        <Kpi label="CAC payback (fully burdened)" value={last?.cac_payback_burdened_months != null ? `${(last.cac_payback_burdened_months as number).toFixed(1)} mo` : '—'} note={last ? `S&M only ${(last.cac_payback_months as number).toFixed(1)} mo` : ''} tone={last && (last.cac_payback_burdened_months as number) <= 18 ? 'good' : 'bad'} />
        <Kpi label="Rule of 40" value={last ? `${((last.rule_of_40 as number) * 100).toFixed(0)}` : '—'} note={last ? `growth ${pct(last.revenue_growth_yoy)} + EBITDA margin ${pct(last.ebitda_margin)}` : ''} tone={last && (last.rule_of_40 as number) >= 0.4 ? 'good' : 'bad'} />
        <Kpi label="Breakeven revenue / month" value={lc ? usd(lc.breakeven_revenue) : '—'} note={lc ? `revenue ${usd(lc.revenue)} · margin of safety ${pct(lc.margin_of_safety)}` : ''} />
      </div>

      <Card title="SaaS unit economics" sub="CAC on trailing 3 months; burdened CAC adds Sales' share of G&A overhead (rent, software, legal, finance) by headcount; LTV = ARPA × gross margin / monthly churn">
        {saas.data ? <DataTable title="saas_metrics" rows={[...saas.data.rows].reverse()} columns={[{ key: 'month' }, { key: 'arr', unit: 'usd' }, { key: 'new_customers', label: 'New' }, { key: 'cac', label: 'CAC', unit: 'usd' }, { key: 'cac_burdened', label: 'CAC burdened', unit: 'usd' }, { key: 'arpa', label: 'ARPA', unit: 'usd' }, { key: 'ltv', label: 'LTV', unit: 'usd' }, { key: 'ltv_to_cac', label: 'LTV:CAC' }, { key: 'ltv_to_cac_burdened', label: 'LTV:CAC burdened' }, { key: 'cac_payback_burdened_months', label: 'Payback burdened (mo)' }, { key: 'revenue_growth_yoy', label: 'Growth YoY', unit: 'ratio' }, { key: 'rule_of_40', label: 'Rule of 40', unit: 'ratio' }, { key: 'free_cash_flow', label: 'Free cash flow', unit: 'usd' }]} /> : <Loading state={saas} />}
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

      <Card title="Runway sensitivity" sub="Months until cash runs out with no new money, from the same driver engine as the forecast. Rows: change in net revenue retention (annual points). Columns: change in non-payroll opex.">
        {sens.data ? <DataTable rows={sens.data.rows} columns={Object.keys(sens.data.rows[0] ?? {}).map((k) => k === 'nrr_change'
          ? { key: k, label: 'NRR change', render: (r: Row) => `${(r[k] as number) > 0 ? '+' : ''}${Math.round((r[k] as number) * 100)} pts` }
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

      <SegmentPnl />
      <BusinessCase />
    </div>
  )
}


// ---- Scenarios: one-click stress tests with your own levers, against the baseline ---------------------------

const LEVERS: { key: string; label: string; min: number; max: number; step: number; fmt: (v: number) => string; base: number }[] = [
  { key: 'nrr_pts', label: 'Net revenue retention (annual, pts)', min: -0.15, max: 0.15, step: 0.01, fmt: (v) => `${v >= 0 ? '+' : ''}${Math.round(v * 100)} pts`, base: 0 },
  { key: 'win_rate_pct', label: 'Win rate', min: -0.5, max: 0.5, step: 0.05, fmt: (v) => `${v >= 0 ? '+' : ''}${Math.round(v * 100)}%`, base: 0 },
  { key: 'cycle_days', label: 'Sales cycle', min: -30, max: 90, step: 15, fmt: (v) => `${v >= 0 ? '+' : ''}${v} days`, base: 0 },
  { key: 'price_pct', label: 'Price', min: -0.2, max: 0.2, step: 0.01, fmt: (v) => `${v >= 0 ? '+' : ''}${Math.round(v * 100)}%`, base: 0 },
  { key: 'cogs_pts', label: 'Cost to serve (pts of revenue)', min: -0.05, max: 0.1, step: 0.01, fmt: (v) => `${v >= 0 ? '+' : ''}${Math.round(v * 100)} pts`, base: 0 },
  { key: 'hiring_pct', label: 'Hiring plan delivered', min: 0, max: 1.5, step: 0.1, fmt: (v) => `${Math.round(v * 100)}%`, base: 1 },
  { key: 'opex_pct', label: 'Other opex', min: -0.3, max: 0.3, step: 0.05, fmt: (v) => `${v >= 0 ? '+' : ''}${Math.round(v * 100)}%`, base: 0 },
]

export function Scenarios() {
  const [levers, setLevers] = useState<Record<string, number>>(() => Object.fromEntries(LEVERS.map((l) => [l.key, l.base])))
  const [raise, setRaise] = useState({ amount: 0, month: '2027-06' })
  const [preset, setPreset] = useState<string | null>(null)
  const args = useMemo(() => ({ ...levers, ...(preset ? { preset } : {}), ...(raise.amount ? { raise_amount: raise.amount, raise_month: raise.month } : {}) }), [levers, raise, preset])
  const r = useTool('run_stress_test', args)
  const presets = (r.data?.presets ?? {}) as Record<string, Record<string, number | string>>
  const apply = (key: string) => {
    const p = presets[key]
    setPreset(key)
    setLevers(Object.fromEntries(LEVERS.map((l) => [l.key, p[l.key] != null ? Number(p[l.key]) : l.base])))
  }
  const reset = () => { setPreset(null); setLevers(Object.fromEntries(LEVERS.map((l) => [l.key, l.base]))); setRaise({ amount: 0, month: '2027-06' }) }
  const b = (r.data?.baseline ?? {}) as Row, s = (r.data?.scenario ?? {}) as Row
  const rows = (r.data?.rows ?? []) as Row[]
  const delta = (k: string) => Number(s[k] ?? 0) - Number(b[k] ?? 0)
  const signed = (v: number) => `${v >= 0 ? '+' : '−'}${usd(Math.abs(v))}`
  const runway = (x: Row) => (x.cash_out_month ? `runs out ${String(x.cash_out_month)}` : 'no cash-out in 24 months')
  return (
    <div className="page">
      <Head title="Scenarios" sub="Stress-test the plan: move the levers or pick a preset; revenue, EBITDA, ARR and cash update against the baseline for 24 months"
        ask={`Walk me through this scenario (${JSON.stringify(args)}): what breaks first, how bad does cash get, and what would you do about it?`} />
      <Card title="Levers" right={<button className="btn small" onClick={reset}>Reset to baseline</button>}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
          {Object.entries(presets).map(([k, p]) => <button key={k} className={`btn ${preset === k ? 'primary' : ''}`} onClick={() => apply(k)}>{String(p.label)}</button>)}
        </div>
        {preset && presets[preset]?.note ? (
          <p className="muted" style={{ margin: '0 0 12px' }}>
            {String(presets[preset].note)}
            {r.data?.preset_detail ? ` · ${Object.entries(r.data.preset_detail as Row).map(([k, v]) => `${k.replace(/_/g, ' ')}: ${typeof v === 'number' && Math.abs(v) > 1000 ? usd(v) : String(v)}`).join(' · ')}` : ''}
          </p>
        ) : null}
        <div className="lever-grid">
          {LEVERS.map((l) => (
            <label key={l.key} className="lever">
              <span>{l.label}<b>{l.fmt(levers[l.key])}</b></span>
              <input type="range" min={l.min} max={l.max} step={l.step} value={levers[l.key]}
                onChange={(e) => { setPreset(null); setLevers({ ...levers, [l.key]: Number(e.target.value) }) }} />
            </label>
          ))}
          <label className="lever">
            <span>Funding round<b>{raise.amount ? usd(raise.amount) : 'none'}</b></span>
            <span style={{ display: 'flex', gap: 6 }}>
              <input type="number" className="table-search" style={{ width: 120 }} step={1000000} value={raise.amount} onChange={(e) => setRaise({ ...raise, amount: Number(e.target.value) })} />
              <input type="month" className="table-search" value={raise.month} onChange={(e) => setRaise({ ...raise, month: e.target.value })} />
            </span>
          </label>
        </div>
      </Card>
      {r.data ? (
        <>
          <KpiRow items={[
            { label: 'Revenue, next 12 months', value: usd(s.revenue_12m), note: `${signed(delta('revenue_12m'))} vs baseline`, tone: delta('revenue_12m') < -1 ? 'bad' : delta('revenue_12m') > 1 ? 'good' : null },
            { label: 'EBITDA, next 12 months', value: usd(s.ebitda_12m), note: `${signed(delta('ebitda_12m'))} vs baseline`, tone: Number(s.ebitda_12m) < 0 ? 'bad' : 'good' },
            { label: 'Run-rate ARR in 12 months', value: usd(s.arr_12m), note: `${signed(delta('arr_12m'))} vs baseline`, tone: delta('arr_12m') < -1 ? 'bad' : delta('arr_12m') > 1 ? 'good' : null },
            { label: 'Lowest cash', value: usd(s.min_cash), note: runway(s), tone: s.cash_out_month ? 'bad' : Number(s.min_cash) < 3000000 ? 'bad' : 'good' },
            { label: 'Cash in 24 months', value: usd(s.cash_end), note: `${signed(delta('cash_end'))} vs baseline` },
            { label: 'First EBITDA-positive month', value: String(s.first_ebitda_positive ?? 'not in 24 months'), note: `baseline ${String(b.first_ebitda_positive ?? 'none')}`, tone: s.first_ebitda_positive ? 'good' : 'bad' },
          ]} />
          <div className="grid cols-3">
            <Card title="Cash" sub="Scenario vs baseline · dashed line: $3M minimum (policy)">
              <Trend rows={rows} x="month" series={[{ key: 'scenario_cash', label: 'Scenario', color: '#3b6fd8' }, { key: 'base_cash', label: 'Baseline', color: '#7a8699', dashed: true }]} refs={[{ y: 3000000, label: '$3M minimum' }]} />
            </Card>
            <Card title="Run-rate ARR" sub="Existing customers at the retention rate, plus pipeline and run-rate bookings">
              <Trend rows={rows} x="month" series={[{ key: 'scenario_arr', label: 'Scenario', color: '#2f9e6b' }, { key: 'base_arr', label: 'Baseline', color: '#7a8699', dashed: true }]} />
            </Card>
            <Card title="EBITDA by month" sub="Scenario vs baseline">
              <Trend rows={rows} x="month" series={[{ key: 'scenario_ebitda', label: 'Scenario', color: '#c98a1b' }, { key: 'base_ebitda', label: 'Baseline', color: '#7a8699', dashed: true }]} refs={[{ y: 0, label: 'breakeven' }]} />
            </Card>
          </div>
          <Card title="Month by month" sub={String(r.data.note ?? '')}>
            <DataTable title="scenario" rows={rows} columns={[{ key: 'month' }, { key: 'scenario_revenue', label: 'Revenue', unit: 'usd' }, { key: 'base_revenue', label: 'Baseline revenue', unit: 'usd' },
              { key: 'scenario_new_arr', label: 'New ARR booked', unit: 'usd' }, { key: 'scenario_ebitda', label: 'EBITDA', unit: 'usd' }, { key: 'scenario_cash', label: 'Cash', unit: 'usd' }, { key: 'base_cash', label: 'Baseline cash', unit: 'usd' }]} />
            <Source data={r.data} />
          </Card>
        </>
      ) : <Loading state={r} />}
    </div>
  )
}


// ---- Entities: the consolidation worksheet ------------------------------------------------------------------------

export function Entities() {
  return <Dash><EntitiesBody /></Dash>
}

function EntitiesBody() {
  const c = useTool('get_consolidation')
  const d = c.data
  const ents = (d?.entities ?? []) as Row[]
  const cols = (d?.columns ?? []) as string[]
  const name = (id: string) => (id === 'ELIM' ? 'Eliminations' : String(ents.find((e) => e.entity_id === id)?.entity_name ?? id))
  const pl = (d?.rows ?? []) as Row[]
  const bs = (d?.balance_sheet ?? []) as Row[]
  const trend = (d?.trend ?? []) as Row[]
  const cta = (d?.cta ?? []) as Row[]
  const ic = pl.find((r) => r.account_id === '4900')
  const total = pl.find((r) => r.account_type === 'total')
  const sumCol = (rows: Row[], col: string, types: string[]) => rows.filter((r) => types.includes(String(r.account_type))).reduce((a, r) => a + Number(r[col] ?? 0), 0)
  const cost = (id: string) => sumCol(pl.filter((r) => r.account_id !== '6900'), id, ['cogs', 'opex'])
  const ctaNow = cta.filter((x) => x.month === d?.month).reduce((a, x) => a + Number(x.cta), 0)
  const byMonth = (rows: Row[], key: string) => Object.values(rows.reduce<Record<string, Row>>((a, r) => { const k = String(r.month); a[k] ??= { month: k }; a[k][String(r.entity_id)] = r[key]; return a }, {}))
  const sheetCols = [{ key: 'line', label: 'Account' }, ...cols.map((cid) => ({ key: cid, label: name(cid), unit: 'usd' as const })), { key: 'consolidated', label: 'Consolidated', unit: 'usd' as const }]
  if (!d) return <div className="page"><Loading state={c} /></div>
  return (
    <div className="page">
      <Head title={`Entities and consolidation · ${String(d.month)}`} sub="Each legal entity's books, the intercompany eliminations and the consolidated group · subsidiaries are cost-plus service providers to the parent"
        ask="Walk me through the consolidation: each entity's results, the intercompany charges and eliminations, and the currency translation adjustment." />
      <KpiRow items={[
        { label: 'Legal entities', value: String(ents.length), note: ents.map((e) => `${e.entity_id} ${e.currency}`).join(' · ') },
        { label: 'Intercompany charges', value: usd(ic ? cols.filter((x) => x !== 'ELIM').reduce((a, x) => a + Number(ic[x] ?? 0), 0) : 0), note: 'subsidiaries to parent this month, eliminated', tone: null },
        { label: 'Eliminations net to zero', value: total && Math.abs(Number(total.ELIM ?? 0)) < 1 ? 'Yes' : 'Check', note: 'intercompany revenue = fees; receivables = payables', tone: total && Math.abs(Number(total.ELIM ?? 0)) < 1 ? 'good' : 'bad' },
        { label: 'UK cost base', value: usd(cost('UK01')), note: `markup ${Math.round(Number(ents.find((e) => e.entity_id === 'UK01')?.markup_pct ?? 0) * 100)}% · profit ${usd(Number(total?.UK01 ?? 0))}` },
        { label: 'India cost base', value: usd(cost('IN01')), note: `markup ${Math.round(Number(ents.find((e) => e.entity_id === 'IN01')?.markup_pct ?? 0) * 100)}% · profit ${usd(Number(total?.IN01 ?? 0))}` },
        { label: 'Translation adjustment', value: usd(ctaNow), note: 'cumulative, in equity (CTA)', tone: ctaNow < 0 ? 'bad' : null },
      ]} />
      <Card title="Consolidation worksheet: P&L" sub="Each entity's month in USD (subsidiaries at the average rate), eliminations, consolidated · ties to the income statement">
        <DataTable title="consolidation_pl" rows={pl} columns={sheetCols} pageSize={100} />
      </Card>
      <div className="grid cols-3">
        <Card title="Costs by entity" sub="Cost of revenue and operating expenses, excluding intercompany fees">
          <Donut rows={cols.filter((x) => x !== 'ELIM').map((x) => ({ entity: name(x), cost: cost(x) }))} dim="entity" measure="cost" />
        </Card>
        <Card title="Intercompany charges by month" sub="What each subsidiary bills the parent (cost plus markup)">
          <Trend rows={byMonth(trend, 'ic_charge')} x="month" series={[{ key: 'UK01', label: name('UK01'), color: '#3b6fd8' }, { key: 'IN01', label: name('IN01'), color: '#c98a1b' }]} />
        </Card>
        <Card title="Translation adjustment" sub="Cumulative CTA by subsidiary (closing vs historical rates)">
          <Trend rows={byMonth(cta, 'cta')} x="month" series={[{ key: 'UK01', label: name('UK01'), color: '#3b6fd8' }, { key: 'IN01', label: name('IN01'), color: '#c98a1b' }]} refs={[{ y: 0, label: '' }]} />
        </Card>
      </div>
      <Card title="Consolidation worksheet: balance sheet" sub="Month end, subsidiaries translated at the closing rate; CTA balances the translated books">
        <DataTable title="consolidation_bs" rows={bs} columns={sheetCols} pageSize={100} />
      </Card>
      <Card title="Entities">
        <DataTable rows={ents} columns={[{ key: 'entity_id' }, { key: 'entity_name' }, { key: 'country' }, { key: 'currency' }, { key: 'role' }, { key: 'markup_pct', label: 'Transfer-pricing markup', unit: 'ratio' }]} />
        <Source data={d} />
      </Card>
    </div>
  )
}
