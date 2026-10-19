import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from './api'
import { Assistant } from './components/Assistant'
import { WorkspaceContext, type Page } from './components/common'
import { Home } from './pages/Home'
import { Alerts, Capital, Cash, Close, Commissions, DealDesk, Plan, Pricing, TaxFx } from './pages/Finance'
import { AP, AR, Billing, Budget, Projects, Revenue, Spend, Trust } from './pages/Modules'

const TABS: [Page, string][] = [
  ['home', 'Home'], ['alerts', 'Alerts'], ['plan', 'Plan'], ['cash', 'Cash'], ['close', 'Close'], ['revenue', 'Revenue'], ['spend', 'Tech spend'], ['budget', 'Budget'], ['projects', 'Projects'],
  ['billing', 'Billing'], ['ar', 'Receivables'], ['ap', 'AP inbox'], ['deals', 'Deal desk'], ['comp', 'Commissions'], ['pricing', 'Pricing'], ['capital', 'Capital'], ['tax', 'Tax & FX'], ['trust', 'Trust'],
]

export default function App() {
  const [page, setPage] = useState<Page>(() => (location.hash.slice(1) as Page) || 'home')
  const [pending, setPending] = useState<{ text: string; n: number } | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [asOf, setAsOf] = useState<string>()
  const [down, setDown] = useState(false)
  const [mobile, setMobile] = useState<'workspace' | 'assistant'>('workspace')  // which panel a phone shows

  useEffect(() => { api.health().then((h) => setAsOf(h.data_through)).catch(() => setDown(true)) }, [])
  useEffect(() => {  // links and the Back button change the hash; follow it
    const onHash = () => setPage((location.hash.slice(1) as Page) || 'home')
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  const go = useCallback((p: Page) => { setPage(p); location.hash = p; setMobile('workspace'); document.querySelector('.workspace')?.scrollTo({ top: 0 }) }, [])
  const ask = useCallback((text: string) => { setPending((p) => ({ text, n: (p?.n ?? 0) + 1 })); setMobile('assistant') }, [])
  const refresh = useCallback(() => setRefreshKey((k) => k + 1), [])
  const ctx = useMemo(() => ({ page, go, ask, refreshKey, refresh }), [page, go, ask, refreshKey, refresh])

  return (
    <WorkspaceContext.Provider value={ctx}>
      <div className={`shell show-${mobile}`}>
        <Assistant pending={pending} />
        <main className="workspace">
          <nav className="topbar">
            {TABS.map(([p, l]) => <button key={p} className={`tab ${page === p ? 'active' : ''}`} onClick={() => go(p)}>{l}</button>)}
            <span className="spacer" />
            <span className="faint" style={{ fontSize: 12 }}>{asOf ? `Data through ${asOf}` : ''}</span>
          </nav>
          {down ? (
            <div className="page"><div className="error">Can't reach the Finance OS API. Start it with <code>python -m finance_os.app</code> and reload.</div></div>
          ) : (
            <>
              {page === 'home' && <Home asOf={asOf} />}
              {page === 'revenue' && <Revenue />}
              {page === 'spend' && <Spend />}
              {page === 'budget' && <Budget />}
              {page === 'projects' && <Projects />}
              {page === 'billing' && <Billing />}
              {page === 'ar' && <AR />}
              {page === 'ap' && <AP />}
              {page === 'trust' && <Trust />}
              {page === 'alerts' && <Alerts />}
              {page === 'deals' && <DealDesk />}
              {page === 'comp' && <Commissions />}
              {page === 'plan' && <Plan />}
              {page === 'cash' && <Cash />}
              {page === 'close' && <Close />}
              {page === 'pricing' && <Pricing />}
              {page === 'capital' && <Capital />}
              {page === 'tax' && <TaxFx />}
            </>
          )}
        </main>
        <nav className="mobile-switch">
          <button className={mobile === 'workspace' ? 'on' : ''} onClick={() => setMobile('workspace')}>▦ Workspace</button>
          <button className={mobile === 'assistant' ? 'on' : ''} onClick={() => setMobile('assistant')}>✦ Assistant</button>
        </nav>
      </div>
    </WorkspaceContext.Provider>
  )
}
