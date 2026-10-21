// Bookkeeping: the bank statement reconciled to GL cash, journal entries keyed by hand (or drafted from a bank item)
// that post only once approved, and the trial balance including them.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Dash, KpiRow } from '../components/Dash'
import { api, fmt, type Row } from '../api'
import { AskButton, Card, Chip, DataTable, Loading } from '../components/common'

const usd = (v: unknown) => fmt('amount', Number(v ?? 0), 'usd')
const num = (v: unknown) => Number(v ?? 0)
// reconciliations tie to the cent, so their figures are shown in full
const cents = (v: unknown) => `${num(v) < 0 ? '−' : ''}$${Math.abs(num(v)).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

type Line = { account_id: string; entity_id: string; debit: string; credit: string; memo: string }
type Draft = { entry_date: string; memo: string; lines: Line[]; source_items: string[] }
type Books = {
  accounts: { rows: Row[]; entities: string[] }
  open_periods: { from: string; to: string }
  entries: Row[]
  trial_balance: { month: string; rows: Row[]; totals: { debit: number; credit: number }; balanced: boolean }
  bank: { month: string; months: string[]; rows: Row[]; items: Row[]; note?: string }
}

const ITEM_LABEL: Record<string, string> = {
  deposit_in_transit: 'Deposit in transit', outstanding_payment: 'Outstanding payment', bank_fee: 'Bank fee',
  interest: 'Interest', unrecorded_bank_item: 'Not in ledger', ledger_error: 'Ledger error',
}
const STATUS_KIND: Record<string, 'good' | 'warn' | 'bad' | 'info'> = {
  posted: 'good', 'awaiting approval': 'warn', rejected: 'bad', reversed: 'info',
}
const blankLine = (entity = 'US01'): Line => ({ account_id: '', entity_id: entity, debit: '', credit: '', memo: '' })

export function Bookkeeping() {
  return <Dash><Body /></Dash>
}

function Body() {
  const [month, setMonth] = useState<string>()
  const [data, setData] = useState<Books>()
  const [error, setError] = useState<string>()
  const [draft, setDraft] = useState<Draft>()
  const formRef = useRef<HTMLDivElement>(null)
  const load = useCallback(() => {
    fetch(`/api/bookkeeping${month ? `?month=${month}` : ''}`)
      .then(async (r) => { if (!r.ok) throw new Error(await r.text()); return r.json() as Promise<Books> })
      .then(setData).catch((e) => setError(String(e)))
  }, [month])
  useEffect(load, [load])

  if (!data) return <div className="page"><Loading state={{ loading: !error, error }} /></div>
  const bank = data.bank
  const rows = bank.rows ?? []
  const items = bank.items ?? []
  const toBook = items.filter((i) => i.needs_journal_entry && !(i.booking as Row | null))
  const pending = data.entries.filter((e) => e.status === 'awaiting approval')
  const reconciles = rows.every((r) => num(r.unexplained_difference) === 0)
  const tb = data.trial_balance
  const startDraft = (d: Draft) => { setDraft(d); setTimeout(() => formRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50) }

  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Bookkeeping</h1><p>Bank reconciliation, journal entries and the trial balance · books open from {data.open_periods.from}</p></div>
        <AskButton text="Walk me through this month's bank reconciliation and draft the journal entries for the items that still need booking.">Ask the assistant</AskButton>
      </div>
      <KpiRow items={[
        { label: 'Cash per bank', value: usd(rows.reduce((a, r) => a + num(r.bank_balance), 0)), note: `${rows.length} accounts · statement ${bank.month}` },
        { label: 'Cash per ledger', value: usd(rows.reduce((a, r) => a + num(r.gl_balance), 0)), note: 'GL account 1000, all entities' },
        { label: 'Bank reconciliation', value: reconciles ? 'Reconciles' : 'Difference', tone: reconciles ? 'good' : 'bad',
          note: reconciles ? 'every difference is a known item' : 'unexplained difference to investigate' },
        { label: 'Bank items to book', value: String(toBook.length), tone: toBook.length ? 'ok' : 'good',
          note: `${usd(toBook.reduce((a, i) => a + num(i.amount), 0))} net: fees, interest, corrections` },
        { label: 'Entries awaiting approval', value: String(pending.length), tone: pending.length ? 'ok' : null, note: 'approval posts them' },
        { label: 'Trial balance', value: tb.balanced ? 'Balanced' : 'Out of balance', tone: tb.balanced ? 'good' : 'bad',
          note: `${usd(tb.totals.debit)} debits = credits` },
      ]} />

      <Card title={`Bank reconciliation · ${bank.month}`} sub={bank.note}
        right={<div className="segmented">{(bank.months ?? []).map((m) => <button key={m} className={m === bank.month ? 'on' : ''} onClick={() => setMonth(m)}>{m}</button>)}</div>}>
        <div className="grid cols-3">
          {rows.map((r) => <RecStatement key={String(r.entity_id)} r={r} />)}
        </div>
      </Card>

      <Card title="Reconciling items" sub="Bank-side items clear on their own; book-side items need a journal entry. Draft one from the item, check it, submit.">
        <DataTable title="bank-reconciling-items" rows={items} columns={[
          { key: 'entity_id', label: 'Entity' },
          { key: 'item_type', label: 'Type', render: (r) => <Chip value={ITEM_LABEL[String(r.item_type)] ?? String(r.item_type)} kind={r.needs_journal_entry ? 'warn' : 'info'} /> },
          { key: 'item_date', label: 'Date' }, { key: 'description' }, { key: 'reference' },
          { key: 'amount', unit: 'usd' }, { key: 'days_outstanding', label: 'Days' }, { key: 'action' },
          { key: 'booking', label: 'Entry', render: (r) => {
            const b = r.booking as Row | null
            if (!r.needs_journal_entry) return <span className="muted">clears itself</span>
            if (b) return <Chip value={`${String(b.entry_id)} · ${String(b.status)}`} kind={STATUS_KIND[String(b.status)]} />
            return <button className="btn small primary" onClick={() => startDraft(r.suggested_entry as Draft)}>Draft entry</button>
          } },
        ]} />
      </Card>

      <div ref={formRef}>
        <EntryForm data={data} draft={draft} onDone={() => { setDraft(undefined); load() }} />
      </div>

      <Card title="Journal entries" sub="Every manual entry and its approval status. Approve posts it; undo reverses a posted entry."
        right={<a className="btn small" href="/api/journal-entries.csv">Export for ERP import (CSV)</a>}>
        <Entries entries={data.entries} accounts={data.accounts.rows} onChange={load} />
      </Card>

      <Card title={`Trial balance · ${tb.month}`} sub="Posted ledger plus posted manual entries. Balance sheet accounts are cumulative; income statement accounts are year to date.">
        <DataTable title="trial-balance" pageSize={40} rows={tb.rows} columns={[
          { key: 'account_id', label: 'Account' }, { key: 'account_name', label: 'Name' },
          { key: 'ledger_balance', label: 'Ledger', unit: 'usd' }, { key: 'manual_entries', label: 'Manual entries', unit: 'usd' },
          { key: 'debit', unit: 'usd' }, { key: 'credit', unit: 'usd' },
        ]} />
        <div className="tb-total">
          <span>Total debits <b>{usd(tb.totals.debit)}</b></span><span>Total credits <b>{usd(tb.totals.credit)}</b></span>
          <Chip value={tb.balanced ? 'Balanced' : 'Out of balance'} kind={tb.balanced ? 'good' : 'bad'} />
        </div>
      </Card>
    </div>
  )
}

function RecStatement({ r }: { r: Row }) {
  const line = (label: string, v: unknown, strong = false) => (
    <div className={`rec-line${strong ? ' strong' : ''}`}><span>{label}</span><span>{cents(v)}</span></div>
  )
  const diff = num(r.unexplained_difference)
  return (
    <div className="rec-statement">
      <div className="rec-head"><b>{String(r.entity_id)}</b><span className="muted">{String(r.bank_name)} · {String(r.bank_account_id)}</span></div>
      {line('Balance per bank statement', r.bank_balance)}
      {line(`+ Deposits in transit (${String(r.deposits_in_transit_count)})`, r.deposits_in_transit)}
      {line(`− Outstanding payments (${String(r.outstanding_payments_count)})`, r.outstanding_payments)}
      {line('Adjusted bank balance', r.adjusted_bank_balance, true)}
      <div className="rec-gap" />
      {line('Balance per ledger (GL 1000)', r.gl_balance)}
      {line('+ Bank items not yet booked', r.unrecorded_bank_items)}
      {line('± Ledger errors', r.ledger_errors)}
      {line('Adjusted book balance', r.adjusted_book_balance, true)}
      <div className="rec-foot">
        <Chip value={diff === 0 ? 'Reconciled' : `Difference ${cents(diff)}`} kind={diff === 0 ? 'good' : 'bad'} />
        {num(r.still_to_book) !== 0 && <span className="muted">{cents(r.still_to_book)} still to book</span>}
      </div>
    </div>
  )
}

function EntryForm({ data, draft, onDone }: { data: Books; draft?: Draft; onDone: () => void }) {
  const today = `${data.open_periods.to}-01`
  const empty = (): Draft => ({ entry_date: today, memo: '', lines: [blankLine(), blankLine()], source_items: [] })
  const [d, setD] = useState<Draft>(draft ?? empty())
  const [errors, setErrors] = useState<string[]>([])
  const [saved, setSaved] = useState<string>()
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (draft) { setD({ ...draft, lines: draft.lines.map((l) => ({ ...blankLine(), ...l })) }); setErrors([]); setSaved(undefined) } }, [draft])
  const accounts = data.accounts.rows
  const dr = d.lines.reduce((a, l) => a + (Number(l.debit) || 0), 0)
  const cr = d.lines.reduce((a, l) => a + (Number(l.credit) || 0), 0)
  const balanced = Math.abs(dr - cr) < 0.005 && dr > 0
  const set = (i: number, patch: Partial<Line>) => setD({ ...d, lines: d.lines.map((l, j) => (j === i ? { ...l, ...patch } : l)) })
  const submit = async () => {
    setBusy(true); setErrors([]); setSaved(undefined)
    try {
      const res = await fetch('/api/journal-entries', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(d) })
      const body = await res.json()
      if (!res.ok) { setErrors(body.detail?.errors ?? [String(body.detail ?? res.status)]); return }
      setSaved(`${body.entry_id} submitted. Approve it under Journal entries to post it.`)
      setD(empty())
      onDone()
    } finally { setBusy(false) }
  }
  const label = useMemo(() => Object.fromEntries(accounts.map((a) => [String(a.account_id), `${String(a.account_id)} · ${String(a.account_name)}`])), [accounts])
  return (
    <Card title="New journal entry" sub={`Open periods ${data.open_periods.from} to ${data.open_periods.to}; earlier months are locked. Each entity must balance.`}
      right={d.source_items.length ? <Chip value={`books ${d.source_items.join(', ')}`} kind="info" /> : undefined}>
      <div className="form-row">
        <label>Date<input type="date" className="table-search" value={d.entry_date} onChange={(e) => setD({ ...d, entry_date: e.target.value })} /></label>
        <label style={{ flex: 1, minWidth: 220 }}>Memo<input className="table-search" value={d.memo} placeholder="What the entry is for" onChange={(e) => setD({ ...d, memo: e.target.value })} /></label>
      </div>
      <div className="table-wrap">
        <table className="je-lines">
          <thead><tr><th>Account</th><th>Entity</th><th>Debit</th><th>Credit</th><th>Line memo</th><th /></tr></thead>
          <tbody>
            {d.lines.map((l, i) => (
              <tr key={i}>
                <td><select className="table-search" value={l.account_id} onChange={(e) => set(i, { account_id: e.target.value })}>
                  <option value="">Choose an account…</option>
                  {accounts.map((a) => <option key={String(a.account_id)} value={String(a.account_id)}>{label[String(a.account_id)]}</option>)}
                </select></td>
                <td><select className="table-search" value={l.entity_id} onChange={(e) => set(i, { entity_id: e.target.value })}>
                  {data.accounts.entities.map((x) => <option key={x}>{x}</option>)}
                </select></td>
                <td><input className="table-search num" inputMode="decimal" value={l.debit} onChange={(e) => set(i, { debit: e.target.value, credit: e.target.value ? '' : l.credit })} /></td>
                <td><input className="table-search num" inputMode="decimal" value={l.credit} onChange={(e) => set(i, { credit: e.target.value, debit: e.target.value ? '' : l.debit })} /></td>
                <td><input className="table-search" value={l.memo} onChange={(e) => set(i, { memo: e.target.value })} /></td>
                <td>{d.lines.length > 2 && <button className="btn small" aria-label="Remove line" onClick={() => setD({ ...d, lines: d.lines.filter((_, j) => j !== i) })}>×</button>}</td>
              </tr>
            ))}
          </tbody>
          <tfoot><tr>
            <td colSpan={2}><button className="btn small" onClick={() => setD({ ...d, lines: [...d.lines, blankLine(d.lines[0]?.entity_id)] })}>Add line</button></td>
            <td className="num"><b>{cents(dr)}</b></td><td className="num"><b>{cents(cr)}</b></td>
            <td colSpan={2}><Chip value={balanced ? 'Balanced' : dr + cr === 0 ? 'Enter amounts' : `Off by ${cents(Math.abs(dr - cr))}`} kind={balanced ? 'good' : 'warn'} /></td>
          </tr></tfoot>
        </table>
      </div>
      {errors.length > 0 && <ul className="je-errors">{errors.map((e) => <li key={e}>{e}</li>)}</ul>}
      {saved && <div className="je-saved">{saved}</div>}
      <div className="form-row" style={{ marginTop: 10 }}>
        <button className="btn primary" disabled={busy || !balanced} onClick={submit}>Submit for approval</button>
        <button className="btn" onClick={() => { setD(empty()); setErrors([]) }}>Clear</button>
        <span className="muted">Nothing posts until the entry is approved.</span>
      </div>
    </Card>
  )
}

function Entries({ entries, accounts, onChange }: { entries: Row[]; accounts: Row[]; onChange: () => void }) {
  const names = Object.fromEntries(accounts.map((a) => [String(a.account_id), String(a.account_name)]))
  const act = (id: string, decision: 'approve' | 'reject' | 'undo') => api.decide(id, decision).then(onChange)
  if (!entries.length) return <div className="muted">No manual entries yet. Draft one from a bank item above, or key one in.</div>
  return (
    <DataTable title="journal-entries" rows={entries} columns={[
      { key: 'entry_id', label: 'Entry' }, { key: 'entry_date', label: 'Date' }, { key: 'memo' },
      { key: 'lines', label: 'Lines', render: (r) => <span className="je-legs">{(r.lines as Line[]).map((l, i) => (
        <span key={i}>{Number(l.debit) ? 'Dr' : 'Cr'} {l.account_id} {names[l.account_id] ?? ''} · {l.entity_id} · {usd(Number(l.debit) || Number(l.credit))}</span>
      ))}</span> },
      { key: 'total', label: 'Amount', unit: 'usd' },
      { key: 'status', render: (r) => <Chip value={String(r.status)} kind={STATUS_KIND[String(r.status)]} /> },
      { key: 'action_id', label: '', render: (r) => r.status === 'awaiting approval'
        ? <span style={{ display: 'flex', gap: 6 }}><button className="btn small primary" onClick={() => act(String(r.action_id), 'approve')}>Approve</button>
            <button className="btn small" onClick={() => act(String(r.action_id), 'reject')}>Reject</button></span>
        : r.status === 'posted' ? <button className="btn small" onClick={() => act(String(r.action_id), 'undo')}>Reverse</button> : null },
    ]} />
  )
}
