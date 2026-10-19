// Corporate finance (company numbers) and the textbook calculators. Both read the same corpfin formulas the
// assistant uses (get_corporate_finance, evaluate_project, finance_calculator).
import { useMemo, useState } from 'react'
import { KpiRow } from '../components/Dash'
import { api, fmt, type Row, type ToolResult } from '../api'
import { AskButton, Card, DataTable, Loading, Source, useTool } from '../components/common'

const usd = (v: unknown) => fmt('amount', Number(v ?? 0), 'usd')
const pct = (v: unknown) => (v == null ? '—' : `${(Number(v) * 100).toFixed(1)}%`)
const x = (v: unknown, d = 2) => (v == null ? '—' : Number(v).toFixed(d))
const words = (k: string) => k.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())

function Head({ title, sub, ask }: { title: string; sub: string; ask: string }) {
  return (
    <div className="page-head">
      <div><h1>{title}</h1><p>{sub}</p></div>
      <AskButton text={ask}>Ask the assistant</AskButton>
    </div>
  )
}

function Pairs({ obj, format }: { obj: Row; format?: (k: string, v: unknown) => string }) {
  const rows = Object.entries(obj).filter(([, v]) => typeof v !== 'object' || v === null).map(([k, v]) => ({ item: words(k), value: format ? format(k, v) : String(v ?? '—') }))
  return (
    <table className="pairs">
      <tbody>{rows.map((r) => <tr key={r.item}><td>{r.item}</td><td className="num">{r.value}</td></tr>)}</tbody>
    </table>
  )
}

const RATIO_FMT = (k: string, v: unknown) => (v == null ? '—' : /margin|return|ratio_debt|debt_ratio|on_assets|on_equity/.test(k) ? pct(v) : k.startsWith('days') ? `${x(v, 1)} days` : `${x(v)}x`)

