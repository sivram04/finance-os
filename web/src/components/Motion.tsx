// Small motion helpers: numbers that count up to their value, and a formatted-string version for KPI tiles that
// already hold text like "$1.44M" or "66.1%". Respects prefers-reduced-motion.
import { useEffect, useRef, useState } from 'react'

const reduced = () => typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

export function useCountUp(target: number, ms = 900) {
  const [v, setV] = useState(reduced() ? target : 0)
  const from = useRef(0)
  useEffect(() => {
    if (reduced() || !Number.isFinite(target)) { setV(target); return }
    const start = performance.now(), a = from.current
    let raf = 0
    const tick = (t: number) => {
      const p = Math.min(1, (t - start) / ms)
      const e = 1 - Math.pow(1 - p, 3)
      setV(a + (target - a) * e)
      if (p < 1) raf = requestAnimationFrame(tick)
      else from.current = target
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target, ms])
  return v
}

export function CountUp({ value, format }: { value: number; format: (n: number) => string }) {
  const v = useCountUp(value)
  return <>{format(v)}</>
}

/** Animate the first number inside an already-formatted string ("$1.44M", "−$582.8K", "66.1%", "12 mo"). */
export function CountText({ text }: { text: string }) {
  const m = /(-?\d[\d,]*\.?\d*)/.exec(text)
  const num = m ? Number(m[1].replace(/,/g, '')) : NaN
  const v = useCountUp(Number.isFinite(num) ? num : 0)
  if (!m || !Number.isFinite(num)) return <>{text}</>
  const decimals = (m[1].split('.')[1] ?? '').length
  const commas = m[1].includes(',')
  const shown = commas ? v.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) : v.toFixed(decimals)
  return <>{text.slice(0, m.index)}{shown}{text.slice(m.index + m[1].length)}</>
}
