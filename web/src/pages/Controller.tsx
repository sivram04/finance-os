// Controller: fixed-asset register reconciled to the GL, ASC 842 lease accounting, and audit-style journal-entry
// testing.
import { Bars, Dash, KpiRow, Trend } from '../components/Dash'
import { fmt, type Row } from '../api'
import { AskButton, Card, Chip, DataTable, Loading, useTool } from '../components/common'

const usd = (v: unknown) => fmt('amount', Number(v ?? 0), 'usd')

export function Controller() {
  return <Dash><Body /></Dash>
}

function Body() {
  const fa = useTool('get_fixed_assets')
  const ls = useTool('get_leases')
  const je = useTool('get_journal_entry_tests')
  if (!fa.data || !ls.data || !je.data) return <div className="page"><Loading state={[fa, ls, je].find((s) => s.error) ?? fa} /></div>
  const ft = fa.data.totals as Row, lt = ls.data.totals as Row
  const rec = (fa.data.reconciliation ?? []) as Row[]
  const ties = rec.every((r) => r.status === 'ties')
  const sched = (ls.data.schedule ?? []) as Row[]
  const months = [...new Set(sched.map((r) => String(r.month)))].sort()
  const liab = months.map((m) => {
    const rows = sched.filter((r) => r.month === m)
    return { month: m, liability: rows.reduce((a, r) => a + Number(r.closing_liability), 0), rou: rows.reduce((a, r) => a + Number(r.closing_rou_asset), 0) }
  })
  const dist = (je.data.distribution ?? []) as Row[]
  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Controller</h1><p>Fixed assets, lease accounting and journal-entry testing · {String(ls.data.month)}</p></div>
        <AskButton text="As controller, what do I need to book or review this month for fixed assets, leases and risky journal entries?">Ask the assistant</AskButton>
      </div>
      <KpiRow items={[
        { label: 'Fixed assets, net book value', value: usd(ft.net_book_value), note: `cost ${usd(ft.cost)} · accumulated ${usd(ft.accumulated_depreciation)}` },
        { label: 'Depreciation vs GL', value: ties ? 'Ties' : 'Difference', note: `${rec.reduce((a, r) => a + Number(r.months), 0)} department-months checked`, tone: ties ? 'good' : 'bad' },
        { label: 'Lease liability', value: usd(lt.closing_liability), note: `${usd(lt.current_liability)} current · ${usd(lt.non_current_liability)} non-current` },
        { label: 'Right-of-use asset', value: usd(lt.closing_rou_asset), note: `straight-line cost ${usd(lt.straight_line_cost)}/mo vs cash ${usd(lt.cash_payment)}` },
        { label: 'Straight-line accrual to date', value: usd(lt.cumulative_cost_minus_cash), note: 'cost recognised minus cash rent paid', tone: 'ok' },
        { label: 'Journal entries to review', value: String(je.data.row_count), note: `risk score 2+ of ${Number((je.data.flag_counts as Row).entries).toLocaleString()} entries`, tone: 'ok' },
      ]} />
      <div className="grid cols-2">
        <Card title="Fixed-asset register" sub="Built from the ledger's capex entries; straight line from the month after purchase">
          <DataTable title="fixed-assets" rows={(fa.data.rows ?? []) as Row[]} columns={[
            { key: 'description' }, { key: 'asset_class', label: 'Class', chip: true }, { key: 'in_service_month', label: 'In service' },
            { key: 'useful_life_months', label: 'Life (mo)' }, { key: 'cost', unit: 'usd' },
            { key: 'accumulated_depreciation', label: 'Accumulated', unit: 'usd' }, { key: 'net_book_value', label: 'Net book value', unit: 'usd' },
          ]} />
        </Card>
        <Card title="Depreciation: register vs GL" sub={ties ? 'Every month ties to the ledger' : 'Differences to investigate'}>
          <Trend rows={(fa.data.depreciation_by_month ?? []) as Row[]} x="month" series={[{ key: 'gl_depreciation', label: 'Booked in GL' }, { key: 'register_depreciation', label: 'Per register', color: '#7a8699', dashed: true }]} />
        </Card>
      </div>
      <div className="grid cols-2">
        <Card title="Leases (ASC 842): liability and right-of-use asset" sub="Operating leases; lease terms are simulated">
          <Trend rows={liab} x="month" series={[{ key: 'liability', label: 'Lease liability' }, { key: 'rou', label: 'Right-of-use asset', color: '#2f9e6b' }]} />
        </Card>
        <Card title="Leases this month" sub={String(ls.data.note)}>
          <DataTable title="leases" rows={(ls.data.rows ?? []) as Row[]} columns={[
            { key: 'description' }, { key: 'lease_month', label: 'Month #' }, { key: 'cash_payment', label: 'Cash', unit: 'usd' },
            { key: 'straight_line_cost', label: 'Straight-line cost', unit: 'usd' }, { key: 'interest', unit: 'usd' },
            { key: 'closing_liability', label: 'Liability', unit: 'usd' }, { key: 'closing_rou_asset', label: 'ROU asset', unit: 'usd' },
          ]} />
        </Card>
      </div>
      <div className="grid cols-2">
        <Card title="Journal entries by risk score" sub="How many entries raise 0, 1, 2… red flags">
          <Bars rows={dist.map((r) => ({ score: `score ${String(r.risk_score)}`, entries: Number(r.entries) }))} dim="score" measure="entries" unit="count" valueFormat={(v) => String(v)} />
        </Card>
        <Card title="Sample to review (risk score 2+)" sub={String(je.data.note)}>
          <DataTable title="je-sample" rows={(je.data.rows ?? []) as Row[]} columns={[
            { key: 'entry_id', label: 'Entry' }, { key: 'entry_date', label: 'Date' }, { key: 'entry_type', label: 'Type', chip: true },
            { key: 'memo' }, { key: 'amount', unit: 'usd' },
            { key: 'flags', label: 'Flags', render: (r) => <span style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              {(['is_manual', 'is_weekend', 'is_round', 'is_outlier', 'is_period_end'] as const).filter((k) => r[k]).map((k) => <Chip key={k} value={k.replace('is_', '').replace('_', ' ')} kind="warn" />)}
            </span> },
          ]} />
        </Card>
      </div>
    </div>
  )
}
