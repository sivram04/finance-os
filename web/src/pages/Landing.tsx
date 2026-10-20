// Landing page: what Finance OS is, how it helps a finance team, and how to find your way around. Every number on it
// is live from the warehouse (the same tools the dashboards and assistant use).
import { useEffect, useMemo, useRef, useState } from 'react'
import { api, fmt, type Row } from '../api'
import { useWorkspace, type Page } from '../components/common'
import { CountUp } from '../components/Motion'

const usd = (v: unknown) => fmt('amount', Number(v ?? 0), 'usd')

const HELPS = [
  { pain: 'Month-end takes days of spreadsheet stitching', gain: 'Books close on a checklist with evidence; every number reconciles to source automatically',
    proof: 'Close and Trust pages · 19 reconciliation checks a month', page: 'close' as Page },
  { pain: '"Why are we off budget?" takes a week to answer', gain: 'Click any variance: source lines, reconciliation, root cause and owner in one place, plus an AI recommendation on current data',
    proof: 'Budget → open a variance case', page: 'budget' as Page },
  { pain: 'Nobody agrees on what ARR or runway means', gain: 'One governed metric catalog: definition, owner, version, source, threshold and reconciliation for every number',
    proof: 'Decision KPIs · 33 metric contracts', page: 'kpis' as Page },
  { pain: 'Forecasts are a black box', gain: 'One driver engine for forecast, scenarios and runway, and every change since last close explained',
    proof: 'Plan, Scenarios, Drivers', page: 'plan' as Page },
  { pain: 'GPU and cloud bills grow faster than revenue', gain: 'Cost per audio hour, idle GPU, commitments and anomalies, tied to the customers who drive them',
    proof: 'Tech spend, contribution bridge', page: 'spend' as Page },
  { pain: 'Deals get discounted below margin', gain: 'Deal desk prices with real unit costs, checks guardrails and terms, and routes exceptions to the right approver',
    proof: 'Deal desk', page: 'deals' as Page },
]

const GUIDE: { name: string; blurb: string; pages: [Page, string, string][] }[] = [
  { name: 'Overview', blurb: 'Start here: where the company stands and what needs a decision.', pages: [
    ['home', 'Home', 'This month at a glance and what needs you'], ['ceo', 'CEO one-pager', 'Top five opportunities and risks in dollars, and the decisions needed'],
    ['kpis', 'Decision KPIs', 'Every KPI with its threshold, status, owner, source and reconciliation'], ['explore', 'Explore', 'Ask the ledger anything: any account, customer, vendor or period'],
    ['financials', 'Financials', 'P&L, balance sheet and cash flow, with Excel export'], ['alerts', 'Alerts', 'What crossed a threshold today'], ['reports', 'Reports', 'Board pack and recurring reports']] },
  { name: 'Plan & cash', blurb: 'Where we are going and how long the money lasts.', pages: [
    ['plan', 'Plan', 'Forecast by scenario, what changed since last close, workforce plan'], ['analysis', 'Analysis', 'Unit economics, break-even, runway sensitivity, five-year plan'],
    ['scenarios', 'Scenarios', 'Move the levers: churn, win rate, price, GPU cost, hiring, fundraising'], ['drivers', 'Drivers', 'Bridges and the driver tree: why the numbers moved'],
    ['corpfin', 'Corporate finance', 'Ratios, DuPont, taxes, EFN, WACC and project evaluation'], ['cash', 'Cash', '13-week cash, covenants, sweeps'], ['capital', 'Capital', 'Cap table and fundraising']] },
  { name: 'Revenue', blurb: 'Who pays us, how much, and whether it lasts.', pages: [
    ['revenue', 'Revenue', 'Customer and product margins'], ['growth', 'Growth', 'ARR waterfall, cohorts, retention'], ['contracts', 'Contracts', 'Committed revenue, RPO and renewals at risk'],
    ['pipeline', 'Pipeline', 'Bookings forecast and sales capacity'], ['deals', 'Deal desk', 'Price and approve deals'], ['comp', 'Commissions', 'Statements, disputes, deferred commissions'], ['ar', 'Receivables', 'Collections and expected payments']] },
  { name: 'Spend', blurb: 'Where the money goes and whether it is worth it.', pages: [
    ['spend', 'Tech spend', 'GPU and cloud cost, idle capacity, anomalies'], ['budget', 'Budget', 'Budget vs actual with a full case file per variance'], ['ap', 'AP inbox', 'Vendor bills read, checked and routed'], ['projects', 'Projects', 'Project margins and funding']] },
  { name: 'Close & control', blurb: 'Can we trust the numbers?', pages: [
    ['close', 'Close', 'The month-end checklist with evidence'], ['entities', 'Entities', 'Multi-entity consolidation and eliminations'], ['tax', 'Tax & FX', 'Sales tax, VAT and currency'], ['trust', 'Trust', 'Every reconciliation and data-freshness check']] },
]

