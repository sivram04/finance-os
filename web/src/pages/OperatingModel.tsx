// The operating model in the browser: the same linked workbook as the Excel download, recalculated on the server for
// the chosen scenario. Click a cell to see its formula; the cells it reads are highlighted, and every reference in the
// formula bar is a link that jumps to that cell, on whichever sheet it lives.
import { useEffect, useMemo, useRef, useState } from 'react'
import { Card, Chip, Loading } from '../components/common'

type Cell = { c: number; ref: string; v: unknown; f: string | null; fmt: string; role: 'input' | 'formula' | 'link' | 'label'; bold: boolean; fill: string | null }
type SheetData = { name: string; max_col: number; rows: { r: number; cells: Cell[] }[] }
type Model = { scenario: string; status: string; sheets: SheetData[]; meta: { actual_from: string; actual_to: string; forecast_from: string; forecast_to: string } }
type Ref = { sheet: string; col: string; row: number; col2?: string; row2?: number; text: string }

const SCENARIOS = ['Base', 'Upside', 'Downside'] as const
const ROLE_COLOR: Record<string, string> = { input: '#1d4ed8', link: '#15803d', formula: 'var(--text)', label: 'var(--text)' }
const colIndex = (s: string) => s.split('').reduce((a, ch) => a * 26 + ch.charCodeAt(0) - 64, 0)
const colName = (n: number) => { let s = ''; while (n > 0) { const m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = Math.floor((n - 1) / 26) } return s }

// references inside a formula: A1, $C$4, C9:E9, Assumptions!$F$7, 'P&L'!O12
const REF = /(?:(?:'([^']+)'|([A-Za-z][A-Za-z0-9_]*))!)?\$?([A-Z]{1,3})\$?(\d+)(?::\$?([A-Z]{1,3})\$?(\d+))?/g
function parseRefs(f: string, sheet: string): { parts: (string | Ref)[]; refs: Ref[] } {
  const parts: (string | Ref)[] = [], refs: Ref[] = []
  let last = 0
  // skip text inside quotes ("Base", "cash generative")
  const masked = f.replace(/"[^"]*"/g, (m) => ' '.repeat(m.length))
  for (const m of masked.matchAll(REF)) {
    const idx = m.index ?? 0
    const before = masked[idx - 1]
    if (before && /[A-Za-z(]/.test(before) && !m[1] && !m[2] && before !== '(' ) continue
    const ref: Ref = { sheet: m[1] ?? m[2] ?? sheet, col: m[3], row: Number(m[4]), col2: m[5], row2: m[6] ? Number(m[6]) : undefined, text: f.slice(idx, idx + m[0].length) }
    parts.push(f.slice(last, idx), ref)
    refs.push(ref)
    last = idx + m[0].length
  }
  parts.push(f.slice(last))
  return { parts, refs }
}

function fmtValue(v: unknown, fmt: string): string {
  if (v == null || v === '') return ''
  if (typeof v === 'boolean') return v ? 'TRUE' : 'FALSE'
  if (typeof v !== 'number') return String(v)
  if (fmt.includes('%')) return `${(v * 100).toFixed(fmt.startsWith('0.00') ? 2 : 1)}%`
  if (fmt === 'General') return Number.isInteger(v) ? String(v) : v.toLocaleString('en-US', { maximumFractionDigits: 4 })
  const dp = fmt.startsWith('#,##0.0') ? 1 : 0
  if (Math.abs(v) < (dp ? 0.05 : 0.5)) return '–'
  const s = Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp })
  return v < 0 ? `(${s})` : s
}

const inRef = (r: Ref, col: number, row: number) => {
  const c1 = colIndex(r.col), c2 = r.col2 ? colIndex(r.col2) : c1
  const r1 = r.row, r2 = r.row2 ?? r.row
  return col >= Math.min(c1, c2) && col <= Math.max(c1, c2) && row >= Math.min(r1, r2) && row <= Math.max(r1, r2)
}