export function CorporateFinance() {
  const d = useTool('get_corporate_finance')
  if (!d.data) return <div className="page"><Loading state={d} /></div>
  const cf = d.data.cash_flow as Row, r = d.data.ratios as Record<string, Row>, tax = d.data.tax_summary as Row
  const pf = d.data.proforma as Row, g = d.data.growth as Row, cc = d.data.cost_of_capital as Row, be = d.data.break_even as Row
  return (
    <div className="page">
      <Head title="Corporate finance" sub={`Cash flow identity, ratios and DuPont, taxes, pro forma and growth, break-even and cost of capital · trailing 12 months ${String(d.data.period)}`}
        ask="Walk me through our corporate finance position: cash flow from assets, ROE by DuPont, our tax exposure by entity, external financing needed, the break-evens and our WACC." />
      <KpiRow items={[
        { label: 'Cash flow from assets', value: usd(cf.cash_flow_from_assets), note: 'OCF − net capital spending − ΔNWC', tone: Number(cf.cash_flow_from_assets) < 0 ? 'bad' : 'good' },
        { label: 'ROE (DuPont)', value: pct((r.dupont as Row).return_on_equity), note: `${pct((r.dupont as Row).profit_margin)} × ${x((r.dupont as Row).total_asset_turnover)} × ${x((r.dupont as Row).equity_multiplier)}` },
        { label: 'Tax owed (provision)', value: usd(tax.group_tax), note: 'subsidiaries on cost-plus margins' },
        { label: 'EFN at base growth', value: usd(pf.efn_cash_held_flat), note: `cash held flat · ${pct(pf.growth_used)} revenue growth` },
        { label: 'Cash break-even', value: usd(be.cash), note: `per month · revenue ${usd(be.revenue)}`, tone: Number(be.revenue) >= Number(be.cash) ? 'good' : 'bad' },
        { label: 'WACC', value: pct(cc.wacc), note: `CAPM: ${pct(cc.risk_free_rate)} + ${x(cc.levered_beta)} × ${pct(cc.market_risk_premium)} + ${pct(cc.private_company_premium)} private` },
      ]} />
      <div className="grid cols-2">
        <Card title="Cash flow identity" sub="Cash flow from assets = cash flow to creditors + cash flow to stockholders">
          <Pairs obj={cf} format={(k, v) => (k === 'note' ? String(v) : usd(v))} />
        </Card>
        <Card title="DuPont identity" sub="ROE = profit margin × total asset turnover × equity multiplier">
          <Pairs obj={r.dupont} format={RATIO_FMT} />
        </Card>
      </div>
      <Card title="Financial ratios" sub="Balance sheet at the latest close, income on the trailing 12 months · interest ratios are blank: no debt">
        <div className="grid cols-4">
          {(['liquidity', 'leverage', 'turnover', 'profitability'] as const).map((grp) => (
            <div key={grp}><h3 style={{ fontSize: 13, margin: '0 0 6px' }}>{words(grp)}</h3><Pairs obj={r[grp]} format={RATIO_FMT} /></div>
          ))}
        </div>
      </Card>
      <Card title="Corporate income tax by legal entity" sub={String(tax.note)}>
        <DataTable rows={d.data.taxes as Row[]} columns={[{ key: 'entity_id', label: 'Entity' }, { key: 'currency' }, { key: 'pre_tax_income_local', label: 'Pre-tax income (local)', render: (q) => Number(q.pre_tax_income_local).toLocaleString(undefined, { maximumFractionDigits: 0 }) },
          { key: 'pre_tax_income_usd', label: 'Pre-tax (USD)', unit: 'usd' }, { key: 'tax_usd', label: 'Tax (USD)', unit: 'usd' }, { key: 'average_rate', label: 'Average rate', unit: 'ratio' }, { key: 'marginal_rate', label: 'Marginal rate', unit: 'ratio' },
          { key: 'nol_carryforward', label: 'Loss carryforward', unit: 'usd' }, { key: 'deferred_tax_asset_gross', label: 'Deferred tax asset', unit: 'usd' }, { key: 'valuation_allowance', unit: 'usd' }]} />
      </Card>
      <div className="grid cols-2">
        <Card title="Pro forma balance sheet and EFN" sub={String(pf.note)}>
          <DataTable rows={[...Object.entries(pf.projected_assets as Row).map(([k, v]) => ({ side: 'Assets', line: words(k), projected: v })),
            ...Object.entries(pf.projected_liabilities as Row).map(([k, v]) => ({ side: 'Liabilities', line: words(k), projected: v })),
            { side: 'Equity', line: 'Equity (with retained earnings)', projected: pf.projected_equity },
            { side: 'Result', line: 'External financing needed', projected: pf.efn }, { side: 'Result', line: 'EFN with cash held flat', projected: pf.efn_cash_held_flat }]}
            columns={[{ key: 'side', chip: true }, { key: 'line' }, { key: 'projected', unit: 'usd' }]} />
        </Card>
        <Card title="Growth rates" sub="How fast the company can grow on its own: negative while it loses money (retention ratio 1, no dividends)">
          <Pairs obj={g} format={(k, v) => (k === 'retention_ratio' ? x(v) : pct(v))} />
        </Card>
      </div>
      <div className="grid cols-2">
        <Card title="Break-even (monthly revenue)" sub={String(be.note)}>
          <Pairs obj={be} format={(k, v) => (k === 'note' || k === 'month' ? String(v) : k === 'cm_ratio' ? pct(v) : k === 'degree_of_operating_leverage' ? x(v) : usd(v))} />
        </Card>
        <Card title="Cost of capital" sub={String(cc.note)}>
          <Pairs obj={cc} format={(k, v) => (k === 'note' ? String(v) : /beta|debt_to_equity/.test(k) ? x(v) : pct(v))} />
        </Card>
      </div>
      <ProjectEvaluator wacc={Number(cc.wacc)} taxRate={Number(cc.tax_rate)} />
      <Source data={d.data} />
    </div>
  )
}

