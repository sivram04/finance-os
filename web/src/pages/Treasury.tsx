// Treasury: debt facilities (undrawn venture loan and revolver), what a draw would cost and do to runway, the
// covenant tests, and FX: subsidiary exposure, forward hedges, hedge ratio and mark-to-market.
import { Columns, Dash, KpiRow, Trend } from '../components/Dash'
import { fmt, type Row } from '../api'
import { AskButton, Card, Chip, DataTable, Loading, useTool } from '../components/common'

const usd = (v: unknown) => fmt('amount', Number(v ?? 0), 'usd')
const pct = (v: unknown) => (v == null ? '—' : `${(Number(v) * 100).toFixed(0)}%`)

export function Treasury() {
  return <Dash><Body /></Dash>
}

function Body() {
  const debt = useTool('get_debt_facilities')
  const fx = useTool('get_fx_hedging')
  if (!debt.data || !fx.data) return <div className="page"><Loading state={[debt, fx].find((s) => s.error) ?? debt} /></div>
  const s = debt.data.summary as Row
  const sched = ((debt.data.schedule ?? []) as Row[]).filter((r) => r.facility_id === 'VD-01')
  const cov = (debt.data.covenants ?? []) as Row[]
  const expo = (fx.data.rows ?? []) as Row[]
  const trend = (fx.data.trend ?? []) as Row[]
  const months = [...new Set(trend.map((r) => String(r.month)))]
  const ratio = months.map((m) => ({ month: m, ...Object.fromEntries(trend.filter((r) => r.month === m).map((r) => [String(r.entity_id), Number(r.hedge_ratio)])) }))
  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Treasury</h1><p>Debt capacity, covenants and FX risk · {String(fx.data.month)}</p></div>
        <AskButton text="Should we draw the venture debt facility? Show the cost, the effect on runway and the covenants, and how well our FX exposure is hedged.">Ask the assistant</AskButton>
      </div>
      <KpiRow items={[
        { label: 'Debt available', value: usd(s.total_commitment), note: `${usd(s.drawn)} drawn · fees ${usd(s.commitment_fees_per_month)}/mo` },
        { label: 'Interest if term loan drawn', value: `${usd(s.pro_forma_interest_per_month)}/mo`, note: `${usd(s.pro_forma_interest_first_12m)} in the first 12 months` },
        { label: 'Runway now → if drawn', value: `${s.runway_months_now ?? '∞'} → ${s.runway_months_if_drawn ?? '∞'} mo`, note: `net burn ${usd(s.net_burn_t3m)}/mo (3-month average)`,
          tone: Number(s.runway_months_if_drawn) < Number(s.runway_months_now) ? 'ok' : 'good' },
        ...expo.map((e) => ({ label: `${String(e.currency)} hedged (next quarter)`, value: pct(e.hedge_ratio), note: `${usd(e.next_quarter_exposure_usd)} exposure · policy 50–80%`,
          tone: (Number(e.hedge_ratio) >= 0.5 && Number(e.hedge_ratio) <= 0.8 ? 'good' : 'ok') as 'good' | 'ok' })),
        { label: 'Hedge mark-to-market', value: usd(fx.data.total_mtm_usd), tone: Number(fx.data.total_mtm_usd) >= 0 ? 'good' : 'bad' },
      ]} />
      <div className="grid cols-2">
        <Card title="Venture term loan if drawn in full" sub="12 months interest-only, then 24 months straight-line principal; illustrative terms">
          <Columns rows={sched.map((r) => ({ month: r.month, debt_service: r.pro_forma_debt_service }))} x="month" y="debt_service" />
          <p className="sub" style={{ marginTop: 6 }}>{String(debt.data.note)}</p>
        </Card>
        <Card title="Covenants and policy tests" sub="Last closed month">
          <DataTable title="covenants" rows={cov} columns={[
            { key: 'rule_id', label: 'Test' }, { key: 'description' },
            { key: 'value', render: (r) => (r.rule_id === 'MIN-CASH' ? usd(r.value) : Number(r.value).toFixed(2)) },
            { key: 'threshold', render: (r) => (r.rule_id === 'MIN-CASH' ? usd(r.threshold) : Number(r.threshold).toFixed(2)) },
            { key: 'status', render: (r) => <Chip value={String(r.status)} kind={r.status === 'pass' ? 'good' : 'bad'} /> },
          ]} />
        </Card>
      </div>
      <div className="grid cols-2">
        <Card title="Hedge ratio by month" sub="Forwards maturing in the next quarter ÷ that quarter's expected subsidiary costs">
          <Trend rows={ratio} x="month" unit="ratio" series={Object.keys(ratio[ratio.length - 1] ?? {}).filter((k) => k !== 'month').map((k) => ({ key: k, label: k }))}
            refs={[{ y: 0.5, label: '50%' }, { y: 0.8, label: '80%' }]} />
        </Card>
        <Card title="Forward contracts" sub="Marked to market at the last close; realized at maturity · simulated trades">
          <DataTable title="fx-hedges" rows={(fx.data.hedges ?? []) as Row[]} columns={[
            { key: 'hedge_id', label: 'Forward' }, { key: 'currency', chip: true }, { key: 'maturity_month', label: 'Matures' },
            { key: 'notional_fc', label: 'Notional', render: (r) => Number(r.notional_fc).toLocaleString() },
            { key: 'forward_rate', label: 'Forward' }, { key: 'spot_rate', label: 'Spot' }, { key: 'mtm_usd', label: 'MTM', unit: 'usd' },
            { key: 'status', chip: true },
          ]} />
        </Card>
      </div>
      <Card title="Debt facilities" sub="Terms are illustrative; both facilities are undrawn">
        <DataTable title="debt-facilities" rows={(debt.data.rows ?? []) as Row[]} columns={[
          { key: 'facility_id', label: 'Facility' }, { key: 'lender' }, { key: 'facility_type', label: 'Type', chip: true },
          { key: 'commitment', unit: 'usd' }, { key: 'drawn', unit: 'usd' }, { key: 'annual_rate', label: 'Rate', unit: 'ratio' },
          { key: 'undrawn_fee', label: 'Undrawn fee', unit: 'ratio' }, { key: 'expires', label: 'Draw by' },
        ]} />
      </Card>
    </div>
  )
}