const QUESTIONS = ['Which KPIs are red this month and what should I do about them?', 'Why is usage revenue below budget this year?',
  'What happens to cash if our largest customer leaves?', 'Can we sell 30,000 streaming hours a month at a 15% discount?']

function useReveal() {
  // sections fade up as they scroll into view; anything already on screen (or every section, if the observer never
  // fires, e.g. in a background tab) shows after a moment so content is never left hidden
  useEffect(() => {
    const els = [...document.querySelectorAll('.reveal')]
    const show = (el: Element) => el.classList.add('in')
    const io = 'IntersectionObserver' in window
      ? new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { show(e.target); io?.unobserve(e.target) } }), { threshold: 0.12 })
      : null
    els.forEach((el) => (io ? io.observe(el) : show(el)))
    const first = window.setTimeout(() => els.forEach((el) => { if (el.getBoundingClientRect().top < window.innerHeight) show(el) }), 60)
    const all = window.setTimeout(() => els.forEach(show), 1500)
    return () => { io?.disconnect(); window.clearTimeout(first); window.clearTimeout(all) }
  }, [])
}

// Shown instantly while the demo server wakes up (it sleeps when idle), then replaced by the live figures.
// The last closed month's headline numbers; update after each month-end close.
const LAST_CLOSE = {
  label: 'Sep 2026 close',
  head: { month: '2026-09', revenue: 1444075.9, arr: 16304727.36, closing_cash: 12356003.86, gross_margin_pct: 0.6608 } as Row,
  kpis: 18,
  queue: 34,
}

