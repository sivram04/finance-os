// Explore: answer a specific question without waiting for a dashboard. Three ways in:
//   Ledger   any slice of the books (months, account, department, entity, customer, vendor, entry type, memo text),
//            grouped by any dimension, with the monthly trend and the journal lines behind it
//   Metrics  any governed metric (or several) over time, side by side
//   Lookup   jump straight to a customer, vendor or project
import { useEffect, useMemo, useState } from 'react'
import { Columns, KpiRow, Trend } from '../components/Dash'
import { fmt, type Row } from '../api'
import { AskButton, Card, DataTable, Loading, Source, useTool, useWorkspace } from '../components/common'

const usd = (v: number) => fmt('amount', v, 'usd')
const GROUPS = [['account', 'Account'], ['month', 'Month'], ['department', 'Department'], ['customer', 'Customer'], ['vendor', 'Vendor'],
  ['entity', 'Legal entity'], ['rollup', 'P&L line'], ['account_type', 'Account type'], ['entry_type', 'Entry type']] as const

type Q = Record<string, string>

function Select({ label, value, onChange, options, any = 'Any' }: { label: string; value: string; onChange: (v: string) => void; options: (string | [string, string])[]; any?: string }) {
  return (
    <label className="explore-field">{label}
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {any && <option value="">{any}</option>}
        {options.map((o) => { const [v, l] = Array.isArray(o) ? o : [o, o]; return <option key={v} value={v}>{l}</option> })}
      </select>
    </label>
  )
}

export function Explore() {
  const [tab, setTab] = useState<'ledger' | 'metrics' | 'lookup'>('ledger')
  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Explore</h1><p>Ask something specific: slice the books any way, compare metrics over any years, or open any customer, vendor or project.</p></div>
        <AskButton text="I have a specific question about our numbers: ">Ask the assistant instead</AskButton>
      </div>
      <div className="segmented" style={{ marginBottom: 12 }}>
        {([['ledger', 'Ledger'], ['metrics', 'Metrics'], ['lookup', 'Look up']] as const).map(([k, l]) =>
          <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{l}</button>)}
      </div>
      {tab === 'ledger' && <Ledger />}
      {tab === 'metrics' && <Metrics />}
      {tab === 'lookup' && <Lookup />}
    </div>
  )
}

