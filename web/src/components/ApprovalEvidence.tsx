// What a reviewer needs before pressing Approve: a verdict badge from the checks (fetched fresh), what approving
// does, each control with pass / fail and its detail, the key facts, who is required to approve, links to the
// detail, a warning when the proposal goes against the checks, and an AI recommendation on current data.
import { useEffect, useState } from 'react'
import type { Action, Row } from '../api'
import { Chip, useWorkspace, type Page } from './common'
import { Recommend } from './Recommend'

export function useEvidence(id: string) {
  const [ev, setEv] = useState<Row | null>(null)
  useEffect(() => { fetch(`/api/actions/${id}/evidence`).then((r) => (r.ok ? r.json() : null)).then(setEv).catch(() => setEv(null)) }, [id])
  return ev
}

export function VerdictBadge({ ev }: { ev: Row | null }) {
  if (!ev) return null
  const failed = Number(ev.failed ?? 0)
  const kind = ev.verdict === 'no checks' ? 'info' : failed ? 'bad' : 'good'
  return <Chip value={String(ev.verdict)} kind={kind} />
}

export function ApprovalEvidence({ action, ev }: { action: Action; ev: Row | null }) {
  const [open, setOpen] = useState(false)
  const { go, inspect } = useWorkspace()
  if (!ev) return null
  const checks = (ev.rows ?? []) as Row[]
  const against = ev.proposal_agrees_with_checks === false && action.status === 'pending'
  return (
    <div className="approval-ev">
      {against && <div className="warn-line">Approving goes against {String(ev.failed)} failed check{Number(ev.failed) === 1 ? '' : 's'}: needs {String(ev.required_approver)}.</div>}
      <button className="link" onClick={() => setOpen(!open)}>{open ? 'Hide evidence' : 'Why? See the evidence'}</button>
      {open && (
        <div className="approval-ev-body">
          {ev.approve_means ? <p><b>Approve means:</b> {String(ev.approve_means)}</p> : null}
          {checks.length ? (
            <ul className="checks">
              {checks.map((c) => (
                <li key={String(c.check)} className={c.passed ? 'ok' : 'no'}>
                  <span className="mark">{c.passed ? '✓' : '✗'}</span>
                  <span>{String(c.check)}{c.detail ? <span className="muted"> · {String(c.detail)}</span> : null}</span>
                </li>
              ))}
            </ul>
          ) : null}
          <div className="facts">{((ev.facts ?? []) as Row[]).map((f) => <span key={String(f.label)}><i>{String(f.label)}</i> {String(f.value)}</span>)}</div>
          <p className="muted" style={{ margin: '6px 0' }}>Required approver: <b>{String(ev.required_approver)}</b></p>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {((ev.links ?? []) as Row[]).map((l) => (
              <button key={String(l.label)} className="btn small" onClick={() => (l.entity ? inspect(l.entity as never) : go(String(l.page) as Page))}>{String(l.label)}</button>
            ))}
          </div>
          <Recommend kind="situation" subject={`Approval: ${action.preview.slice(0, 160)}`} context={`Checks: ${String(ev.verdict)}. ${checks.filter((c) => !c.passed).map((c) => `${String(c.check)}${c.detail ? ` (${String(c.detail)})` : ''}`).join('; ')}`} label="Should I approve? Ask AI" />
        </div>
      )}
    </div>
  )
}
