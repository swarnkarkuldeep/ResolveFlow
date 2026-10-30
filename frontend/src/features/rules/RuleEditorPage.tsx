import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { useAuth } from '../../app/auth'
import { useToast } from '../../app/Toasts'
import { api } from '../../lib/api'
import type { RuleDetail } from '../../lib/types'
import { Button, Field, FormError, Select, Spinner, TextInput } from '../../ui'
import { ActionEditor } from './ActionEditor'
import { ConditionBuilder } from './ConditionBuilder'
import { useNames, useRule } from './queries'
import { TesterPanel } from './TesterPanel'
import { VersionsPanel } from './VersionsPanel'
import { EVENT_LABEL, emptyDefinition } from './vocab'
import type { EventName, RuleDefinition } from './vocab'

interface Draft {
  name: string
  definition: RuleDefinition
}

const NEW: Draft = { name: '', definition: emptyDefinition() }

export function RuleEditorPage() {
  const { id } = useParams()
  const isNew = !id
  const { can } = useAuth()
  const canManage = can('rule:manage')
  const rule = useRule(id)
  const { people, teams } = useNames()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const toast = useToast()
  const [draft, setDraft] = useState<Draft | null>(null)
  const [error, setError] = useState<string | null>(null)

  const saved: Draft | null = isNew ? NEW : rule.data ? { name: rule.data.name, definition: rule.data.definition } : null

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['rules'] })
    void queryClient.invalidateQueries({ queryKey: ['rule', id] })
  }

  const save = useMutation({
    mutationFn: (d: Draft) =>
      isNew
        ? api<RuleDetail>('/api/rules', { method: 'POST', body: { name: d.name.trim(), definition: d.definition } })
        : api<RuleDetail>(`/api/rules/${id}`, { method: 'PUT', body: { name: d.name.trim(), definition: d.definition } }),
    onSuccess: (r) => {
      setError(null)
      setDraft(null)
      toast('Automation saved')
      refresh()
      if (isNew) navigate(`/automations/${r.id}`, { replace: true })
    },
    onError: (e) => setError(e.message),
  })

  const activate = useMutation({
    mutationFn: (version: number) => api<RuleDetail>(`/api/rules/${id}/activate`, { method: 'POST', body: { version } }),
    onSuccess: (r) => {
      setError(null)
      toast(`Automation is live (version ${r.active_version})`)
      refresh()
    },
    onError: (e) => setError(e.message),
  })

  if (!isNew && rule.isPending) return <Spinner label="Loading automation" />
  if (!isNew && rule.isError)
    return (
      <div className="p-8">
        <p className="font-medium">Automation not found</p>
        <Link to="/automations" className="text-accent underline underline-offset-2">
          Back to automations
        </Link>
      </div>
    )
  if (!saved) return null

  const form = draft ?? saved
  const dirty = draft !== null && JSON.stringify(draft) !== JSON.stringify(saved)
  const r = rule.data
  const set = (patch: Partial<Draft>) => setDraft({ ...form, ...patch })
  const setDef = (patch: Partial<RuleDefinition>) => set({ definition: { ...form.definition, ...patch } })
  const trigger = form.definition.trigger

  const liveNote = !r
    ? 'Save this automation, record a passing test, then make it live.'
    : r.status === 'archived'
      ? 'This automation is archived.'
      : r.active_version === null
        ? 'This automation is not live yet.'
        : r.active_version === r.current_version
          ? `Version ${r.current_version} is live.`
          : `Version ${r.current_version} is not live yet. Version ${r.active_version} keeps running until you make it live.`

  const canActivate = !!r && !dirty && r.tested && r.status !== 'archived' && r.active_version !== r.current_version

  return (
    <div className="h-full overflow-y-auto bg-paper">
      <div className="mx-auto grid max-w-[1180px] gap-8 px-6 py-8 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0">
          <Link to="/automations" className="text-[14px] text-slate hover:text-ink">
            ← All automations
          </Link>
          <h1 className="mb-1 mt-2 text-[24px] font-semibold tracking-tight">{isNew ? 'New automation' : (r?.name ?? '')}</h1>
          <p className="mb-6 text-[14px] text-slate">{liveNote}</p>
          {!canManage && (
            <p className="mb-6 rounded-panel border border-line bg-fog px-4 py-3 text-[14px] text-slate">
              Only an owner or admin can change automations. You can see how this one is set up.
            </p>
          )}
          <fieldset disabled={!canManage} className="m-0 flex min-w-0 flex-col gap-8 border-0 p-0">
            <Field label="Name" htmlFor="rule-name">
              <TextInput id="rule-name" value={form.name} maxLength={120} onChange={(e) => set({ name: e.target.value })} />
            </Field>

            <section aria-label="Trigger">
              <h2 className="mb-2 text-[16px] font-semibold tracking-tight">When this happens</h2>
              <div className="flex flex-wrap items-center gap-2">
                <Select
                  aria-label="When"
                  value={trigger.event}
                  onChange={(e) => setDef({ trigger: { event: e.target.value as EventName } })}
                  className="!w-auto"
                >
                  {(Object.keys(EVENT_LABEL) as EventName[]).map((ev) => (
                    <option key={ev} value={ev}>
                      {EVENT_LABEL[ev]}
                    </option>
                  ))}
                </Select>
                {trigger.event === 'sla.threshold' && (
                  <Select
                    aria-label="Level"
                    value={trigger.level ?? ''}
                    onChange={(e) =>
                      setDef({ trigger: { event: 'sla.threshold', ...(e.target.value ? { level: e.target.value as 'warning' | 'breach' } : {}) } })
                    }
                    className="!w-auto"
                  >
                    <option value="">At risk or breached</option>
                    <option value="warning">At risk (75% of the target used)</option>
                    <option value="breach">Breached</option>
                  </Select>
                )}
              </div>
            </section>

            <section aria-label="Conditions section">
              <h2 className="mb-2 text-[16px] font-semibold tracking-tight">Only if</h2>
              <ConditionBuilder group={form.definition.conditions} onChange={(g) => setDef({ conditions: g })} />
            </section>

            <section aria-label="Actions section">
              <h2 className="mb-2 text-[16px] font-semibold tracking-tight">Then</h2>
              <ActionEditor actions={form.definition.actions} ctx={{ people, teams }} onChange={(a) => setDef({ actions: a })} />
            </section>
          </fieldset>

          <div className="sticky bottom-0 -mx-6 mt-8 flex flex-wrap items-center gap-3 border-t border-line bg-paper px-6 py-4">
            {canManage && (
              <>
                <Button variant="primary" disabled={!form.name.trim() || (!isNew && !dirty) || save.isPending} onClick={() => save.mutate(form)}>
                  {save.isPending ? 'Saving…' : 'Save automation'}
                </Button>
                {!isNew && (
                  <Button disabled={!canActivate || activate.isPending} onClick={() => r && activate.mutate(r.current_version)}>
                    Make live
                  </Button>
                )}
                {!isNew && !canActivate && r && r.active_version !== r.current_version && r.status !== 'archived' && (
                  <p className="text-[13px] text-slate">
                    {dirty ? 'Save your changes first.' : 'Record a passing test that expects a match before making this live.'}
                  </p>
                )}
              </>
            )}
            <div className="min-w-0 flex-1">
              <FormError message={error} />
            </div>
          </div>
        </div>

        <aside className="flex min-w-0 flex-col gap-6 lg:sticky lg:top-8 lg:self-start">
          {canManage && <TesterPanel definition={form.definition} ruleId={r?.id} dirty={dirty} onRecorded={refresh} />}
          {r && <VersionsPanel versions={r.versions} canManage={canManage} busy={activate.isPending} onRollback={(v) => activate.mutate(v)} />}
        </aside>
      </div>
    </div>
  )
}
