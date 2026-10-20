// A short guided tour for first-time visitors: each step highlights one part of the screen and says what it does.
// It starts once per browser the first time someone opens the dashboard; the Tour button in the top bar replays it.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

type Step = { target?: string; title: string; body: string }

const STEPS: Step[] = [
  { title: 'Welcome to Finance OS', body: 'A finance workspace for Echo Labs, a simulated voice-AI company whose books, billing, usage and spend are generated fresh every day. This 1-minute tour shows what each part does.' },
  { target: '.topbar.sections', title: 'Five areas', body: 'Overview: headline numbers, the CEO one-pager and KPIs. Plan & cash: forecasts, scenarios and machine-learning predictions. Revenue: customers, pipeline, contracts and receivables. Spend: GPU and cloud costs, the AP inbox and budgets. Close & control: month-end close, entities, tax and data checks.' },
  { target: '.topbar.subpages', title: 'Pages in each area', body: 'Each area has its own pages. Every page reads the same governed warehouse, so a number is the same wherever it appears.' },
  { target: '.period-pick', title: 'Time range', body: 'Changes the period for every chart and monthly table on the page. "Oct to date" shows the month that is still open, projected to month end.' },
  { target: '.kpi-row, .scorecard', title: 'Headline numbers', body: 'The key figures for the page, coloured by how they compare with benchmarks or budget. Hover a card for what it means.' },
  { target: '.card:not(.kpi) .recharts-wrapper', title: 'Charts you can click', body: 'Click a bar or slice to filter the whole page by it; click a month on a trend to drill into that month. Hover a short id like EN-004 for its full name (EN = enterprise, MM = mid-market, SS = self-serve customer).' },
  { target: '.assistant, .chat-open, .mobile-switch', title: 'Ask the assistant', body: 'Ask anything in plain English ("why did revenue drop?"). It answers only from the warehouse, shows each step and its sources, and anything that changes data becomes an approval card for you to approve or reject. Close it with « for a full-width dashboard and reopen it any time.' },
  { target: '.topbar.sections .tab:nth-child(3)', title: 'Predictions (machine learning)', body: 'Under Plan & cash, Predictions shows the ML models: churn, expansion, revenue and spend forecasts, payment timing and cost anomalies, each tested against the method it would replace.' },
  { target: '.demo-banner', title: 'This is a demo', body: 'The company is simulated and refreshed daily. Approvals only change this demo, and assistant questions are capped per day.' },
  { title: "You're set", body: 'Start anywhere. Replay this tour any time with the Tour button at the top right.' },
]

const KEY = 'finance-os.tour-done'

// the first element matching the selector that is actually on screen (phones hide the assistant panel, for example)
function visible(selector: string): Element | null {
  return [...document.querySelectorAll(selector)].find((e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 }) ?? null
}

function seen() {
  try { return localStorage.getItem(KEY) === '1' } catch { return false }
}
function markSeen() {
  try { localStorage.setItem(KEY, '1') } catch { /* private window: the tour may show again */ }
}

export function useTour(active: boolean) {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (active && !seen()) {
      const t = setTimeout(() => setOpen(true), 900)  // let the page draw first
      return () => clearTimeout(t)
    }
  }, [active])
  const close = useCallback(() => {
    markSeen()
    setOpen(false)
    window.scrollTo({ top: 0 })  // highlighting scrolled the page; give the visitor the top bar back
    document.querySelector('.workspace')?.scrollTo({ top: 0 })
  }, [])
  return { open, start: () => setOpen(true), close }
}

export function Tour({ onClose }: { onClose: () => void }) {
  // steps whose element is on screen now (re-checked every render: KPIs and charts load after the tour opens)
  const [, tick] = useState(0)
  useEffect(() => { const t = setInterval(() => tick((n) => n + 1), 500); return () => clearInterval(t) }, [])
  const steps = STEPS.filter((s) => !s.target || visible(s.target))
  const [current, setCurrent] = useState(STEPS[0].title)
  const i = Math.max(0, steps.findIndex((s) => s.title === current))
  const setI = (n: number | ((n: number) => number)) => {
    const next = typeof n === 'function' ? n(i) : n
    setCurrent(steps[Math.max(0, Math.min(next, steps.length - 1))].title)
  }
  const [box, setBox] = useState<DOMRect | null>(null)
  const popRef = useRef<HTMLDivElement>(null)
  const [popHeight, setPopHeight] = useState(0)
  useLayoutEffect(() => { if (popRef.current) setPopHeight(popRef.current.offsetHeight) })
  const step = steps[i]

  useLayoutEffect(() => {
    const el = step.target ? visible(step.target) : null
    if (!el) { setBox(null); return }
    el.scrollIntoView({ block: 'center' })
    const measure = () => setBox(el.getBoundingClientRect())
    measure()
    const t = setTimeout(measure, 350)
    window.addEventListener('resize', measure)
    window.addEventListener('scroll', measure, true)
    return () => { clearTimeout(t); window.removeEventListener('resize', measure); window.removeEventListener('scroll', measure, true) }
  }, [step.title])

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [onClose])

  const pad = 6
  const vw = window.innerWidth, vh = window.innerHeight
  const W = Math.min(340, vw - 32)
  const popH = popHeight || 220
  let pos: React.CSSProperties = { left: (vw - W) / 2, top: Math.max(16, (vh - popH) / 2) }
  if (box) {
    const left = Math.min(Math.max(16, box.left), vw - W - 16)
    if (box.bottom + pad + 12 + popH < vh) pos = { left, top: box.bottom + pad + 12 }                 // below
    else if (box.top - pad - 12 - popH > 0) pos = { left, top: box.top - pad - 12 - popH }           // above
    else if (box.right + pad + 12 + W < vw) pos = { left: box.right + pad + 12, top: Math.min(Math.max(16, box.top), vh - popH - 16) }  // right
    else if (box.left - pad - 12 - W > 0) pos = { left: box.left - pad - 12 - W, top: Math.min(Math.max(16, box.top), vh - popH - 16) } // left
    else pos = { left, top: vh - popH - 16 }
  }
  const last = i >= steps.length - 1
  return (
    <div className="tour" role="dialog" aria-modal="true" aria-label={step.title}>
      {box
        ? <div className="tour-spot" style={{ left: box.left - pad, top: box.top - pad, width: box.width + pad * 2, height: box.height + pad * 2 }} />
        : <div className="tour-dim" />}
      <div className="tour-pop" ref={popRef} style={{ ...pos, width: W }}>
        <div className="tour-count">{i + 1} of {steps.length}</div>
        <h3>{step.title}</h3>
        <p>{step.body}</p>
        <div className="tour-actions">
          <button className="link" onClick={onClose}>{last ? '' : 'Skip tour'}</button>
          <span style={{ flex: 1 }} />
          {i > 0 && <button onClick={() => setI(i - 1)}>Back</button>}
          <button className="primary" onClick={() => (last ? onClose() : setI(i + 1))}>{last ? 'Start exploring' : 'Next'}</button>
        </div>
      </div>
    </div>
  )
}
