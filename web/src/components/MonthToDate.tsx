// The open month so far, clearly marked as not closed: actuals to date, a straight-line projection to month end,
// and the comparison with last month and the budget. Usage revenue is an estimate until the month is invoiced.
import { Columns, KpiRow } from './Dash'
import { fmt, type Row } from '../api'
import { Card, Chip, DataTable, Loading, Source, useTool } from './common'

const usd = (v: unknown) => fmt('amount', Number(v ?? 0), 'usd')
const pct = (v: unknown) => (v == null ? null : `${Number(v) >= 0 ? '+' : ''}${(Number(v) * 100).toFixed(1)}%`)

function show(t: Row, k: string) {
  const v = t[k]
  if (v == null) return '—'
  return t.unit === 'usd' ? usd(v) : Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 })
}

export function MonthToDate({ compact = false }: { compact?: boolean }) {
  const d = useTool('get_month_to_date')
  if (!d.data) return <Card title="Month to date"><Loading state={d} /></Card>
  const tiles = d.data.rows as Row[]
  const cust = d.data.customers as Row
  const label = new Date(`${String(d.data.month)}-01T00:00`).toLocaleString('en', { month: 'long', year: 'numeric' })
  return (
    <Card title={<span>{label} to date <Chip value="open · not closed" kind="warn" /></span>}
      sub={`Day ${String(d.data.days_elapsed)} of ${String(d.data.days_in_month)} · usage through ${String(d.data.usage_through)}, ledger through ${String(d.data.gl_through)} · projections are straight-line on the daily run rate · ${String(d.data.note)}`}>
      <KpiRow items={tiles.map((t) => {
        const vs = pct(t.vs_budget_pct) ?? pct(t.vs_last_month_pct)
        const vsLabel = t.vs_budget_pct != null ? 'vs budget' : 'vs last month'
        const bad = t.vs_budget_pct != null ? Number(t.vs_budget_pct) < -0.05 : t.metric === 'gpu_cloud_spend' ? Number(t.vs_last_month_pct ?? 0) > 0.1 : false
        return {
          label: String(t.label), value: show(t, 'mtd'),
          note: t.projected != null ? `→ ${show(t, 'projected')} by month end${vs ? ` · ${vs} ${vsLabel}` : ''}` : String(t.basis),
          title: String(t.basis), tone: vs ? (bad ? 'bad' : 'good') : null,
        }
      })} />
      {!compact && (
        <div className="grid cols-2">
          <Card title="Estimated usage revenue by day" sub="Audio hours each day at each customer's last-month rate · blank days are still to come">
            <Columns rows={(d.data.daily as Row[]).map((r) => ({ ...r, day: String(r.day).slice(8) }))} x="day" y="usage_revenue" />
          </Card>
          <Card title="Customers this month" sub={`${String(cust.active)} active · ${(cust.new_this_month as string[]).length} new · ${(cust.gone_quiet as string[]).length} gone quiet (used last month, nothing yet)`}>
            <DataTable rows={(d.data.top_customers as Row[])} pageSize={6} columns={[{ key: 'customer_id' }, { key: 'usage_revenue_estimated', label: 'Usage revenue (est.)', unit: 'usd' }]} />
            {(cust.gone_quiet as string[]).length ? <p className="muted" style={{ fontSize: 12 }}>Gone quiet: {(cust.gone_quiet as string[]).join(', ')}</p> : null}
            <p className="muted" style={{ fontSize: 12 }}>Also this month: vendor payments {usd(d.data.vendor_payments)}, payroll remitted {usd(d.data.payroll_remitted)}.</p>
          </Card>
        </div>
      )}
      <Source data={d.data} />
    </Card>
  )
}
