// Controller: fixed-asset register reconciled to the GL, ASC 842 lease accounting, audit-style journal-entry
// testing, stock-based compensation (ASC 718) and the income tax provision (ASC 740).
import { Bars, Columns, Dash, KpiRow, Trend } from '../components/Dash'
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
      <StockComp />
      <IncomeTax />
    </div>
  )
}

const pct = (v: unknown) => (v == null ? '—' : `${(Number(v) * 100).toFixed(1)}%`)
const n = (v: unknown) => Number(v ?? 0).toLocaleString()

function StockComp() {
  const sc = useTool('get_stock_comp')
  if (!sc.data) return <Card title="Stock-based compensation"><Loading state={sc} /></Card>
  const t = sc.data.totals as Row
  return (
    <>
      <KpiRow items={[
        { label: 'Stock comp this month', value: usd(t.month_expense), note: `${usd(t.ytd_expense)} year to date · not yet in the ledger`, tone: 'ok' },
        { label: 'Options granted', value: n(t.options_granted), note: `${n(t.vested)} vested · ${n(t.unvested)} unvested · ${n(t.forfeited)} forfeited` },
        { label: 'Option pool left', value: n(t.pool_remaining), note: `of ${n(t.pool_size)} in the pool (cap table)` },
        { label: 'Unrecognised cost', value: usd(t.unrecognised_cost), note: `recognised over about ${String(t.weighted_years_to_recognise)} years` },
      ]} />
      <div className="grid cols-2">
        <Card title="Stock-based compensation expense (ASC 718)" sub={String(sc.data.note)}>
          <Columns rows={(sc.data.by_month ?? []) as Row[]} x="month" y="expense" />
        </Card>
        <Card title="409A valuations and Black-Scholes fair value" sub="At-the-money grants; simplified-method expected term">
          <DataTable title="option-valuations" rows={(sc.data.valuations ?? []) as Row[]} columns={[
            { key: 'effective_date', label: 'Effective' }, { key: 'fmv_per_share', label: 'Common FMV', unit: 'usd' },
            { key: 'volatility', render: (r) => pct(r.volatility) }, { key: 'risk_free_rate', label: 'Risk-free', render: (r) => pct(r.risk_free_rate) },
            { key: 'expected_term_years', label: 'Term (yrs)' }, { key: 'fair_value_per_option', label: 'Fair value / option', unit: 'usd' },
          ]} />
        </Card>
      </div>
      <Card title="Option grants" sub={`At ${String(sc.data.month)}: four-year vesting with a one-year cliff`}>
        <DataTable title="option-grants" rows={(sc.data.rows ?? []) as Row[]} columns={[
          { key: 'employee_id', label: 'Employee' }, { key: 'department_id', label: 'Dept' }, { key: 'grant_date', label: 'Granted' },
          { key: 'shares', render: (r) => n(r.shares) }, { key: 'strike_price', label: 'Strike', unit: 'usd' },
          { key: 'grant_fair_value', label: 'Grant fair value', unit: 'usd' }, { key: 'vested_shares', label: 'Vested', render: (r) => n(r.vested_shares) },
          { key: 'status', chip: true }, { key: 'cumulative_expense', label: 'Expensed to date', unit: 'usd' }, { key: 'expense', label: 'This month', unit: 'usd' },
        ]} />
      </Card>
    </>
  )
}

function IncomeTax() {
  const tx = useTool('get_income_tax_provision')
  if (!tx.data) return <Card title="Income tax provision"><Loading state={tx} /></Card>
  const d = tx.data
  const rows = (d.rows ?? []) as Row[]
  const rec = ((d.rate_reconciliation ?? []) as Row[]).find((r) => r.year === d.year) as Row | undefined
  const def = ((d.deferred ?? []) as Row[]).find((r) => r.year === d.year) as Row | undefined
  const total = rows.reduce((a, r) => a + Number(r.total_provision), 0)
  const defLines = def ? Object.entries(def).filter(([k]) => !['year', 'loss_carryforward'].includes(k)) : []
  return (
    <>
      <KpiRow items={[
        { label: `Income tax provision ${String(tx.data.year)}`, value: usd(total), note: String(tx.data.note ?? ''), tone: 'ok' },
        { label: 'Effective tax rate', value: pct(rec?.effective_rate), note: `on pre-tax income of ${usd(rec?.pretax_income)}` },
        { label: 'US loss carryforward', value: usd(def?.loss_carryforward), note: 'no expiry; offsets up to 80% of future taxable income' },
        { label: 'Valuation allowance', value: usd(def?.valuation_allowance), note: 'full allowance on US net deferred tax assets (cumulative losses)' },
      ]} />
      <Card title="Income tax provision by entity (ASC 740)" sub="Book income, book-to-tax differences, taxable income, and current and deferred tax">
        <DataTable title="tax-provision" rows={rows} columns={[
          { key: 'entity_id', label: 'Entity' }, { key: 'pretax_income', label: 'Pre-tax income', unit: 'usd' },
          { key: 'stock_comp_addback', label: 'Stock comp (not deductible yet)', unit: 'usd' },
          { key: 'commissions_capitalised', label: 'Commissions (deducted when paid)', unit: 'usd' },
          { key: 'rent_straight_line_vs_cash', label: 'Rent (cash vs straight line)', unit: 'usd' },
          { key: 'taxable_income', label: 'Taxable income', unit: 'usd' }, { key: 'statutory_rate', label: 'Rate', render: (r) => pct(r.statutory_rate) },
          { key: 'current_tax', label: 'Current tax', unit: 'usd' }, { key: 'deferred_tax', label: 'Deferred tax', unit: 'usd' },
          { key: 'total_provision', label: 'Provision', unit: 'usd' },
        ]} />
      </Card>
      <div className="grid cols-2">
        <Card title="Rate reconciliation" sub="From the 21% US federal rate to the effective rate. Tax on a pre-tax loss gives a negative rate: UK and India pay tax while the US losses get no benefit.">
          <div className="rec-statement">
            {((rec?.items ?? []) as Row[]).map((i) => (
              <div key={String(i.item)} className="rec-line"><span>{String(i.item)}</span><span>{usd(i.amount)} · {pct(i.rate)}</span></div>
            ))}
            <div className="rec-line strong"><span>Income tax provision</span><span>{usd(rec?.total_provision)} · {pct(rec?.effective_rate)}</span></div>
          </div>
        </Card>
        <Card title="Deferred taxes (US)" sub="Temporary differences at the combined federal and state rate">
          <div className="rec-statement">
            {defLines.map(([k, v]) => (
              <div key={k} className={`rec-line${['net_deferred_tax'].includes(k) ? ' strong' : ''}`}><span>{k.includes('_') ? k.replaceAll('_', ' ').replace(/^./, (c) => c.toUpperCase()) : k}</span><span>{usd(v)}</span></div>
            ))}
          </div>
        </Card>
      </div>
    </>
  )
}