function Ledger() {
  const opts = useTool('explore_options')
  const o = (opts.data ?? {}) as Record<string, unknown>
  const months = (o.months ?? []) as string[]
  // a link (e.g. "Show transactions" under an assistant answer) can open Explore with filters: #explore?customer_id=EN-001
  const fromLink = (): Q | null => {
    const qs = location.hash.split('?')[1]
    return qs ? { group_by: 'account', ...Object.fromEntries(new URLSearchParams(qs)) } : null
  }
  const [q, setQ] = useState<Q>(() => fromLink() ?? { group_by: 'account', account_type: 'opex' })
  const [run, setRun] = useState<Q>(q)
  useEffect(() => {  // default range: the last 12 months
    if (months.length && !q.start_month) { const next = { ...q, start_month: months[Math.max(0, months.length - 12)], end_month: months.at(-1)! }; setQ(next); setRun(next) }
  }, [months.length])  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const onHash = () => { const l = fromLink(); if (l) { setQ(l); setRun(l) } }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  const args = useMemo(() => Object.fromEntries(Object.entries(run).filter(([, v]) => v)), [run])
  const r = useTool('explore_ledger', args)
  const set = (k: string) => (v: string) => setQ({ ...q, [k]: v })
  const top = ((r.data?.rows ?? []) as Row[]).reduce<Row | null>((m, x) => (!m || Math.abs(Number(x.amount)) > Math.abs(Number(m.amount)) ? x : m), null)
  if (!opts.data) return <Loading state={opts} />
  const accounts = ((o.accounts ?? []) as Row[]).map((a) => [String(a.account_id), `${a.account_id} ${a.account_name}`] as [string, string])
  const groupKey = ({ customer: 'customer_id', vendor: 'vendor_id', department: 'department_id', entity: 'entity_id' } as Record<string, string>)[String(run.group_by)] ?? String(run.group_by)
  return (
    <>
      <Card title="Question" sub="Pick any mix of filters, then Run. Leave a filter on Any to include everything.">
        <div className="explore-grid">
          <Select label="From" value={q.start_month ?? ''} onChange={set('start_month')} options={months} any="" />
          <Select label="To" value={q.end_month ?? ''} onChange={set('end_month')} options={months} any="" />
          <Select label="Account type" value={q.account_type ?? ''} onChange={set('account_type')} options={(o.account_types ?? []) as string[]} />
          <Select label="P&L / BS line" value={q.rollup ?? ''} onChange={set('rollup')} options={(o.rollups ?? []) as string[]} />
          <Select label="Account" value={q.account ?? ''} onChange={set('account')} options={accounts} />
          <Select label="Department" value={q.department ?? ''} onChange={set('department')} options={(o.departments ?? []) as string[]} />
          <Select label="Legal entity" value={q.entity ?? ''} onChange={set('entity')} options={(o.entities ?? []) as string[]} />
          <Select label="Customer" value={q.customer_id ?? ''} onChange={set('customer_id')} options={(o.customers ?? []) as string[]} />
          <Select label="Vendor" value={q.vendor_id ?? ''} onChange={set('vendor_id')} options={(o.vendors ?? []) as string[]} />
          <Select label="Entry type" value={q.entry_type ?? ''} onChange={set('entry_type')} options={(o.entry_types ?? []) as string[]} />
          <label className="explore-field">Memo contains<input value={q.text ?? ''} onChange={(e) => set('text')(e.target.value)} placeholder="e.g. payroll, GPU" /></label>
          <Select label="Group by" value={q.group_by ?? 'account'} onChange={set('group_by')} options={GROUPS.map(([v, l]) => [v, l] as [string, string])} any="" />
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          <button className="btn" onClick={() => setRun(q)}>Run</button>
          <button className="btn small" onClick={() => { const n = { group_by: 'account', start_month: q.start_month, end_month: q.end_month }; setQ(n); setRun(n) }}>Reset filters</button>
        </div>
      </Card>
      {r.data ? (
        <>
          <KpiRow items={[
            { label: 'Total', value: usd(Number(r.data.total)), note: `${String(r.data.start)} to ${String(r.data.end)}` },
            { label: 'Journal lines', value: Number(r.data.line_count).toLocaleString(), note: 'behind this total' },
            { label: `Largest ${GROUPS.find(([v]) => v === run.group_by)?.[1].toLowerCase() ?? ''}`, value: top ? String(top[groupKey]) : '—', note: top ? usd(Number(top.amount)) : '' },
          ]} />
          <div className="grid cols-2">
            <Card title="By month" sub="The selection's monthly total · drag the slider to zoom"><Columns rows={(r.data.trend ?? []) as Row[]} x="month" y="amount" /></Card>
            <Card title={`By ${GROUPS.find(([v]) => v === run.group_by)?.[1].toLowerCase()}`} sub="Click a customer or vendor to open its details">
              <DataTable title="explore" rows={r.data.rows} columns={[{ key: groupKey, label: GROUPS.find(([v]) => v === run.group_by)?.[1] }, { key: 'amount', unit: 'usd' }, { key: 'lines', unit: 'count' }]} />
            </Card>
          </div>
          <Card title="Largest journal lines" sub="The entries behind the total, biggest first">
            <DataTable title="journal_lines" rows={(r.data.top_lines ?? []) as Row[]} columns={[{ key: 'entry_date' }, { key: 'entry_id' }, { key: 'entry_type', chip: true }, { key: 'memo' }, { key: 'account_id', label: 'Acct' }, { key: 'account_name' },
              { key: 'department_id', label: 'Dept' }, { key: 'entity_id', label: 'Entity' }, { key: 'customer_id' }, { key: 'vendor_id' }, { key: 'amount', unit: 'usd' }]} />
            <Source data={r.data} />
          </Card>
        </>
      ) : <Loading state={r} />}
    </>
  )
}

