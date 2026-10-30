import { relativeTime } from '../../lib/format'
import type { RuleVersionInfo } from '../../lib/types'
import { Button } from '../../ui'

export function VersionsPanel({
  versions,
  canManage,
  busy,
  onRollback,
}: {
  versions: RuleVersionInfo[]
  canManage: boolean
  busy: boolean
  onRollback: (version: number) => void
}) {
  return (
    <section aria-label="Versions" className="rounded-panel border border-line bg-paper p-4">
      <h2 className="mb-1 text-[16px] font-semibold tracking-tight">Versions</h2>
      <p className="mb-3 text-[13px] text-slate">Every save is a new version. Only a version with a passing test can go live.</p>
      <ul className="flex flex-col gap-2">
        {versions.map((v) => (
          <li key={v.version} className="flex flex-wrap items-center justify-between gap-2 text-[14px]">
            <span>
              <span className="font-medium">Version {v.version}</span>{' '}
              <span className="text-slate">
                · {v.active ? 'Live' : v.tested ? 'Tested' : 'Not tested yet'} · {v.author ?? 'Someone'} {relativeTime(v.created_at)}
              </span>
            </span>
            {canManage && v.tested && !v.active && (
              <Button variant="ghost" aria-label={`Roll back to version ${v.version}`} disabled={busy} onClick={() => onRollback(v.version)}>
                Make this live
              </Button>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
