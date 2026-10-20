// Machine-learning predictions: churn probability, usage revenue forecast with a range, payment timing and cost
// anomalies. Each card shows the model's backtest against the method it would replace, so it is clear when ML wins.
import { useState } from 'react'
import { Columns, Dash, KpiRow, Trend } from '../components/Dash'
import { fmt, type Row } from '../api'
import { AskButton, Card, Chip, DataTable, Loading, useTool, useWorkspace } from '../components/common'

const usd = (v: unknown) => fmt('amount', Number(v ?? 0), 'usd')
const pct = (v: unknown, d = 0) => (v == null ? '—' : `${(Number(v) * 100).toFixed(d)}%`)
type Card_ = Record<string, unknown>

function Verdict({ text, good }: { text: string; good: boolean | null }) {
  return <div className={`ml-verdict ${good == null ? '' : good ? 'good' : 'warn'}`}>{text}</div>
}

export function Predictions() {
  return <Dash><Body /></Dash>
}

function Compare({ card, what, rule }: { card: Card_; what: string; rule: string }) {
  const cmp = card.same_budget_comparison as Record<string, Record<string, number>>
  const ev = card.evaluation as Record<string, Record<string, number>>
  const best = String(card.model).replace(/ /g, '_')
  return <Verdict good={cmp.model.caught > cmp.rule.caught ? true : cmp.model.caught < cmp.rule.caught ? false : null}
    text={`Held-out weeks: ROC AUC ${ev[best]?.roc_auc} vs ${ev.current_rule?.roc_auc} for ${rule}. Flagging the same ${cmp.rule.flagged} customer-weeks, the model finds ${cmp.model.caught} of ${card.holdout_positives} ${what} and ${rule} ${cmp.rule.caught}. ${String(card.caveat)}`} />
}