export function Landing({ theme, onTheme }: { theme: 'light' | 'dark'; onTheme: () => void }) {
  const { go, ask } = useWorkspace()
  const [data, setData] = useState<{ head?: Row; kpis?: Row; queue?: number; caseFile?: Row }>({})
  const [section, setSection] = useState(0)
  const [hover, setHover] = useState<number | null>(null)
  useReveal()
  useEffect(() => {
    api.data('get_ceo_one_pager').then((r) => setData((d) => ({ ...d, head: r.headline as Row }))).catch(() => {})
    api.data('get_decision_kpis').then((r) => setData((d) => ({ ...d, kpis: r.counts as Row }))).catch(() => {})
    fetch('/api/control-queue').then((r) => r.json()).then((q) => setData((d) => ({ ...d, queue: q.rows.filter((x: Row) => x.status === 'open').length }))).catch(() => {})
    api.data('get_variance_case', { alert_id: 'BVA-202609-NONE-4000' }).then((r) => setData((d) => ({ ...d, caseFile: r as unknown as Row }))).catch(() => {})
  }, [])
  const live = !!data.head
  const h = data.head ?? LAST_CLOSE.head
  const kpis = data.kpis ? Number(data.kpis.red) + Number(data.kpis.amber) : live ? undefined : LAST_CLOSE.kpis
  const queue = data.queue ?? (live ? undefined : LAST_CLOSE.queue)
  const scrollTo = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })

  return (
    <div className="landing">
      <nav className="landing-nav">
        <button className="brand" onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}><span className="brand-mark">◆</span> Finance OS</button>
        <div className="landing-links">
          <button onClick={() => scrollTo('what')}>Product</button>
          <button onClick={() => scrollTo('helps')}>How it helps</button>
          <button onClick={() => scrollTo('walkthrough')}>See it work</button>
          <button onClick={() => scrollTo('navigate')}>Navigate</button>
        </div>
        <div className="landing-actions">
          <button className="ghost" onClick={onTheme}>{theme === 'light' ? 'Dark' : 'Light'}</button>
          <button className="primary" onClick={() => go('home')}>Dashboard →</button>
        </div>
      </nav>

      <header className="hero" id="what">
        <div className="hero-copy reveal">
          <span className="eyebrow">AI finance workspace for Echo Labs</span>
          <h1>Every number explained, reconciled and owned.</h1>
          <p>Finance OS connects the ledger, billing, payroll, cloud and CRM into one governed warehouse, then turns it into
            dashboards, forecasts and an assistant that answers from the data. The dashboards state the facts: what happened,
            why, whether it reconciles and who owns it. Recommendations come from the AI, reasoned from that day's data,
            so they change when the situation does.</p>
          <div className="hero-cta">
            <button className="primary big" onClick={() => go('home')}>Open the dashboard</button>
            <button className="secondary big" onClick={() => scrollTo('walkthrough')}>Watch a variance become a decision</button>
          </div>
        </div>
        <div className="hero-live reveal">
          <div className="live-head"><span className={live ? 'pulse' : 'pulse idle'} /> {live
            ? `Live from the warehouse · closed through ${String(h.month)}`
            : `${LAST_CLOSE.label} · connecting to live data (the demo server wakes up in about 20 seconds)…`}</div>
          <div className="live-grid">
            <LiveStat label="Revenue this month" value={h?.revenue} money />
            <LiveStat label="Run-rate ARR" value={h?.arr} money />
            <LiveStat label="Cash" value={h?.closing_cash} money />
            <LiveStat label="Gross margin" value={Number(h.gross_margin_pct) * 100} suffix="%" decimals={1} />
            <LiveStat label="KPIs needing a decision" value={kpis} tone="warn" onClick={() => go('kpis')} />
            <LiveStat label="Open control items" value={queue} tone="warn" onClick={() => go('kpis')} />
          </div>
          <div className="live-foot">Click a tile to open it</div>
        </div>
      </header>

      <section id="helps" className="band">
        <div className="section-head reveal"><h2>How it helps</h2><p>The finance team's slowest questions, answered in a click. Hover a card, then open it.</p></div>
        <div className="help-grid">
          {HELPS.map((x, i) => (
            <div key={x.pain} className={`help-card reveal ${hover === i ? 'on' : ''}`} style={{ transitionDelay: `${i * 60}ms` }}
              onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <div className="pain">{x.pain}</div>
              <div className="gain">{x.gain}</div>
              <div className="help-foot"><span className="muted">{x.proof}</span><button className="link" onClick={() => go(x.page)}>Open →</button></div>
            </div>
          ))}
        </div>
      </section>

      <section id="walkthrough" className="band alt">
        <div className="section-head reveal"><h2>See it work: one variance, from data to the CFO's decision</h2>
          <p>Usage revenue for {data.caseFile ? String((data.caseFile.case as Row)?.month) : 'the latest month'}, straight from the warehouse. Press play or click a step.</p></div>
        <Walkthrough c={data.caseFile} onOpen={() => { location.hash = 'budget?alert=BVA-202609-NONE-4000' }} />
      </section>

      <section id="navigate" className="band">
        <div className="section-head reveal"><h2>How to navigate</h2><p>Five sections across the top; each has its pages in the second row. The assistant sits on the left and answers from the same data.</p></div>
        <div className="nav-guide reveal">
          <div className="nav-tabs">
            {GUIDE.map((g, i) => <button key={g.name} className={section === i ? 'on' : ''} onClick={() => setSection(i)} onMouseEnter={() => setSection(i)}>{g.name}</button>)}
          </div>
          <div className="nav-panel" key={section}>
            <p className="muted">{GUIDE[section].blurb}</p>
            <div className="nav-pages">
              {GUIDE[section].pages.map(([p, name, what]) => (
                <button key={p} className="nav-page" onClick={() => go(p)}><b>{name}</b><span>{what}</span><i>Open →</i></button>
              ))}
            </div>
          </div>
        </div>
        <div className="tips reveal">
          <div><b>Click to filter.</b> Click any bar or slice and the whole page filters to it; click a month on a trend to drill in.</div>
          <div><b>Zoom by year.</b> The Period control (All, each year, last 12 months) narrows every chart and table.</div>
          <div><b>Open anything.</b> Customer, vendor and project IDs open their full history; variances open a case file.</div>
          <div><b>Recommendations, not rules.</b> Advice is never a stored sentence: ask the AI and it reasons from the current data. Every answer shows the metric version, freshness, reconciliation and a link to the transactions.</div>
        </div>
      </section>

      <section className="band alt">
        <div className="section-head reveal"><h2>Ask it anything</h2><p>The assistant reads the warehouse with the same tools as the pages and never invents a number. Try one:</p></div>
        <div className="ask-grid reveal">
          {QUESTIONS.map((q) => <button key={q} className="ask-chip" onClick={() => { go('home'); setTimeout(() => ask(q), 50) }}>{q}<span>Ask →</span></button>)}
        </div>
      </section>

      <footer className="landing-foot">
        <span>Finance OS · Echo Labs · numbers from the governed warehouse, reconciled daily</span>
        <button className="primary" onClick={() => go('home')}>Open the dashboard →</button>
      </footer>
    </div>
  )
}

