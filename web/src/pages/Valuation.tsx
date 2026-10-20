// Valuation: DCF on the five-year plan, trading-peer multiples and the last round, with a sensitivity grid and a
// football field of per-share ranges. Shown on the Corporate finance page.
import { fmt, type Row } from '../api'
import { AskButton, Card, DataTable, Loading, useTool } from '../components/common'

const usd = (v: unknown) => fmt('amount', Number(v ?? 0), 'usd')
const ps = (v: unknown) => `$${Number(v ?? 0).toFixed(2)}`
const pct = (v: unknown) => `${(Number(v) * 100).toFixed(1)}%`

export function Valuation() {
  const v = useTool('get_valuation')
  if (!v.data) return <Loading state={v} />
  const d = v.data as unknown as Record<string, unknown>
  const g = d.dcf_perpetual_growth as Row, ex = d.dcf_exit_multiple as Row, comps = d.comparables as Row
  const football = (d.rows ?? []) as Row[]
  const max = Math.max(...football.map((r) => Number(r.high))) * 1.1
  const grid = (d.sensitivity_per_share ?? []) as Row[]
  return (
    <>
      <h2 style={{ margin: '8px 0 -4px' }}>Valuation</h2>
      <div className="grid cols-2">
        <Card title="Football field: value per share" sub={`${Number(d.fully_diluted_shares).toLocaleString()} fully diluted shares · cash ${usd(d.cash)}, debt ${usd(d.debt)}`}
          right={<AskButton text="What is Echo Labs worth? Walk me through the DCF, the peer multiples and the last round, and why they differ." />}>
          <div className="football">
            {football.map((r) => (
              <div key={String(r.method)} className="ff-row">
                <span className="ff-label">{String(r.method)}</span>
                <div className="ff-track">
                  <div className="ff-bar" style={{ left: `${(Number(r.low) / max) * 100}%`, width: `${Math.max(0.8, ((Number(r.high) - Number(r.low)) / max) * 100)}%` }} />
                  <div className="ff-mid" style={{ left: `${(Number(r.mid) / max) * 100}%` }} title={`mid ${ps(r.mid)}`} />
                </div>
                <span className="ff-val">{Number(r.low) === Number(r.high) ? ps(r.low) : `${ps(r.low)} – ${ps(r.high)}`}</span>
              </div>
            ))}
          </div>
          <p className="sub" style={{ marginTop: 8 }}>{String(d.note)}</p>
        </Card>
        <Card title="DCF on the five-year plan" sub={`WACC ${pct(d.wacc)} · terminal growth ${pct(d.terminal_growth)} · exit ${Number(d.exit_ebitda_multiple)}x EBITDA`}>
          <DataTable title="dcf" rows={(d.plan ?? []) as Row[]} pageSize={6} columns={[
            { key: 'year', render: (r) => String(r.year) }, { key: 'revenue', unit: 'usd' }, { key: 'ebitda', unit: 'usd' },
            { key: 'free_cash_flow', label: 'Free cash flow', unit: 'usd' }, { key: 'pv_fcf', label: 'Present value', unit: 'usd' },
          ]} />
          <div className="kv" style={{ marginTop: 8 }}>
            <div><span>Sum of PV of free cash flow</span><b>{usd(g.sum_pv_fcf)}</b></div>
            <div><span>PV of terminal value (perpetual growth)</span><b>{usd(g.pv_terminal_value)} ({pct(g.terminal_share_of_ev)} of EV)</b></div>
            <div><span>Enterprise value → equity value</span><b>{usd(g.enterprise_value)} → {usd(g.equity_value)}</b></div>
            <div><span>Per share: perpetual growth / exit multiple</span><b>{ps(g.per_share)} / {ps(ex.per_share)}</b></div>
          </div>
        </Card>
      </div>
      <div className="grid cols-2">
        <Card title="Sensitivity: value per share" sub="DCF with perpetual growth; rows are WACC, columns terminal growth">
          <DataTable title="valuation-sensitivity" rows={grid} pageSize={5} columns={[
            { key: 'wacc', label: 'WACC', render: (r) => pct(r.wacc) },
            ...Object.keys(grid[0] ?? {}).filter((k) => k !== 'wacc').map((k) => ({ key: k, label: k, render: (r: Row) => ps(r[k]) })),
          ]} />
        </Card>
        <Card title="Trading peers" sub={`EV / NTM revenue on ${usd(comps.ntm_revenue)} · P25 ${Number(comps.p25).toFixed(1)}x, median ${Number(comps.median).toFixed(1)}x, P75 ${Number(comps.p75).toFixed(1)}x`}>
          <DataTable title="peers" rows={(comps.peers ?? []) as Row[]} pageSize={6} columns={[
            { key: 'peer' }, { key: 'ev_to_ntm_revenue', label: 'EV / NTM revenue', render: (r) => `${Number(r.ev_to_ntm_revenue).toFixed(1)}x` },
            { key: 'ntm_revenue_growth', label: 'Growth', unit: 'ratio' }, { key: 'gross_margin', label: 'Gross margin', unit: 'ratio' },
          ]} />
          <p className="sub" style={{ marginTop: 6 }}>Peer multiples are illustrative, not market data.</p>
        </Card>
      </div>
    </>
  )
}
