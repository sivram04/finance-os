import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from './api'
import { Assistant } from './components/Assistant'
import { Drawer } from './components/Drawer'
import { WorkspaceContext, type Entity, type Page } from './components/common'
import { PeriodContext, type Period } from './components/Dash'
import { Home } from './pages/Home'
import { Growth, Pipeline } from './pages/Exec'
import { Alerts, Analysis, Entities, Scenarios, Financials, Reports, Capital, Cash, Close, Commissions, DealDesk, Plan, Pricing, TaxFx } from './pages/Finance'
import { AP, AR, Billing, Budget, Projects, Revenue, Spend, Trust } from './pages/Modules'
import { CeoOnePager, Contracts, Drivers } from './pages/Insights'
import { Explore } from './pages/Explore'
import { DecisionKpis } from './pages/DecisionKpis'
import { Landing } from './pages/Landing'
import { Calculators, CorporateFinance } from './pages/CorpFin'

// pages grouped into sections: the top row picks a section, the second row its pages
const SECTIONS: { name: string; pages: [Page, string][] }[] = [
  { name: 'Overview', pages: [['home', 'Home'], ['ceo', 'CEO one-pager'], ['kpis', 'Decision KPIs'], ['explore', 'Explore'], ['financials', 'Financials'], ['alerts', 'Alerts'], ['reports', 'Reports']] },
  { name: 'Plan & cash', pages: [['plan', 'Plan'], ['analysis', 'Analysis'], ['scenarios', 'Scenarios'], ['drivers', 'Drivers'], ['corpfin', 'Corporate finance'], ['calculators', 'Calculators'], ['cash', 'Cash'], ['capital', 'Capital'], ['pricing', 'Pricing']] },
  { name: 'Revenue', pages: [['revenue', 'Revenue'], ['growth', 'Growth'], ['pipeline', 'Pipeline'], ['contracts', 'Contracts'], ['deals', 'Deal desk'], ['comp', 'Commissions'], ['billing', 'Billing'], ['ar', 'Receivables']] },
  { name: 'Spend', pages: [['spend', 'Tech spend'], ['ap', 'AP inbox'], ['budget', 'Budget'], ['projects', 'Projects']] },
  { name: 'Close & control', pages: [['close', 'Close'], ['entities', 'Entities'], ['tax', 'Tax & FX'], ['trust', 'Trust']] },
]

