// What short ids mean (EN-004, MM-003, P-102, C-105, OPP-0047, AE-02…): loaded once from the warehouse, with a
// prefix-based fallback, so any id on a chart or table can show its full name on hover.
import { useEffect, useState } from 'react'
import { api } from '../api'

const names: Record<string, string> = {}
const listeners = new Set<() => void>()
let requested = false

const PREFIXES: [RegExp, string][] = [
  [/^EN-\d+$/, 'enterprise customer'], [/^MM-\d+$/, 'mid-market customer'], [/^SS-\d+$/, 'self-serve customer'],
  [/^FED-\d+$/, 'federal customer'], [/^P-\d+$/, 'project'], [/^C-\d+$/, 'contract'], [/^OPP-\d+$/, 'deal (CRM opportunity)'],
  [/^AE-\d+$/, 'sales rep (account executive)'], [/^(INV|PINV)/, 'invoice'], [/^Q-/, 'deal-desk quote'],
]

function load() {
  if (requested) return
  requested = true
  api.data('get_entity_names').then((r) => {
    for (const row of (r.rows ?? []) as { id: string; label: string }[]) names[row.id] = row.label
    listeners.forEach((f) => f())
  }).catch(() => { requested = false })
}

/** "EN-004 · Enterprise Customer 4 · enterprise customer", or null when the value is not an id. */
export function describe(value: unknown): string | null {
  const id = String(value ?? '')
  if (names[id]) return names[id]
  const hit = PREFIXES.find(([re]) => re.test(id))
  return hit ? `${id} · ${hit[1]}` : null
}

/** Re-render when the names arrive. */
export function useNames() {
  const [, bump] = useState(0)
  useEffect(() => {
    load()
    const f = () => bump((n) => n + 1)
    listeners.add(f)
    return () => { listeners.delete(f) }
  }, [])
}