export function OperatingModel() {
  const [scenario, setScenario] = useState<(typeof SCENARIOS)[number]>('Base')
  const [model, setModel] = useState<Model>()
  const [error, setError] = useState<string>()
  const [sheet, setSheet] = useState('P&L')
  const [sel, setSel] = useState<{ sheet: string; ref: string } | null>(null)
  const [loading, setLoading] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)
  // bring the selected cell into view (after a jump to another sheet, or a reference far to the right)
  useEffect(() => {
    if (!sel || sel.sheet !== sheet) return
    const td = wrapRef.current?.querySelector<HTMLElement>(`td[data-ref="${sel.ref}"]`)
    const wrap = wrapRef.current
    if (td && wrap) {
      const label = wrap.querySelector<HTMLElement>('td.line')?.offsetWidth ?? 0
      if (td.offsetLeft - label < wrap.scrollLeft || td.offsetLeft + td.offsetWidth > wrap.scrollLeft + wrap.clientWidth)
        wrap.scrollLeft = Math.max(0, td.offsetLeft - label - 40)
      if (td.offsetTop < wrap.scrollTop + 60 || td.offsetTop > wrap.scrollTop + wrap.clientHeight - 40)
        wrap.scrollTop = Math.max(0, td.offsetTop - 120)
    }
  }, [sel, sheet, model])
  useEffect(() => {
    setLoading(true); setError(undefined)
    fetch(`/api/operating-model?scenario=${scenario}`)
      .then(async (r) => { if (!r.ok) throw new Error(await r.text()); return r.json() as Promise<Model> })
      .then(setModel).catch((e) => setError(String(e))).finally(() => setLoading(false))
  }, [scenario])

  const sheetData = model?.sheets.find((s) => s.name === sheet)
  const cellMap = useMemo(() => {
    const m = new Map<string, Cell>()
    model?.sheets.forEach((s) => s.rows.forEach((r) => r.cells.forEach((c) => m.set(`${s.name}!${c.ref}`, c))))
    return m
  }, [model])
  const selCell = sel ? cellMap.get(`${sel.sheet}!${sel.ref}`) : undefined
  const parsed = selCell?.f && sel ? parseRefs(selCell.f, sel.sheet) : null
  const precedents = (parsed?.refs ?? []).filter((r) => r.sheet === sheet)
  const jump = (r: Ref) => { setSheet(r.sheet); setSel({ sheet: r.sheet, ref: `${r.col}${r.row}` }) }

  if (!model) return <Card title="Operating model (linked)"><Loading state={{ loading: !error, error }} /></Card>
  const maxCol = sheetData?.max_col ?? 1
  const rowsByNum = new Map((sheetData?.rows ?? []).map((r) => [r.r, new Map(r.cells.map((c) => [c.c, c]))]))
  const lastRow = Math.max(...(sheetData?.rows ?? [{ r: 1 }]).map((r) => r.r))
  const ok = model.status === 'ALL CHECKS PASS'

  return (
    <Card
      title="Operating model (linked)"
      sub={`The same workbook as the Excel download: actuals ${model.meta.actual_from} to ${model.meta.actual_to} from the ledger, forecast ${model.meta.forecast_from} to ${model.meta.forecast_to} by formula. Click a cell to see its formula; the cells it uses light up, and each reference jumps to its source.`}
      right={<div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <span className="muted" style={{ fontSize: 12 }}>Scenario</span>
        <div className="segmented">{SCENARIOS.map((s) => <button key={s} className={scenario === s ? 'on' : ''} onClick={() => setScenario(s)}>{s}</button>)}</div>
        <Chip value={loading ? 'Recalculating…' : model.status} kind={loading ? 'info' : ok ? 'good' : 'bad'} />
        <a className="btn small" href="/api/operating-model.xlsx">Download (.xlsx)</a>
      </div>}>
      <div className="segmented" style={{ marginBottom: 8, flexWrap: 'wrap' }}>
        {model.sheets.map((s) => <button key={s.name} className={sheet === s.name ? 'on' : ''} onClick={() => { setSheet(s.name); setSel(null) }}>{s.name}</button>)}
      </div>
      <div className="formula-bar om-bar">
        <span className="ref">{sel ? `${sel.sheet === sheet ? '' : sel.sheet + '!'}${sel.ref}` : ''}</span>
        <span className="fx">fx</span>
        <span className="om-formula">
          {!selCell ? <span className="faint">Select a cell</span>
            : parsed ? parsed.parts.map((p, i) => typeof p === 'string' ? <span key={i}>{p}</span>
              : <button key={i} className={`om-ref ${p.sheet === sheet ? 'same' : 'other'}`} title={`Go to ${p.sheet}!${p.col}${p.row}`} onClick={() => jump(p)}>{p.text}</button>)
              : <span>{fmtValue(selCell.v, selCell.fmt)} <span className="faint">· {selCell.role === 'input' ? 'input (a ledger actual or an assumption)' : 'label'}</span></span>}
          {selCell?.f && <span className="faint"> = {fmtValue(selCell.v, selCell.fmt)}</span>}
        </span>
      </div>
      <div className="om-legend">
        <span><i style={{ background: '#1d4ed8' }} />Input</span><span><i style={{ background: 'var(--text)' }} />Formula</span>
        <span><i style={{ background: '#15803d' }} />Links to another sheet</span><span><i className="fc" />Forecast month</span>
        <span><i className="prec" />Cells the selected formula uses</span>
      </div>
      <div className="sheet-wrap" ref={wrapRef}>
        <table className="sheet om-sheet">
          <thead><tr><th className="corner" />{Array.from({ length: maxCol }, (_, i) => <th key={i} className="col-letter">{colName(i + 1)}</th>)}</tr></thead>
          <tbody>
            {Array.from({ length: lastRow }, (_, k) => k + 1).map((r) => {
              const row = rowsByNum.get(r)
              return (
                <tr key={r}>
                  <td className="rownum">{r}</td>
                  {Array.from({ length: maxCol }, (_, i) => i + 1).map((c) => {
                    const cell = row?.get(c)
                    const ref = `${colName(c)}${r}`
                    const isSel = sel?.sheet === sheet && sel.ref === ref
                    const isPrec = precedents.some((p) => inRef(p, c, r))
                    const header = cell?.fill === '1F3A5F'
                    const style: React.CSSProperties = {
                      color: header ? '#fff' : cell ? ROLE_COLOR[cell.role] : undefined,
                      fontWeight: cell?.bold ? 600 : undefined,
                      background: header ? '#1F3A5F' : cell?.fill === 'E8EDF3' ? 'var(--chip)' : cell?.fill === 'FFF8E6' ? 'var(--om-fc, #fff8e6)' : cell?.fill === 'FFFFCC' ? '#ffffcc' : undefined,
                      textAlign: c <= 2 || typeof cell?.v !== 'number' && typeof cell?.v !== 'boolean' ? 'left' : 'right',
                    }
                    return (
                      <td key={c} data-ref={ref} style={style} className={`${isSel ? 'sel' : ''} ${isPrec ? 'om-prec' : ''} ${c === 1 ? 'line' : ''}`}
                        onClick={() => cell && setSel({ sheet, ref })} title={cell?.f ?? undefined}>
                        {cell ? fmtValue(cell.v, cell.fmt) : ''}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