export default function App() {
  const [page, setPage] = useState<Page>(() => (location.hash.slice(1).split('?')[0] as Page) || 'welcome')
  const [pending, setPending] = useState<{ text: string; n: number } | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [asOf, setAsOf] = useState<string>()
  const [liveThrough, setLiveThrough] = useState<string>()
  const [down, setDown] = useState(false)
  const [entity, setEntity] = useState<Entity | null>(null)  // the open drill-down panel
  const [mobile, setMobile] = useState<'workspace' | 'assistant'>('workspace')  // which panel a phone shows
  const [period, setPeriod] = useState<Period>('all')
  const periodCtx = useMemo(() => ({ period, setPeriod }), [period])
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    try { return localStorage.getItem('theme') === 'dark' ? 'dark' : 'light' } catch { return 'light' }
  })
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try { localStorage.setItem('theme', theme) } catch { /* private window */ }
  }, [theme])
  const years = useMemo(() => {
    const last = asOf ? Number(asOf.slice(0, 4)) : new Date().getFullYear()
    return [String(last - 1), String(last)]
  }, [asOf])

  useEffect(() => { api.health().then((h) => { setAsOf(h.data_through); setLiveThrough(h.live_through) }).catch(() => setDown(true)) }, [])
  useEffect(() => {  // links and the Back button change the hash; follow it
    const onHash = () => setPage((location.hash.slice(1).split('?')[0] as Page) || 'welcome')
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  const go = useCallback((p: Page) => { setPage(p); location.hash = p; setMobile('workspace'); document.querySelector('.workspace')?.scrollTo({ top: 0 }); window.scrollTo({ top: 0 }) }, [])
  const ask = useCallback((text: string) => { setPending((p) => ({ text, n: (p?.n ?? 0) + 1 })); setMobile('assistant') }, [])
  const refresh = useCallback(() => setRefreshKey((k) => k + 1), [])
  const inspect = useCallback((e: Entity) => setEntity(e), [])
  const ctx = useMemo(() => ({ page, go, ask, refreshKey, refresh, inspect }), [page, go, ask, refreshKey, refresh, inspect])
  const section = SECTIONS.find((s) => s.pages.some(([p]) => p === page)) ?? SECTIONS[0]

  return (
    <PeriodContext.Provider value={periodCtx}>
    <WorkspaceContext.Provider value={ctx}>
      {page === 'welcome' ? <Landing theme={theme} onTheme={() => setTheme(theme === 'light' ? 'dark' : 'light')} /> : (
      <div className={`shell show-${mobile}`}>
        <Assistant pending={pending} />
        <main className="workspace">
          <nav className="topbar sections">
            <button className="brand-home" onClick={() => go('welcome')} title="About Finance OS">◆</button>
            {SECTIONS.map((s) => <button key={s.name} className={`tab ${s === section ? 'active' : ''}`} onClick={() => go(s.pages[0][0])}>{s.name}</button>)}
            <span className="spacer" />
            <button className="theme-toggle" onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')} title="Switch light / dark">{theme === 'light' ? 'Dark mode' : 'Light mode'}</button>
            <span className="faint" style={{ fontSize: 12 }}>{asOf ? `Books closed through ${new Date(asOf + 'T00:00').toLocaleString('en', { month: 'short', year: 'numeric' })}${liveThrough ? ` · live through ${new Date(liveThrough + 'T00:00').toLocaleString('en', { day: 'numeric', month: 'short' })}` : ''}` : ''}</span>
          </nav>
          <nav className="topbar subpages">
            {section.pages.map(([p, l]) => <button key={p} className={`tab ${page === p ? 'active' : ''}`} onClick={() => go(p)}>{l}</button>)}
            <div className="period-pick" title="Year range for every trend and monthly table">
              <span className="label">Period</span>
              {([['all', 'All'], ...years.map((y) => [y, y]), ['12m', 'Last 12 mo']] as [Period, string][]).map(([v, l]) =>
                <button key={v} className={period === v ? 'on' : ''} onClick={() => setPeriod(v)}>{l}</button>)}
            </div>
          </nav>
          {down ? (
            <div className="page"><div className="error">Can't reach the Finance OS API. Start it with <code>python -m finance_os.app</code> and reload.</div></div>
          ) : (
            <>
              <div key={page} className="page-enter">
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
              {page === 'reports' && <Reports />}
              {page === 'financials' && <Financials />}
              {page === 'analysis' && <Analysis />}
              {page === 'scenarios' && <Scenarios />}
              {page === 'entities' && <Entities />}
              {page === 'contracts' && <Contracts />}
              {page === 'drivers' && <Drivers />}
              {page === 'ceo' && <CeoOnePager />}
              {page === 'explore' && <Explore />}
              {page === 'kpis' && <DecisionKpis />}
              {page === 'corpfin' && <CorporateFinance />}
              {page === 'calculators' && <Calculators />}
              {page === 'growth' && <Growth />}
              {page === 'pipeline' && <Pipeline />}
              {page === 'deals' && <DealDesk />}
              {page === 'comp' && <Commissions />}
              {page === 'plan' && <Plan />}
              {page === 'cash' && <Cash />}
              {page === 'close' && <Close />}
              {page === 'pricing' && <Pricing />}
              {page === 'capital' && <Capital />}
              {page === 'tax' && <TaxFx />}
              </div>
            </>
          )}
        </main>
        {entity && <Drawer entity={entity} onClose={() => setEntity(null)} />}
        <nav className="mobile-switch">
          <button className={mobile === 'workspace' ? 'on' : ''} onClick={() => setMobile('workspace')}>▦ Workspace</button>
          <button className={mobile === 'assistant' ? 'on' : ''} onClick={() => setMobile('assistant')}>Assistant</button>
        </nav>
      </div>
      )}
    </WorkspaceContext.Provider>
    </PeriodContext.Provider>
  )
}