function LiveStat({ label, value, money, suffix = '', decimals = 0, tone, onClick }: { label: string; value: unknown; money?: boolean; suffix?: string; decimals?: number; tone?: string; onClick?: () => void }) {
  return (
    <button className={`live-stat ${tone ?? ''}`} onClick={onClick} disabled={!onClick}>
      <span className="label">{label}</span>
      <span className="value">{value == null ? '…' : <CountUp value={Number(value)} format={(n) => (money ? usd(n) : `${n.toFixed(decimals)}${suffix}`)} />}</span>
    </button>
  )
}

const STEPS = ['What happened', 'Source data', 'Reconciliation', 'Root cause', 'Owner and AI recommendation', 'CFO decision']

function Walkthrough({ c, onOpen }: { c?: Row; onOpen: () => void }) {
  const [step, setStep] = useState(0)
  const [playing, setPlaying] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => {
    if (!playing) return
    timer.current = window.setTimeout(() => setStep((s) => { if (s >= STEPS.length - 1) { setPlaying(false); return s } return s + 1 }), 3200)
    return () => window.clearTimeout(timer.current)
  }, [playing, step])
  const body = useMemo(() => {
    if (!c) return <div className="muted">Loading the case from the warehouse…</div>
    const k = c.case as Row, root = c.root_cause as Row
    const chain = (c.reconciliation_chain ?? []) as Row[]
    const comps = (c.root_cause_components ?? []) as Row[]
    const opts = (c.decision_options ?? []) as Row[]
    switch (step) {
      case 0: return <><p className="big-num bad"><CountUp value={Number(k.variance_favorable)} format={(n) => `${n < 0 ? '−' : '+'}${usd(Math.abs(n))}`} /></p>
        <p>{String(k.message)}. Year to date {usd(Number(k.ytd_actual) - Number(k.ytd_budget))}; the full year lands {usd(k.fy_forecast_variance)} vs budget.</p></>
      case 1: return <><p><b>{String(c.source_line_count)}</b> journal lines, one usage invoice per customer, total <b>{usd(c.source_lines_total)}</b>. Largest:</p>
        <ul>{((c.rows ?? []) as Row[]).slice(0, 4).map((r) => <li key={String(r.entry_id)}>{String(r.source_ref)} · {String(r.customer_id)} · {usd(r.amount)}</li>)}</ul></>
      case 2: return <div className="mini-chain">{chain.map((s) => <div key={String(s.step)} className={`mini-node ${String(s.status)}`}><span>{String(s.step)}</span><b>{s.amount != null ? usd(s.amount) : '—'}</b><i>{String(s.status)}</i></div>)}</div>
      case 3: return <><p><b>{String(root.classification)}.</b> {String(root.summary)}</p>
        <div className="mini-bars">{comps.map((x) => { const v = Number(x.amount); const w = Math.min(100, Math.abs(v) / 9000); return <div key={String(x.driver)}><span>{String(x.driver)}</span><i style={{ width: `${w}%`, background: v < 0 ? 'var(--bad)' : 'var(--good)' }} /><b>{usd(v)}</b></div> })}</div></>
      case 4: return <><p>Owner: <b>{String(k.owner)}</b></p>
        <p>There is no stored "do this" rule. In the dashboard, <b>Recommend with AI</b> sends this evidence to the assistant, which
          reasons over that day's numbers and returns two to four actions, each tied to a figure, with the owner and the trade-off.
          Seed new data tomorrow and the recommendation changes with it.</p></>
      default: return <><p>The CFO chooses; the choice, the note and the actions committed to are recorded with the evidence in the audit log.</p>
        <div className="mini-opts">{opts.map((o) => <div key={String(o.option)}><b>{String(o.option)}</b><span>{String(o.effect)}</span></div>)}</div>
        <button className="primary" onClick={onOpen}>Open this case in the dashboard →</button></>
    }
  }, [c, step, onOpen])
  return (
    <div className="walk reveal">
      <div className="walk-steps">
        {STEPS.map((s, i) => (
          <button key={s} className={`walk-step ${i === step ? 'on' : ''} ${i < step ? 'done' : ''}`} onClick={() => { setPlaying(false); setStep(i) }}>
            <span className="n">{i + 1}</span>{s}
            {i === step && playing && <span className="bar" />}
          </button>
        ))}
        <button className="secondary" onClick={() => { if (step >= STEPS.length - 1) setStep(0); setPlaying(!playing) }}>{playing ? 'Pause' : step >= STEPS.length - 1 ? 'Replay' : 'Play'}</button>
      </div>
      <div className="walk-body" key={step}>
        <h3>{step + 1}. {STEPS[step]}</h3>
        {body}
      </div>
    </div>
  )
}
