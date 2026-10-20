import { MonthSummary, Scorecard } from './Exec'
import { useEffect, useState } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, fmt, type Action, type Row } from '../api'
import { Card, Chip, Loading, useTool, useWorkspace, type Page } from '../components/common'
import { usePeriod } from '../components/Dash'
import { ApprovalEvidence, useEvidence, VerdictBadge } from '../components/ApprovalEvidence'

const QUICK = [
  ['Summarize what needs attention', 'What needs my attention right now? Group it by urgency.'],
  ['Explain revenue vs. budget', 'Why is usage revenue below budget this year? Show the drivers.'],
  ['Review the AP inbox', 'Review the AP inbox and recommend what to approve or reject, with reasons.'],
  ['Prepare collections', 'Who should we chase for payment first, and is anything on hold?'],
  ['Check the numbers are trustworthy', 'Are all reconciliations passing? Is any number untrusted right now?'],
]


const MODULES: { page: Page; name: string; desc: string; area: string }[] = [
  { page: 'revenue', name: 'Revenue & margins', desc: 'Customers, churn, unit economics', area: 'Unit economics' },
  { page: 'spend', name: 'Tech spend', desc: 'GPU and cloud, capacity, forecast', area: 'Tech spend' },
  { page: 'budget', name: 'Budget vs. actual', desc: 'Variances and their drivers', area: 'Budget' },
  { page: 'projects', name: 'Projects', desc: 'EAC, unbilled work, funding', area: 'Projects' },
  { page: 'billing', name: 'Billing', desc: 'Billing run and validation', area: 'Billing' },
  { page: 'ar', name: 'Receivables', desc: 'Aging, collections, disputes', area: 'AR' },
  { page: 'ap', name: 'AP inbox', desc: 'Vendor bills read by AI, checked by rules', area: 'AP' },
  { page: 'trust', name: 'Trust', desc: 'Reconciliations and controls', area: 'Trust' },
]

function PeriodCard({ title, start, end }: { title: string; start: string; end: string }) {
  const s = useTool('get_pnl', { start_month: start, end_month: end, group_by: 'rollup' })
  const total = (type: string) => (s.data?.rows ?? []).filter((r: Row) => r.account_type === type).reduce((a, r) => a + (r.amount as number), 0)
  const revenue = total('revenue'), costs = total('cogs') + total('opex')
  return (
    <Card title={title} sub={start === end ? start : `${start} → ${end}`}>
      {s.data ? (
        <div className="period">
          <div className="line"><span>Revenue</span><span>{fmt('revenue', revenue)}</span></div>
          <div className="line"><span>Costs</span><span>{fmt('cost', costs)}</span></div>
          <div className="line"><span>Operating result</span><span style={{ color: revenue - costs < 0 ? 'var(--bad)' : 'var(--good)' }}>{fmt('amount', revenue - costs)}</span></div>
        </div>
      ) : <Loading state={s} />}
    </Card>
  )
}

function PositionChart() {
  const [metric, setMetric] = useState('revenue')
  const s = useTool('get_kpi_trend', { metric })
  const opts: [string, string][] = [['revenue', 'Revenue'], ['net_burn', 'Net burn'], ['closing_cash', 'Cash'], ['arr', 'Run-rate ARR']]
  return (
    <Card title="Company position" sub="Monthly, from the general ledger"
      right={<div className="segmented">{opts.map(([k, l]) => <button key={k} className={metric === k ? 'on' : ''} onClick={() => setMetric(k)}>{l}</button>)}</div>}>
      {s.data ? (
        <div style={{ height: 240 }}>
          <ResponsiveContainer>
            <AreaChart data={s.data.rows} margin={{ left: 8, right: 8, top: 8 }}>
              <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--accent)" stopOpacity={0.25} /><stop offset="100%" stopColor="var(--accent)" stopOpacity={0} /></linearGradient></defs>
              <CartesianGrid stroke="var(--border)" vertical={false} />
              <XAxis dataKey="month" tick={{ fontSize: 11, fill: 'var(--faint)' }} tickLine={false} axisLine={false} />
              <YAxis tickFormatter={(v) => fmt(metric, v as number, 'usd')} tick={{ fontSize: 11, fill: 'var(--faint)' }} tickLine={false} axisLine={false} width={64} />
              <Tooltip formatter={(v) => fmt(metric, v as number, 'usd')} contentStyle={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }} />
              <Area type="monotone" dataKey="value" stroke="var(--accent)" strokeWidth={2} fill="url(#g)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      ) : <Loading state={s} />}
    </Card>
  )
}