function Metrics() {
  const opts = useTool('explore_options')
  const metrics = ((opts.data?.metrics ?? []) as Row[])
  const [picked, setPicked] = useState<string[]>(['revenue', 'arr'])
  const a = useTool('get_kpi_trend', { metric: picked[0] ?? 'revenue' })
  const b = useTool('get_kpi_trend', { metric: picked[1] ?? picked[0] ?? 'revenue' })
  const c = useTool('get_kpi_trend', { metric: picked[2] ?? picked[0] ?? 'revenue' })
  const res = [a, b, c].slice(0, Math.max(1, picked.length))
  const meta = (m: string) => metrics.find((x) => x.metric_name === m)
  const rows = useMemo(() => {
    const by = new Map<string, Row>()
    res.forEach((t, i) => ((t.data?.rows ?? []) as Row[]).forEach((r) => { const k = String(r.month); by.set(k, { ...(by.get(k) ?? { month: k }), [picked[i]]: r.value }) }))
    return [...by.values()].sort((x, y) => String(x.month).localeCompare(String(y.month)))
  }, [a.data, b.data, c.data, picked])  // eslint-disable-line react-hooks/exhaustive-deps
  if (!opts.data) return <Loading state={opts} />
  const toggle = (m: string) => setPicked(picked.includes(m) ? picked.filter((x) => x !== m) : [...picked, m].slice(-3))
  return (
    <>
      <Card title="Pick up to three metrics" sub="From the governed metric catalog · the Period control at the top sets the years">
        <div className="metric-picker">
          {metrics.map((m) => <button key={String(m.metric_name)} className={`filter-chip ${picked.includes(String(m.metric_name)) ? 'on' : ''}`} onClick={() => toggle(String(m.metric_name))}>{String(m.label)}</button>)}
        </div>
      </Card>
      <div className={`grid cols-${Math.min(3, picked.length) || 1}`}>
        {picked.map((m, i) => (
          <Card key={m} title={String(meta(m)?.label ?? m)} sub={`by month · ${String(meta(m)?.unit ?? '')}`}>
            {res[i]?.data ? <Trend rows={rows} x="month" unit={String(meta(m)?.unit ?? 'usd')} series={[{ key: m, label: String(meta(m)?.label ?? m) }]} /> : <Loading state={res[i]} />}
          </Card>
        ))}
      </div>
      <Card title="Side by side" sub="Every month of the picked metrics">
        <DataTable title="metrics" rows={rows} columns={[{ key: 'month' }, ...picked.map((m) => ({ key: m, label: String(meta(m)?.label ?? m), unit: (String(meta(m)?.unit) === 'usd' ? 'usd' : undefined) as 'usd' | undefined }))]} />
      </Card>
    </>
  )
}

function Lookup() {
  const opts = useTool('explore_options')
  const { inspect } = useWorkspace()
  const [q, setQ] = useState('')
  if (!opts.data) return <Loading state={opts} />
  const items = [
    ...((opts.data.customers ?? []) as string[]).map((id) => ({ kind: 'customer' as const, id })),
    ...((opts.data.vendors ?? []) as string[]).map((id) => ({ kind: 'vendor' as const, id })),
  ]
  const hits = q ? items.filter((x) => x.id.toLowerCase().includes(q.toLowerCase())).slice(0, 40) : items.slice(0, 40)
  return (
    <Card title="Look up" sub="Type an ID (EN-001, MM-004, NIMBUS…) or a project ID like P-103, then open it">
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Customer, vendor or project ID" style={{ flex: 1 }} />
        {/^P-\d+/i.test(q) && <button className="btn" onClick={() => inspect({ kind: 'project', id: q.toUpperCase() })}>Open project {q.toUpperCase()}</button>}
      </div>
      <div className="metric-picker">
        {hits.map((x) => <button key={`${x.kind}-${x.id}`} className="filter-chip" onClick={() => inspect(x)}>{x.kind}: <b>{x.id}</b></button>)}
      </div>
    </Card>
  )
}
