// Drill-down panel: one customer, vendor, project or KPI in full. Opens from any table cell that names one
// (customer_id / vendor_id / project_id) or from a KPI tile, and reads the same tools as the assistant.
import { useEffect } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fmt, type Row } from '../api'
import { AskButton, Card, DataTable, Loading, Source, useTool, type Entity } from './common'

const AXIS = { tick: { fontSize: 11, fill: 'var(--faint)' }, tickLine: false, axisLine: false } as const
const usd = (v: unknown) => fmt('amount', v as number, 'usd')

function Trend({ rows, x, y, unit = 'usd' }: { rows: Row[]; x: string; y: string; unit?: string }) {
  return (
    <div style={{ height: 180 }}>
      <ResponsiveContainer>
        <AreaChart data={rows} margin={{ left: 8, right: 8, top: 8 }}>
          <CartesianGrid stroke="var(--border)" vertical={false} />
          <XAxis dataKey={x} {...AXIS} />
          <YAxis tickFormatter={(v) => fmt(y, v as number, unit)} width={64} {...AXIS} />
          <Tooltip formatter={(v) => fmt(y, v as number, unit)} contentStyle={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }} />
          <Area type="monotone" dataKey={y} stroke="var(--accent)" strokeWidth={2} fill="var(--accent)" fillOpacity={0.12} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

function Customer({ id }: { id: string }) {
  const d = useTool('get_customer_detail', { customer_id: id })
  if (!d.data) return <Loading state={d} />
  const c = (d.data.customer ?? {}) as Row
  const t = (d.data.totals ?? {}) as Row
  return (
    <>
      <p className="muted">{String(c.customer_name ?? '')} · {String(c.segment ?? '').replace('_', ' ')} · customer since {String(c.signup_date ?? '')}</p>
      <div className="grid cols-3">
        <div className="card kpi"><div className="label">Billed to date</div><div className="value">{usd(t.billed)}</div></div>
        <div className="card kpi"><div className="label">Open balance</div><div className="value">{usd(t.open_balance ?? 0)}</div></div>
        <div className="card kpi"><div className="label">Avg days to pay</div><div className="value">{t.avg_days_to_pay != null ? (t.avg_days_to_pay as number).toFixed(1) : '—'}</div></div>
      </div>
      <Card title="Revenue by month"><Trend rows={d.data.rows} x="month" y="revenue" /></Card>
      {(d.data.alerts as Row[]).length > 0 && <Card title="Open alerts"><DataTable rows={d.data.alerts as Row[]} columns={[{ key: 'severity', chip: true }, { key: 'rule_id' }, { key: 'message' }]} /></Card>}
      <Card title="Invoices"><DataTable title={`${id}_invoices`} rows={d.data.invoices as Row[]} columns={[{ key: 'invoice_ref' }, { key: 'invoice_type', chip: true }, { key: 'invoice_date' }, { key: 'due_date' }, { key: 'amount', unit: 'usd' }, { key: 'balance', unit: 'usd' }, { key: 'status', chip: true }, { key: 'days_paid_late', label: 'Days late' }, { key: 'is_disputed', label: 'Disputed', flag: 'bad' }]} /></Card>
      <Card title="Margin by month"><DataTable rows={d.data.rows} columns={[{ key: 'month' }, { key: 'revenue', unit: 'usd' }, { key: 'gross_margin_pct', unit: 'ratio' }, { key: 'movement', chip: true }, { key: 'is_below_floor', label: 'Below floor', flag: 'bad' }]} /></Card>
      <Card title="Payments"><DataTable rows={d.data.payments as Row[]} empty="No payments." columns={[{ key: 'payment_id' }, { key: 'received_date' }, { key: 'amount', unit: 'usd' }, { key: 'remittance_ref' }, { key: 'applied_ref' }]} /></Card>
      <Card title="Lifecycle"><DataTable rows={d.data.lifecycle as Row[]} empty="No churn, expansion or contraction events." columns={[{ key: 'event_date' }, { key: 'event_type', chip: true }, { key: 'multiplier' }, { key: 'reason' }]} /></Card>
      {(d.data.projects as Row[]).length > 0 && <Card title="Projects"><DataTable rows={d.data.projects as Row[]} columns={[{ key: 'project_id' }, { key: 'project_name' }, { key: 'project_type', chip: true }, { key: 'contract_value', unit: 'usd' }]} /></Card>}
      <Source data={d.data} />
    </>
  )
}

function Vendor({ id }: { id: string }) {
  const d = useTool('get_vendor_detail', { vendor_id: id })
  if (!d.data) return <Loading state={d} />
  return (
    <>
      <div className="grid cols-3">
        <div className="card kpi"><div className="label">Still owed</div><div className="value">{usd(d.data.open_ap ?? 0)}</div></div>
        <div className="card kpi"><div className="label">Bills</div><div className="value">{d.data.row_count}</div></div>
        <div className="card kpi"><div className="label">Bill PDFs read</div><div className="value">{(d.data.documents as Row[]).length}</div></div>
      </div>
      {(d.data.contract as Row[]).length > 0 && <Card title="Contract"><DataTable rows={d.data.contract as Row[]} columns={[{ key: 'vendor_name' }, { key: 'category' }, { key: 'end_date' }, { key: 'avg_monthly_spend_t3m', label: 'Avg monthly spend (3m)', unit: 'usd' }, { key: 'is_renewal_due', label: 'Renewal due', flag: 'warn' }]} /></Card>}
      <Card title="Bills"><DataTable title={`${id}_bills`} rows={d.data.rows} empty="No bills." columns={[{ key: 'bill_id' }, { key: 'vendor_invoice_number' }, { key: 'service_month' }, { key: 'bill_date' }, { key: 'total_amount', unit: 'usd' }]} /></Card>
      <Card title="AP activity (posted and paid)"><DataTable rows={d.data.ap_activity as Row[]} columns={[{ key: 'entry_date' }, { key: 'entry_type', chip: true }, { key: 'source_ref' }, { key: 'credit', label: 'Billed', unit: 'usd' }, { key: 'debit', label: 'Paid', unit: 'usd' }]} /></Card>
      <Card title="Bill PDFs"><DataTable rows={d.data.documents as Row[]} empty="No documents." columns={[{ key: 'doc_file' }, { key: 'invoice_date' }, { key: 'total', unit: 'usd' }, { key: 'route', chip: true }, { key: 'issues' }]} /></Card>
      <Source data={d.data} />
    </>
  )
}

function Project({ id }: { id: string }) {
  const d = useTool('get_project_detail', { project_id: id })
  if (!d.data) return <Loading state={d} />
  const p = (d.data.project ?? {}) as Row
  const last = (d.data.rows as Row[]).at(-1) ?? {}
  return (
    <>
      <p className="muted">{String(p.project_name ?? '')} · {String(p.project_type ?? '').replace('_', ' ')} · {String(p.customer_id ?? '')} · contract {usd(p.contract_value)}</p>
      <div className="grid cols-3">
        <div className="card kpi"><div className="label">EAC vs budget</div><div className="value">{usd(last.eac)}</div><div className="note">budget {usd(last.budget)}</div></div>
        <div className="card kpi"><div className="label">% complete</div><div className="value">{last.pct_complete != null ? `${((last.pct_complete as number) * 100).toFixed(0)}%` : '—'}</div></div>
        <div className="card kpi"><div className="label">Unbilled</div><div className="value">{usd(last.unbilled ?? 0)}</div></div>
      </div>
      <Card title="Earned vs billed"><Trend rows={d.data.rows} x="month" y="earned_to_date" /></Card>
      <Card title="By month"><DataTable rows={d.data.rows} columns={[{ key: 'month' }, { key: 'actual_to_date', unit: 'usd' }, { key: 'eac', unit: 'usd' }, { key: 'earned_to_date', unit: 'usd' }, { key: 'billed_to_date', unit: 'usd' }, { key: 'unbilled', unit: 'usd' }, { key: 'deferred', unit: 'usd' }]} /></Card>
      <Card title="Invoices"><DataTable rows={d.data.invoices as Row[]} empty="No invoices." columns={[{ key: 'invoice_ref' }, { key: 'invoice_date' }, { key: 'amount', unit: 'usd' }, { key: 'balance', unit: 'usd' }, { key: 'status', chip: true }, { key: 'is_disputed', label: 'Disputed', flag: 'bad' }]} /></Card>
      {(d.data.exceptions as Row[]).length > 0 && <Card title="Exceptions"><DataTable rows={d.data.exceptions as Row[]} columns={[{ key: 'exception_type', chip: true }, { key: 'detail' }]} /></Card>}
      <Source data={d.data} />
    </>
  )
}

function Kpi({ id }: { id: string }) {
  const trend = useTool('get_kpi_trend', { metric: id })
  const def = useTool('get_metric_definition', { metric: id })
  const m = (def.data?.rows as Row[] | undefined)?.[0]
  return (
    <>
      {m && <p className="muted">{String(m.formula ?? m.definition ?? '')}</p>}
      <Card title="By month">{trend.data ? <Trend rows={trend.data.rows} x="month" y="value" unit={String(m?.unit ?? 'usd')} /> : <Loading state={trend} />}</Card>
      {trend.data && <Card title="Values"><DataTable rows={[...trend.data.rows].reverse()} columns={[{ key: 'month' }, { key: 'value', unit: String(m?.unit ?? '') as 'usd' }]} /></Card>}
      {m && <Card title="Definition"><DataTable rows={[m]} columns={Object.keys(m).filter((k) => !['metric_name'].includes(k)).map((k) => ({ key: k }))} /></Card>}
    </>
  )
}

export function Drawer({ entity, onClose }: { entity: Entity; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  const title = { customer: 'Customer', vendor: 'Vendor', project: 'Project', kpi: 'Metric' }[entity.kind]
  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label={`${title} ${entity.id}`}>
        <div className="drawer-head">
          <div><div className="faint">{title}</div><h2>{entity.id}</h2></div>
          <div style={{ display: 'flex', gap: 6 }}>
            <AskButton text={`Tell me about ${entity.kind} ${entity.id}: what stands out and what needs action?`}>Ask</AskButton>
            <button className="btn small" onClick={onClose}>Close</button>
          </div>
        </div>
        {entity.kind === 'customer' && <Customer id={entity.id} />}
        {entity.kind === 'vendor' && <Vendor id={entity.id} />}
        {entity.kind === 'project' && <Project id={entity.id} />}
        {entity.kind === 'kpi' && <Kpi id={entity.id} />}
      </aside>
    </>
  )
}