function Num({ label, value, onChange, step }: { label: string; value: number; onChange: (n: number) => void; step?: number }) {
  return <label className="explore-field">{label}<input type="number" value={value} step={step} onChange={(e) => onChange(Number(e.target.value))} /></label>
}

function ProjectEvaluator({ wacc, taxRate }: { wacc: number; taxRate: number }) {
  const [p, setP] = useState({ investment: 500000, life_years: 5, annual_revenue: 300000, annual_costs: 120000, salvage: 50000, nwc: 20000, tax_rate: Number(taxRate.toFixed(4)), discount_rate: Number(wacc.toFixed(4)) })
  const [dep, setDep] = useState('straight_line')
  const args = useMemo(() => ({ ...p, depreciation: dep }), [p, dep])
  const r = useTool('evaluate_project', args)
  const set = (k: keyof typeof p) => (n: number) => setP({ ...p, [k]: n })
  return (
    <Card title="Project evaluator" sub="Capital budgeting with the depreciation tax shield, after-tax salvage and working capital · discounts at the company WACC by default">
      <div className="explore-grid">
        <Num label="Investment $" value={p.investment} onChange={set('investment')} step={10000} />
        <Num label="Life (years)" value={p.life_years} onChange={set('life_years')} />
        <Num label="Annual revenue $" value={p.annual_revenue} onChange={set('annual_revenue')} step={10000} />
        <Num label="Annual cash costs $" value={p.annual_costs} onChange={set('annual_costs')} step={10000} />
        <Num label="Salvage value $" value={p.salvage} onChange={set('salvage')} step={5000} />
        <Num label="Working capital $" value={p.nwc} onChange={set('nwc')} step={5000} />
        <Num label="Tax rate" value={p.tax_rate} onChange={set('tax_rate')} step={0.01} />
        <Num label="Discount rate" value={p.discount_rate} onChange={set('discount_rate')} step={0.005} />
        <label className="explore-field">Depreciation<select value={dep} onChange={(e) => setDep(e.target.value)}><option value="straight_line">Straight line</option><option value="double_declining">Double declining</option></select></label>
      </div>
      {r.data ? (
        <>
          <KpiRow items={[
            { label: 'NPV', value: usd(r.data.npv), tone: Number(r.data.npv) >= 0 ? 'good' : 'bad' },
            { label: 'IRR', value: pct(r.data.irr), note: `vs ${pct(r.data.discount_rate)} hurdle` },
            { label: 'Payback', value: `${x(r.data.payback_years, 2)} yrs` },
            { label: 'Discounted payback', value: r.data.discounted_payback_years == null ? 'never' : `${x(r.data.discounted_payback_years, 2)} yrs` },
            { label: 'Profitability index', value: x(r.data.profitability_index) },
            { label: 'Depreciation tax shield', value: usd(r.data.total_tax_shield), note: 'over the life' },
          ]} />
          <DataTable rows={r.data.rows} columns={[{ key: 'year' }, { key: 'revenue', unit: 'usd' }, { key: 'costs', unit: 'usd' }, { key: 'depreciation', unit: 'usd' }, { key: 'ebit', label: 'EBIT', unit: 'usd' },
            { key: 'taxes', unit: 'usd' }, { key: 'ocf', label: 'OCF', unit: 'usd' }, { key: 'depreciation_tax_shield', label: 'Tax shield', unit: 'usd' }, { key: 'after_tax_salvage_and_nwc', label: 'Salvage + NWC', unit: 'usd' }, { key: 'cash_flow', unit: 'usd' }]} />
        </>
      ) : <Loading state={r} />}
    </Card>
  )
}

// ---- Calculators: textbook formulas with example inputs --------------------------------------------------------

