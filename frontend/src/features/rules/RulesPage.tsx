import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp } from 'lucide-react'
import { Link } from 'react-router-dom'

import { useAuth } from '../../app/auth'
import { useToast } from '../../app/Toasts'
import { api } from '../../lib/api'
import type { RuleSummary } from '../../lib/types'
import { Button, Spinner } from '../../ui'
import { useNames, useRules } from './queries'
import { describeDefinition } from './vocab'

function Badge({ children, tone = 'plain' }: { children: React.ReactNode; tone?: 'plain' | 'live' }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[12px] ${
        tone === 'live' ? 'border-accent text-accent' : 'border-line text-slate'
      }`}
    >
      {children}
    </span>
  )
}

export function RulesPage() {
  const { can } = useAuth()
  const manage = can('rule:manage')
  const rules = useRules()
  const { names } = useNames()
  const queryClient = useQueryClient()
  const toast = useToast()
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['rules'] })

  const reorder = useMutation({
    mutationFn: (ids: string[]) => api('/api/rules/reorder', { method: 'POST', body: { ids } }),
    onSuccess: () => void refresh(),
    onError: (e) => toast(e.message, 'error'),
  })
  const setArchived = useMutation({
    mutationFn: ({ id, archive }: { id: string; archive: boolean }) =>
      api(`/api/rules/${id}/${archive ? 'archive' : 'restore'}`, { method: 'POST', body: {} }),
    onSuccess: (_d, { archive }) => {
      toast(archive ? 'Automation archived' : 'Automation restored')
      void refresh()
    },
    onError: (e) => toast(e.message, 'error'),
  })

  const items = rules.data ?? []
  const open = items.filter((r) => r.status !== 'archived')

  const move = (rule: RuleSummary, delta: number) => {
    const ids = open.map((r) => r.id)
    const from = ids.indexOf(rule.id)
    const to = from + delta
    if (to < 0 || to >= ids.length) return
    ;[ids[from], ids[to]] = [ids[to], ids[from]]
    reorder.mutate(ids)
  }

  return (
    <div className="h-full overflow-y-auto bg-paper">
      <div className="mx-auto max-w-[860px] px-6 py-8">
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <h1 className="text-[24px] font-semibold tracking-tight">Automations</h1>
            <p className="mt-1 max-w-[56ch] text-[14px] text-slate">
              Rules that route and tidy up tickets for you. They run in order, and the first rule to set something wins.
            </p>
          </div>
          {manage && (
            <Link
              to="/automations/new"
              className="inline-flex h-9 items-center rounded-control bg-accent px-3.5 text-[14px] font-medium text-accent-ink hover:brightness-110"
            >
              New automation
            </Link>
          )}
        </div>
        {rules.isPending && <Spinner label="Loading automations" />}
        {rules.isError && <p className="text-danger">{rules.error.message}</p>}
        {rules.isSuccess && items.length === 0 && (
          <div className="py-10">
            <p className="font-medium">No automations yet</p>
            <p className="mt-1 max-w-[48ch] text-[14px] text-slate">
              Create your first one to assign, prioritise or tag tickets automatically. You will test it on a made-up ticket before it goes live.
            </p>
          </div>
        )}
        {items.length > 0 && (
          <ul aria-label="Automations">
            {items.map((r) => {
              const archived = r.status === 'archived'
              const index = open.findIndex((x) => x.id === r.id)
              return (
                <li key={r.id} className={`flex flex-wrap items-start justify-between gap-3 border-b border-line/70 py-4 ${archived ? 'opacity-70' : ''}`}>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Link to={`/automations/${r.id}`} className="text-[16px] font-medium hover:text-accent">
                        {r.name}
                      </Link>
                      {r.status === 'active' && <Badge tone="live">Live</Badge>}
                      {r.status === 'draft' && <Badge>Draft</Badge>}
                      {archived && <Badge>Archived</Badge>}
                      {!archived && <Badge>{r.tested ? 'Tested' : 'Not tested yet'}</Badge>}
                      {r.status === 'active' && r.active_version !== r.current_version && <Badge>Changes not live</Badge>}
                    </div>
                    <p className="mt-1 max-w-[70ch] text-[14px] text-slate">{describeDefinition(r.definition, names)}</p>
                  </div>
                  {manage && (
                    <div className="flex items-center gap-1">
                      {!archived && (
                        <>
                          <Button variant="ghost" aria-label={`Move ${r.name} up`} disabled={index <= 0 || reorder.isPending} onClick={() => move(r, -1)} className="!px-2">
                            <ArrowUp size={16} aria-hidden="true" />
                          </Button>
                          <Button variant="ghost" aria-label={`Move ${r.name} down`} disabled={index === open.length - 1 || reorder.isPending} onClick={() => move(r, 1)} className="!px-2">
                            <ArrowDown size={16} aria-hidden="true" />
                          </Button>
                        </>
                      )}
                      {archived ? (
                        <Button variant="ghost" aria-label={`Restore ${r.name}`} onClick={() => setArchived.mutate({ id: r.id, archive: false })}>
                          Restore
                        </Button>
                      ) : (
                        <Button variant="ghost" aria-label={`Archive ${r.name}`} onClick={() => setArchived.mutate({ id: r.id, archive: true })}>
                          Archive
                        </Button>
                      )}
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}