function NeedsYou() {
  const s = useTool('get_attention_items')
  const { go, ask } = useWorkspace()
  return (
    <Card title="Needs you" sub={s.data ? `${s.data.row_count} open items across ${Object.keys((s.data.counts_by_area as object) ?? {}).length} areas` : undefined}
      right={<button className="btn small" onClick={() => ask('What needs my attention right now? Group it by urgency.')}>Summarize</button>}>
      {s.data ? (
        <div className="attention">
          {s.data.rows.map((r, i) => (
            <div className="item" key={i}>
              <div><Chip value={r.severity as string} /> </div>
              <div><div className="title">{r.title as string}</div><div className="detail">{r.detail as string}</div></div>
              <div style={{ display: 'flex', gap: 6 }}>
                <span className="chip">{r.area as string}</span>
                <button className="btn small" onClick={() => go(r.page as Page)}>Open</button>
              </div>
            </div>
          ))}
        </div>
      ) : <Loading state={s} />}
    </Card>
  )
}

function PendingItem({ a, decide }: { a: Action; decide: (id: string, d: 'approve' | 'reject') => void }) {
  const ev = useEvidence(a.id)
  return (
    <div className="item approval-item">
      <div style={{ display: 'grid', gap: 4, alignContent: 'start' }}><Chip value={a.kind.replace(/_/g, ' ')} kind="info" /><VerdictBadge ev={ev} /></div>
      <div className="detail" style={{ color: 'var(--text)' }}>
        {a.preview}
        <ApprovalEvidence action={a} ev={ev} />
      </div>
      <div style={{ display: 'flex', gap: 6 }}>
        <button className="btn small primary" onClick={() => decide(a.id, 'approve')}>Approve</button>
        <button className="btn small" onClick={() => decide(a.id, 'reject')}>Reject</button>
      </div>
    </div>
  )
}

function PendingApprovals() {
  const [items, setItems] = useState<Action[] | null>(null)
  const { refreshKey, refresh } = useWorkspace()
  useEffect(() => { api.actions('pending').then(setItems) }, [refreshKey])
  const decide = async (id: string, d: 'approve' | 'reject') => { await api.decide(id, d); refresh() }
  return (
    <Card title="Waiting for your approval" sub="Prepared by the assistant; nothing happens until you decide · each card shows its checks and what approving does">
      {!items ? <div className="muted">Loading…</div> : items.length === 0 ? <div className="muted">Nothing waiting. Ask the assistant to prepare decisions, e.g. "Review the AP inbox".</div> : (
        <div className="attention scroll-box short">
          {items.map((a) => <PendingItem key={a.id} a={a} decide={decide} />)}
        </div>
      )}
    </Card>
  )
}

export function Home({ asOf }: { asOf?: string }) {
  const { go, ask } = useWorkspace()
  const att = useTool('get_attention_items')
  const counts = (att.data?.counts_by_area ?? {}) as Record<string, number>
  const { period } = usePeriod()
  // a year in the Period control shows that year as of its last closed month (December, or the latest month this year)
  const latest = asOf?.slice(0, 7) ?? ''
  const m = /^\d{4}$/.test(period) && latest && period < latest.slice(0, 4) ? `${period}-12` : latest
  const label = m ? new Date(m + '-01T00:00').toLocaleString('en', { month: 'long', year: 'numeric' }) : '…'
  const year = m.slice(0, 4)
  const qStartMonth = m ? String(Math.floor((Number(m.slice(5, 7)) - 1) / 3) * 3 + 1).padStart(2, '0') : ''
  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Echo Labs · Finance OS</h1><p>Your finance command center. Monthly figures are for {m === latest ? 'the last closed month' : `the last month of ${period}`} ({label}){m !== latest ? ' · pick All in Period to return to the latest month' : ''}.</p></div>
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {QUICK.map(([l, q]) => <button key={l} className="btn" onClick={() => ask(q)}>{l}</button>)}
      </div>
      <Scorecard month={m} />
      <MonthSummary month={m} />
      {m && (
        <div className="grid cols-3">
          <PeriodCard title={m === latest ? 'This month' : 'Month'} start={m} end={m} />
          <PeriodCard title={m === latest ? 'This quarter' : 'Quarter'} start={`${year}-${qStartMonth}`} end={m} />
          <PeriodCard title={m === latest ? 'This year' : `Year ${year}`} start={`${year}-01`} end={m} />
        </div>
      )}
      <PositionChart />
      <div className="grid cols-2 match-column">
        <NeedsYou />
        <div className="grid">
          <PendingApprovals />
          <div className="grid cols-2">
            {MODULES.map((mod) => (
              <button key={mod.page} className="tile" onClick={() => go(mod.page)}>
                <span className="name">{mod.name} {counts[mod.area] ? <span className="chip warn">{counts[mod.area]}</span> : null}</span>
                <span className="desc">{mod.desc}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
