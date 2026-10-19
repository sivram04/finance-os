// One budget variance, end to end: what happened → the source journal lines → the reconciliation chain from the
// source system to the reported number → the root cause in drivers → owner and actions → the CFO's decision, which is
// recorded in the audit log. Reads get_variance_case (the same tool the assistant uses).
import { useEffect, useRef, useState } from 'react'
import { Bridge, KpiRow, Trend } from './Dash'
import { fmt, type Row } from '../api'
import { Card, Chip, DataTable, Loading, Source, useTool, useWorkspace } from './common'

const usd = (v: unknown) => fmt('amount', Number(v ?? 0), 'usd')
const signed = (v: number) => `${v >= 0 ? '+' : '−'}${usd(Math.abs(v))}`

function Step({ n, title, sub, children, right }: { n: number; title: string; sub?: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="case-step">
      <div className="case-num">{n}</div>
      <div className="case-body">
        <div className="case-head"><div><h3>{title}</h3>{sub && <p className="muted">{sub}</p>}</div>{right}</div>
        {children}
      </div>
    </div>
  )
}

export function VarianceCase({ alertId, onClose }: { alertId: string; onClose: () => void }) {
  const d = useTool('get_variance_case', { alert_id: alertId })
  const { ask, inspect } = useWorkspace()
  const [decisions, setDecisions] = useState<Row[]>([])
  const [choice, setChoice] = useState<string>('')
  const [note, setNote] = useState('')
  const [picked, setPicked] = useState<Record<number, boolean>>({})
  const ref = useRef<HTMLDivElement>(null)
  const load = () => fetch(`/api/variance-decisions/${alertId}`).then((r) => r.json()).then(setDecisions)
  useEffect(() => { load(); setChoice(''); setNote(''); setPicked({}); ref.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }, [alertId])  // eslint-disable-line react-hooks/exhaustive-deps
  if (!d.data) return <div ref={ref}><Card title={`Variance case ${alertId}`}><Loading state={d} /></Card></div>
  const c = d.data.case as Row, root = d.data.root_cause as Row
  const comps = (d.data.root_cause_components ?? []) as Row[]
  const actions = (d.data.actions ?? []) as Row[]
  const options = (d.data.decision_options ?? []) as Row[]
  const chain = (d.data.reconciliation_chain ?? []) as Row[]
  const isRev = c.account_type === 'revenue'
  const decide = () => fetch('/api/variance-decisions', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ alert_id: alertId, decision: choice, note, actions: actions.filter((_, i) => picked[i]) }) }).then(load)
  const bridge = isRev && comps.length > 1
    ? { start: { name: 'Budget', value: Number(c.budget) },
        steps: [{ name: 'Growth the budget assumed, not delivered', value: -Number(comps[0].amount) },
          ...comps.slice(1).map((x) => ({ name: String(x.driver), value: Number(x.amount) }))],
        end: { name: 'Actual', value: Number(c.actual) } }
    : null
  return (
    <div ref={ref}>
      <Card title={`Variance case: ${String(c.message)}`} sub={`${String(c.month)} · ${String(c.department)} · ${String(c.account)} · ${alertId}`}
        right={<span style={{ display: 'flex', gap: 6 }}>
          <button className="btn small" onClick={() => ask(`Walk me through variance ${alertId}: source, reconciliation, root cause, owner and the decision you recommend.`)}>Ask the assistant</button>
          <button className="btn small" onClick={onClose}>Close</button></span>}>

        <Step n={1} title="What happened" sub="Favorable is positive for revenue and costs alike">
          <KpiRow items={[
            { label: 'This month', value: signed(Number(c.variance_favorable)), note: `${usd(c.actual)} actual vs ${usd(c.budget)} budget`, tone: Number(c.variance_favorable) < 0 ? 'bad' : 'good' },
            { label: 'Year to date', value: signed((Number(c.ytd_actual) - Number(c.ytd_budget)) * (isRev ? 1 : -1)), note: `${usd(c.ytd_actual)} vs ${usd(c.ytd_budget)}`, tone: (Number(c.ytd_actual) - Number(c.ytd_budget)) * (isRev ? 1 : -1) < 0 ? 'bad' : 'good' },
            { label: 'Full-year landing', value: signed(Number(c.fy_forecast_variance) * (isRev ? 1 : -1)), note: `forecast ${usd(c.fy_forecast)} vs budget ${usd(c.fy_budget)}`, tone: Number(c.fy_forecast_variance) * (isRev ? 1 : -1) < 0 ? 'bad' : 'good' },
            { label: 'Owner', value: String(c.owner), note: `commentary ${String(c.commentary_status)}` },
          ]} />
          <Trend rows={(d.data.trend ?? []) as Row[]} x="month" series={[{ key: 'actual', label: 'Actual' }, { key: 'budget', label: 'Budget', color: '#7a8699', dashed: true }]} />
        </Step>

        <Step n={2} title="Source data" sub={`${String(d.data.source_line_count)} journal lines totalling ${usd(d.data.source_lines_total)} · largest first · click a customer or vendor for its history`}
          right={<button className="btn small" onClick={() => { location.hash = `explore?${new URLSearchParams({ account: String(c.account).split(' ')[0], start_month: String(c.month), end_month: String(c.month), group_by: isRev ? 'customer' : 'entry_type' }).toString()}` }}>Open in Explore</button>}>
          <DataTable title="variance_source_lines" rows={d.data.rows} pageSize={8} columns={[{ key: 'entry_date' }, { key: 'entry_id' }, { key: 'entry_type', chip: true }, { key: 'memo' }, { key: 'source_ref', label: 'Source document' }, { key: 'customer_id' }, { key: 'vendor_id' }, { key: 'entity_id', label: 'Entity' }, { key: 'amount', unit: 'usd' }]} />
        </Step>

        <Step n={3} title="Reconciliation" sub="Source system → general ledger → reported actual, and the approved budget">
          <div className="recon-chain">
            {chain.map((s, i) => (
              <div key={String(s.step)} className={`recon-node ${String(s.status).replace(' ', '-')}`}>
                <div className="muted" style={{ fontSize: 11 }}>{i + 1}. {String(s.step)}</div>
                <div><b>{s.amount != null ? usd(s.amount) : '—'}</b></div>
                <div style={{ fontSize: 12 }}>{String(s.system)}</div>
                <Chip value={String(s.status)} kind={s.status === 'pass' ? 'good' : s.status === 'fail' ? 'bad' : 'info'} />
                <div className="muted" style={{ fontSize: 11 }}>{String(s.detail)}</div>
              </div>
            ))}
          </div>
          {((d.data.reconciliation_checks ?? []) as Row[]).length ? (
            <DataTable rows={d.data.reconciliation_checks as Row[]} columns={[{ key: 'check_name', label: 'Check' }, { key: 'period' },
              ...(['expected', 'actual', 'variance'] as const).map((k) => ({ key: k, render: (r: Row) => (String(r.check_name).startsWith('usage_events') ? `${Number(r[k]).toLocaleString(undefined, { maximumFractionDigits: 0 })} hrs` : usd(r[k])) })), { key: 'status', chip: true }, { key: 'explanation' }]} />
          ) : null}
        </Step>

        <Step n={4} title="Root cause" sub={String(root.classification ?? '')}>
          <p style={{ margin: '0 0 10px' }}>{String(root.summary ?? '')}</p>
          <div className="grid cols-2">
            {bridge ? <Bridge start={bridge.start} steps={bridge.steps} end={bridge.end} /> : (
              <DataTable rows={comps} columns={[{ key: 'driver' }, { key: 'amount', unit: 'usd' }]} />
            )}
            {((d.data.customers ?? []) as Row[]).length ? (
              <DataTable rows={d.data.customers as Row[]} onRow={(r) => inspect({ kind: 'customer', id: String(r.customer_id) })} columns={[{ key: 'customer_id' }, { key: 'december', label: 'December', unit: 'usd' }, { key: 'this_month', label: String(c.month), unit: 'usd' }, { key: 'change', unit: 'usd' }, { key: 'events', label: 'Lifecycle events' }]} />
            ) : <DataTable rows={(d.data.by_entry_type ?? []) as Row[]} columns={[{ key: 'entry_type', chip: true }, { key: 'amount', unit: 'usd' }]} />}
          </div>
        </Step>

        <Step n={5} title="Owner and actions" sub={`Accountable: ${String(c.owner)} · tick the actions the decision commits to`}>
          <DataTable rows={actions.map((a, i) => ({ ...a, i }))} columns={[
            { key: 'i', label: '', render: (r) => <input type="checkbox" checked={!!picked[Number(r.i)]} onChange={(e) => setPicked({ ...picked, [Number(r.i)]: e.target.checked })} /> },
            { key: 'action' }, { key: 'owner', chip: true }, { key: 'due' }, { key: 'why' }]} />
        </Step>

        <Step n={6} title="CFO decision" sub="Recorded with the evidence and committed actions in the audit log">
          <div className="decision-options">
            {options.map((o) => (
              <button key={String(o.option)} className={`decision-option ${choice === o.option ? 'on' : ''}`} onClick={() => setChoice(String(o.option))}>
                <b>{String(o.option)}</b><span>{String(o.effect)}</span>
              </button>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <input className="table-search" style={{ flex: 1 }} placeholder="Decision note (what you decided and why)" value={note} onChange={(e) => setNote(e.target.value)} />
            <button className="btn" disabled={!choice} onClick={decide}>Record decision</button>
          </div>
          {decisions.length ? (
            <DataTable rows={decisions} columns={[{ key: 'decided_at', label: 'Decided', render: (r) => String(r.decided_at).slice(0, 16).replace('T', ' ') }, { key: 'decided_by', label: 'By' }, { key: 'decision', chip: true }, { key: 'note' },
              { key: 'actions', label: 'Committed actions', render: (r) => ((r.actions ?? []) as Row[]).map((a) => `${String(a.action)} (${String(a.owner)})`).join('; ') || '—' }]} />
          ) : <p className="muted">No decision recorded yet.</p>}
        </Step>
        <Source data={d.data} />
      </Card>
    </div>
  )
}