const EXAMPLES: Record<string, { title: string; module: string; inputs: Record<string, unknown> }> = {
  future_value: { title: 'Future value of a lump sum', module: 'Time value of money', inputs: { rate: 0.08, periods: 10, pv: 1000 } },
  present_value: { title: 'Present value of a lump sum', module: 'Time value of money', inputs: { rate: 0.08, periods: 10, fv: 2158.92 } },
  annuity: { title: 'Annuity (ordinary or due, optionally growing)', module: 'Time value of money', inputs: { rate: 0.06, periods: 20, payment: 5000, due: false, growth: 0 } },
  perpetuity: { title: 'Perpetuity (optionally growing)', module: 'Time value of money', inputs: { rate: 0.08, payment: 100, growth: 0.02 } },
  loan: { title: 'Loan amortization schedule', module: 'Time value of money', inputs: { principal: 100000, annual_rate: 0.08, years: 5, periods_per_year: 12, kind: 'amortized' } },
  bond_price: { title: 'Bond price', module: 'Bond valuation', inputs: { face: 1000, coupon_rate: 0.06, ytm: 0.08, years: 10, freq: 2 } },
  bond_ytm: { title: 'Yield to maturity', module: 'Bond valuation', inputs: { price: 950, face: 1000, coupon_rate: 0.06, years: 10, freq: 2 } },
  interest_rate_risk: { title: 'Interest-rate risk (+/- 1 point)', module: 'Bond valuation', inputs: { face: 1000, coupon_rate: 0.04, ytm: 0.05, years: 30, shock: 0.01, freq: 2 } },
  ddm: { title: 'Dividend discount model', module: 'Stock valuation', inputs: { dividend_next: 2, required_return: 0.12, growth: 0.05 } },
  voting: { title: 'Straight vs cumulative voting', module: 'Stock valuation', inputs: { shares_owned: 300, shares_total: 1000, seats: 4, cumulative: true } },
  holding_return: { title: 'Dividend yield and capital gains yield', module: 'Risk and return', inputs: { price_begin: 40, price_end: 44, dividend: 1.2 } },
  return_stats: { title: 'Arithmetic vs geometric average, variance, standard deviation', module: 'Risk and return', inputs: { returns: [0.1, -0.05, 0.2, 0.08] } },
  portfolio: { title: 'Two-asset portfolio', module: 'Portfolio theory', inputs: { w1: 0.6, r1: 0.12, s1: 0.2, r2: 0.06, s2: 0.1, corr: 0.3 } },
  sml: { title: 'CAPM and the security market line', module: 'Portfolio theory', inputs: { rf: 0.043, mrp: 0.055, beta: 1.35, expected_return: 0.14 } },
  wacc: { title: 'WACC', module: 'Cost of capital', inputs: { equity_value: 800, debt_value: 200, cost_of_equity: 0.14, cost_of_debt: 0.07, tax_rate: 0.21, preferred_value: 0, cost_of_preferred: 0 } },
  flotation: { title: 'Flotation costs', module: 'Cost of capital', inputs: { investment: 1000000, weights_flotation: [[0.7, 0.08], [0.3, 0.03]] } },
  rights_offering: { title: 'Rights offering', module: 'Cost of capital', inputs: { price_now: 25, subscription_price: 20, shares_outstanding: 1000000, funds_needed: 5000000 } },
  mm: { title: 'M&M propositions I and II (set tax_rate 0 for no taxes)', module: 'Capital structure', inputs: { unlevered_value_or_ebit: 0, ebit: 150000, debt: 400000, cost_of_debt: 0.08, unlevered_cost_of_equity: 0.12, tax_rate: 0.21 } },
  homemade_leverage: { title: 'Homemade leverage', module: 'Capital structure', inputs: { shares: 100, price: 20, borrow: 2000, rate: 0.1, eps_unlevered: 2.5 } },
  payout: { title: 'Cash dividend vs share repurchase', module: 'Payout policy', inputs: { net_income: 49000, shares: 100000, price: 10, cash_distributed: 300000 } },
  split: { title: 'Stock split or stock dividend', module: 'Payout policy', inputs: { shares: 1000000, price: 60, ratio: 3 } },
  bid_price: { title: 'Bid price (NPV = 0)', module: 'Project analysis', inputs: { investment: 600000, life: 4, units: 50000, variable_cost: 8, fixed_costs: 250000, tax_rate: 0.21, rate: 0.12, salvage: 50000, nwc: 40000 } },
  crossover: { title: 'Crossover rate between two projects', module: 'Capital budgeting', inputs: { flows_a: [-500, 250, 250, 250], flows_b: [-400, 150, 200, 250] } },
  tax: { title: 'Marginal vs average tax (bands)', module: 'Taxes', inputs: { income: 335000, bands: [[50000, 0.15], [75000, 0.25], [100000, 0.34], [335000, 0.39], [null, 0.34]] } },
  uk_tax: { title: 'UK corporation tax with marginal relief', module: 'Taxes', inputs: { profit: 150000 } },
}