function Body() {
  const models = useTool('get_ml_models')
  const exp = useTool('get_expansion_predictions')
  const revf = useTool('get_revenue_forecast_ml')
  const spend = useTool('get_spend_forecast_ml')
  const deals = useTool('get_deal_predictions')
  const churn = useTool('get_churn_predictions')
  const usage = useTool('get_usage_forecast_ml')
  const pay = useTool('get_payment_predictions')
  const anom = useTool('get_cost_anomalies_ml')
  const { refresh } = useWorkspace()
  const [busy, setBusy] = useState(false)
  const all = [churn, usage, pay, anom, models, exp, revf, spend, deals]
  if (!churn.data || !usage.data || !pay.data || !anom.data || !models.data || !exp.data || !revf.data || !spend.data || !deals.data) {
    return <div className="page"><Loading state={all.find((s) => s.error) ?? churn} /></div>
  }
  const xc = exp.data.model_card as Card_
  const rc = revf.data.model_card as Card_
  const re = rc.evaluation as Record<string, unknown>
  const reW = (re.mape_where_driver_exists ?? {}) as Record<string, number>
  const reA = (re.mape_all_origins ?? {}) as Record<string, number>
  const sc = spend.data.model_card as Card_
  const se = (sc.evaluation as Record<string, Record<string, number>>).mape
  const dc = deals.data.model_card as Card_
  const pipe = deals.data.pipeline as Record<string, number>
  const spendTotal = ((spend.data.rows ?? []) as Row[]).filter((r) => r.series === 'total')
  const expRows = (exp.data.rows ?? []) as Row[]
  const revRows = (revf.data.rows ?? []) as Row[]
  const dealRows = (deals.data.rows ?? []) as Row[]
  const cc = churn.data.model_card as Card_
  const uc = usage.data.model_card as Card_
  const pc = pay.data.model_card as Card_
  const ac = anom.data.model_card as Card_
  const ub = (uc.backtest ?? {}) as Record<string, number>
  const pe = pc.evaluation as Record<string, Record<string, number>>
  const ae = ac.evaluation as Record<string, unknown>
  const planted = (ae.planted_anomalies ?? []) as Row[]
  const churnRows = (churn.data.rows ?? []) as Row[]
  const fc = (usage.data.rows ?? []) as Row[]
  const hist = (usage.data.history ?? []) as Row[]
  const chart = [...hist.map((h) => ({ month: h.month, actual: h.actual })),
    ...fc.map((r) => ({ month: r.month, forecast: r.forecast, low_80: r.low_80, high_80: r.high_80, driver: r.driver_forecast }))]
  const weeks = (pay.data.expected_collections_by_week ?? []) as Row[]
  const retrain = async () => {
    setBusy(true)
    try { await fetch('/api/ml/retrain', { method: 'POST' }); refresh() } finally { setBusy(false) }
  }
  const trained = String((models.data.rows as Row[])[0]?.trained_at ?? '').replace('T', ' ').slice(0, 16)

  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Predictions</h1><p>Machine-learning models next to the methods they would replace, each backtested on months it did not see · trained {trained} UTC</p></div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn" onClick={retrain} disabled={busy}>{busy ? 'Retraining…' : 'Retrain now'}</button>
          <AskButton text="Which customers are most likely to churn, when will our big invoices be paid, and are there unusual costs? Use the ML predictions and say how reliable each model is.">Ask the assistant</AskButton>
        </div>
      </div>
      <KpiRow items={[
        { label: 'Expected ARR lost (3 mo)', value: usd(churn.data.expected_arr_lost_3m), note: 'sum of churn probability × ARR', tone: 'bad' },
        { label: 'Customers above 50%', value: String(churnRows.filter((r) => Number(r.churn_probability_3m) >= 0.5).length), note: `of ${churnRows.length} active` },
        { label: 'Usage revenue next month', value: usd(fc[0]?.forecast), note: `80% range ${usd(fc[0]?.low_80)} – ${usd(fc[0]?.high_80)}` },
        { label: 'Collections next 4 weeks', value: usd(weeks.slice(0, 4).reduce((a, w) => a + Number(w.amount), 0)), note: 'undisputed open invoices, model dates' },
        { label: 'Likely to expand', value: String(expRows.filter((r) => Number(r.expansion_probability_3m) >= 0.5).length), note: 'expansion probability of 50%+' },
        { label: 'GPU + cloud next month', value: usd(spendTotal[0]?.forecast), note: `growth method ${usd(spendTotal[0]?.growth_method)}` },
        { label: 'Cost anomalies (6 mo)', value: String((anom.data.rows as Row[]).length), note: `${(anom.data.daily as Row[]).length} daily cloud flags (30 days)` },
      ]} />

      <Card title="Churn probability, next 3 months" sub={`${cc.model} · ${Number(cc.features)} features from usage, the API request log, revenue and invoices · holdout from ${cc.holdout_from}`}
        right={<AskButton text="Which customers are most likely to churn in the next 3 months and why?" />}>
        <Compare card={cc} what="churners" rule="the health rules" />
        <DataTable title="churn-predictions" rows={churnRows} columns={[
          { key: 'customer_id', label: 'Customer' }, { key: 'segment', chip: true },
          { key: 'churn_probability_3m', label: 'Churn probability', unit: 'ratio' },
          { key: 'arr', label: 'ARR', unit: 'usd' }, { key: 'arr_at_risk', label: 'ARR × probability', unit: 'usd' },
          { key: 'rule_level', label: 'Health rules', render: (r) => <Chip value={String(r.rule_level)} kind={r.rule_level === 'at_risk' ? 'bad' : r.rule_level === 'watch' ? 'warn' : 'good'} /> },
          { key: 'signals', label: 'Signals', render: (r) => ((r.signals as string[]) ?? []).join('; ') || '—' },
        ]} />
        <div className="sub" style={{ marginTop: 8 }}>What drives the model (permutation importance on the holdout): {((cc.feature_importance ?? []) as Row[]).slice(0, 4).map((f) => String(f.feature)).join(', ')}</div>
      </Card>

      <div className="grid cols-2">
        <Card title="Usage revenue forecast" sub={`${uc.model} · 80% range · dashed: driver forecast`}>
          <Trend rows={chart} x="month" series={[{ key: 'actual', label: 'Actual' }, { key: 'forecast', label: 'ML forecast', color: '#8a63d2' },
            { key: 'low_80', label: 'Low (80%)', color: '#b8a6e6', dashed: true }, { key: 'high_80', label: 'High (80%)', color: '#b8a6e6', dashed: true },
            { key: 'driver', label: 'Driver forecast', color: '#7a8699', dashed: true }]} />
          <Verdict good={ub.ets_mape != null ? ub.ets_mape < ub.driver_mape : null}
            text={ub.ets_mape != null ? `Backtest over ${ub.forecasts_compared} forecasts: ML error ${pct(ub.ets_mape, 1)} vs driver forecast ${pct(ub.driver_mape, 1)}; actuals inside the 80% range ${pct(ub.range_coverage)} of the time. ${String(uc.verdict ?? '')}.` : 'No driver forecast versions to compare with yet.'} />
        </Card>
        <Card title="Expected collections by week" sub={`${pc.model} · undisputed open invoices`}>
          <Columns rows={weeks} x="week_of" y="amount" />
          <Verdict good={pe.mae_days.model_p50 < pe.mae_days.rule_due_plus_avg_late}
            text={`Holdout error ${pe.mae_days.model_p50} days vs ${pe.mae_days.rule_due_plus_avg_late} for due date + average lateness (${pe.mae_days_invoices_10k_plus.model_p50} vs ${pe.mae_days_invoices_10k_plus.rule_due_plus_avg_late} days on invoices of $10K+). P10–P90 range held the actual ${pct(pe.range_coverage_p10_p90)} of the time.`} />
        </Card>
      </div>


      <Card title="Expansion propensity, next 3 months" sub={`${xc.model} · same weekly snapshots and features as churn`}
        right={<AskButton text="Which customers are most likely to expand in the next 3 months, and why?" />}>
        <Compare card={xc} what="expansions" rule="the usage-trend rule" />
        <DataTable title="expansion-predictions" rows={expRows} columns={[
          { key: 'customer_id', label: 'Customer' }, { key: 'segment', chip: true },
          { key: 'expansion_probability_3m', label: 'Expansion probability', unit: 'ratio' }, { key: 'arr', label: 'ARR', unit: 'usd' },
          { key: 'usage_trend', label: 'Usage trend', unit: 'ratio' }, { key: 'rule_says_expanding', label: 'Rule flags it', flag: 'good' },
          { key: 'signals', label: 'Signals', render: (r) => ((r.signals as string[]) ?? []).join('; ') || '—' },
        ]} />
      </Card>

      <div className="grid cols-2">
        <Card title="Bottom-up revenue forecast" sub={`${rc.model} · ${Number(re.customer_origin_rows).toLocaleString()} customer-origins`}>
          <Trend rows={revRows.map((r) => ({ month: r.month, forecast: r.forecast, low_80: r.low_80, high_80: r.high_80, driver: r.driver_forecast }))}
            x="month" series={[{ key: 'forecast', label: 'ML bottom-up', color: '#8a63d2' }, { key: 'low_80', label: 'Low (80%)', color: '#b8a6e6', dashed: true },
              { key: 'high_80', label: 'High (80%)', color: '#b8a6e6', dashed: true }, { key: 'driver', label: 'Driver forecast', color: '#7a8699', dashed: true }]} />
          <Verdict good={reW.ml_bottom_up != null && reW.driver != null ? reW.ml_bottom_up < reW.driver : null}
            text={`Walk-forward backtest: ML ${pct(reA.ml_bottom_up, 1)} vs ETS ${pct(reA.ets_total, 1)} over ${String(re.backtest_forecasts)} forecasts; where the driver forecast exists, ML ${pct(reW.ml_bottom_up, 1)}, ETS ${pct(reW.ets_total, 1)}, driver ${pct(reW.driver, 1)}. ${String(rc.verdict ?? '')}. ${String(rc.caveat)}`} />
        </Card>
        <Card title="GPU and cloud spend forecast" sub={`${sc.model} · next 3 months`}>
          <Trend rows={spendTotal.map((r) => ({ month: r.month, forecast: r.forecast, low_80: r.low_80, high_80: r.high_80, growth: r.growth_method }))}
            x="month" series={[{ key: 'forecast', label: 'ML', color: '#8a63d2' }, { key: 'low_80', label: 'Low (80%)', color: '#b8a6e6', dashed: true },
              { key: 'high_80', label: 'High (80%)', color: '#b8a6e6', dashed: true }, { key: 'growth', label: 'Growth method', color: '#7a8699', dashed: true }]} />
          <Verdict good={se.ml < se.growth_method}
            text={`Backtest: ML ${pct(se.ml, 1)} vs ${pct(se.growth_method, 1)} for the 3-month growth method. ${String(sc.verdict)}. ${String(sc.caveat)}`} />
        </Card>
      </div>

      <Card title="Deal win probability" sub={`${dc.model} · ML-weighted pipeline ${usd(pipe.ml_weighted)} vs CRM stage-weighted ${usd(pipe.crm_weighted)}`}>
        <Verdict good={String(dc.verdict).startsWith('the model beats')} text={`${String(dc.headline)}. ${String(dc.verdict)}. ${String(dc.caveat)}`} />
        <DataTable title="deal-predictions" rows={dealRows} columns={[
          { key: 'opportunity_id', label: 'Deal' }, { key: 'account_name', label: 'Account' }, { key: 'segment', chip: true }, { key: 'stage', chip: true },
          { key: 'amount_arr', label: 'ARR', unit: 'usd' }, { key: 'crm_probability', label: 'CRM stage', unit: 'ratio' },
          { key: 'ml_win_probability', label: 'ML win', unit: 'ratio' }, { key: 'close_date', label: 'Close' },
        ]} />
      </Card>

      <Card title="When each open invoice will be paid" sub="Model's expected date with a P10–P90 range, next to the cash forecast's rule">
        <DataTable title="payment-predictions" rows={(pay.data.rows ?? []) as Row[]} columns={[
          { key: 'invoice_ref', label: 'Invoice' }, { key: 'customer_id', label: 'Customer' }, { key: 'balance', unit: 'usd' },
          { key: 'due_date', label: 'Due' }, { key: 'expected_pay_date', label: 'Expected (model)' },
          { key: 'earliest_p10', label: 'Earliest (P10)' }, { key: 'latest_p90', label: 'Latest (P90)' },
          { key: 'rule_pay_date', label: 'Rule date' }, { key: 'is_disputed', label: 'Disputed', flag: 'bad' }, { key: 'note' },
        ]} />
      </Card>

      <Card title="Cost anomalies" sub={`${ac.model} · last 6 closed months`}>
        <Verdict good={planted.every((p) => Number(p.model_caught) === Number(p.periods))}
          text={`Planted anomalies in the history: ${planted.map((p) => `${p.anomaly}: model ${p.model_caught}/${p.periods}, fixed rule ${p.fixed_rule_caught}/${p.periods}`).join('; ')}. ${String(ac.caveat)}`} />
        <DataTable title="cost-anomalies" rows={(anom.data.rows ?? []) as Row[]} empty="Nothing unusual in the last 6 closed months." columns={[
          { key: 'month' }, { key: 'account_name', label: 'Account' }, { key: 'department_id', label: 'Dept' },
          { key: 'amount', unit: 'usd' }, { key: 'expected', label: 'Typical', unit: 'usd' },
          { key: 'expected_high', label: 'Upper bound', unit: 'usd' }, { key: 'robust_z', label: 'Robust z' },
          { key: 'fixed_rule', label: 'Fixed rule flags it', flag: 'warn' },
        ]} />
        {(anom.data.daily as Row[]).length > 0 && (
          <DataTable title="cloud-anomalies" rows={anom.data.daily as Row[]} columns={[
            { key: 'date' }, { key: 'service' }, { key: 'team' }, { key: 'cost', unit: 'usd' },
            { key: 'expected', label: 'Typical', unit: 'usd' }, { key: 'robust_z', label: 'Robust z' },
          ]} />
        )}
      </Card>

      <Card title="Model cards" sub="What each model predicts and how it compares with the current method">
        <DataTable title="ml-models" rows={models.data.rows as Row[]} columns={[
          { key: 'model' }, { key: 'method' }, { key: 'predicts' }, { key: 'result' }, { key: 'caveat' },
        ]} />
      </Card>
    </div>
  )
}