export function Calculators() {
  const [kind, setKind] = useState('bond_price')
  const [text, setText] = useState<Record<string, string>>({})
  const [res, setRes] = useState<ToolResult | null>(null)
  const [err, setErr] = useState<string>()
  const ex = EXAMPLES[kind]
  const val = (k: string) => text[`${kind}.${k}`] ?? JSON.stringify(ex.inputs[k])
  const run = () => {
    try {
      const inputs = Object.fromEntries(Object.keys(ex.inputs).map((k) => [k, JSON.parse(val(k))]))
      setErr(undefined)
      api.data('finance_calculator', { kind, inputs }).then(setRes).catch((e) => setErr(String(e)))
    } catch { setErr('Inputs must be numbers, true/false, null or [lists].') }
  }
  const groups = [...new Set(Object.values(EXAMPLES).map((e) => e.module))]
  const result = (res?.result ?? {}) as Row
  return (
    <div className="page">
      <Head title="Calculators" sub="Textbook corporate finance: time value of money, bonds, stocks, risk and return, CAPM, cost of capital, M&M, payout, project analysis and taxes"
        ask="Explain how this calculation works and what the result means." />
      <div className="grid cols-2" style={{ alignItems: 'start' }}>
        <Card title="Pick a calculator">
          {groups.map((g) => (
            <div key={g} style={{ marginBottom: 8 }}>
              <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>{g}</div>
              <div className="metric-picker">
                {Object.entries(EXAMPLES).filter(([, e]) => e.module === g).map(([k, e]) => (
                  <button key={k} className={`filter-chip ${kind === k ? 'on' : ''}`} onClick={() => { setKind(k); setRes(null) }}>{e.title}</button>
                ))}
              </div>
            </div>
          ))}
        </Card>
        <Card title={ex.title} sub="Rates as decimals (0.08 = 8%) · lists in [brackets]">
          <div className="explore-grid">
            {Object.keys(ex.inputs).map((k) => (
              <label key={k} className="explore-field">{words(k)}<input value={val(k)} onChange={(e) => setText({ ...text, [`${kind}.${k}`]: e.target.value })} /></label>
            ))}
          </div>
          <div style={{ marginTop: 10, display: 'flex', gap: 8 }}><button className="btn" onClick={run}>Calculate</button>{err && <span className="error">{err}</span>}</div>
          {res && (res.error ? <div className="error">{String(res.error)}</div> : (
            <div style={{ marginTop: 12 }}>
              {Object.entries(result).map(([k, v]) => (
                <div key={k} className="tree-row" style={{ gridTemplateColumns: '1fr 1fr' }}>
                  <span>{words(k)}</span>
                  <span><b>{typeof v === 'object' && v !== null ? Object.entries(v as Row).map(([a, b]) => `${words(a)}: ${String(b)}`).join(' · ') : String(v)}</b></span>
                </div>
              ))}
              {res.rows?.length ? <DataTable rows={res.rows} pageSize={12} columns={Object.keys(res.rows[0]).map((k) => ({ key: k }))} /> : null}
            </div>
          ))}
        </Card>
      </div>
    </div>
  )
}
