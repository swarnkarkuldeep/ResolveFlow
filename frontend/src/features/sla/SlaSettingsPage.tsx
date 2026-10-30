import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { FormEvent } from 'react'

import { useAuth } from '../../app/auth'
import { useToast } from '../../app/Toasts'
import { api } from '../../lib/api'
import { formatMinutes } from '../../lib/format'
import { PRIORITIES, PRIORITY_LABEL } from '../../lib/types'
import type { Priority } from '../../lib/types'
import { Button, FormError, Spinner, TextInput } from '../../ui'

const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const
type Day = (typeof DAYS)[number]
const DAY_NAME: Record<Day, string> = {
  mon: 'Monday', tue: 'Tuesday', wed: 'Wednesday', thu: 'Thursday', fri: 'Friday', sat: 'Saturday', sun: 'Sunday',
}

interface Range {
  start: string
  end: string
}

interface Settings {
  enabled: boolean
  business_hours_only: boolean
  targets: Record<Priority, { first_response_minutes: number; resolution_minutes: number }>
  timezone: string
  schedule: Record<Day, Range[]>
  holidays: string[]
  version: number
}

interface Form {
  enabled: boolean
  business_hours_only: boolean
  targets: Record<Priority, { fr: string; res: string }>
  timezone: string
  schedule: Record<Day, Range[]>
  holidays: string[]
}

const FALLBACK_ZONES = ['UTC', 'Europe/London', 'Europe/Berlin', 'America/New_York', 'America/Chicago', 'America/Los_Angeles', 'Asia/Kolkata', 'Asia/Tokyo', 'Australia/Sydney']

function zones(current: string): string[] {
  const supported = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf?.('timeZone') ?? FALLBACK_ZONES
  const all = new Set(['UTC', ...supported, current])
  return [...all].sort()
}

function toForm(s: Settings): Form {
  return {
    enabled: s.enabled,
    business_hours_only: s.business_hours_only,
    targets: Object.fromEntries(
      PRIORITIES.map((p) => [p, { fr: String(s.targets[p].first_response_minutes), res: String(s.targets[p].resolution_minutes) }]),
    ) as Form['targets'],
    timezone: s.timezone,
    schedule: s.schedule,
    holidays: s.holidays,
  }
}

function toBody(f: Form) {
  const targets = Object.fromEntries(
    PRIORITIES.map((p) => [p, { first_response_minutes: Number(f.targets[p].fr), resolution_minutes: Number(f.targets[p].res) }]),
  )
  return {
    enabled: f.enabled,
    business_hours_only: f.business_hours_only,
    targets,
    timezone: f.timezone,
    schedule: f.schedule,
    holidays: f.holidays,
  }
}

function minutesPreview(value: string): string {
  const n = Number(value)
  return Number.isInteger(n) && n > 0 ? formatMinutes(n) : ''
}

function SettingsForm({ initial, editable }: { initial: Settings; editable: boolean }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [form, setForm] = useState<Form>(() => toForm(initial))
  const [error, setError] = useState<string | null>(null)
  const [date, setDate] = useState('')

  const dirty = JSON.stringify(form) !== JSON.stringify(toForm(initial))

  const save = useMutation({
    mutationFn: () => api<Settings>('/api/settings/sla', { method: 'PUT', body: toBody(form) }),
    onSuccess: () => {
      setError(null)
      toast('Service levels saved')
      void queryClient.invalidateQueries({ queryKey: ['sla-settings'] })
      void queryClient.invalidateQueries({ queryKey: ['tickets'] })
      void queryClient.invalidateQueries({ queryKey: ['ticket'] })
    },
    onError: (e) => setError(e.message),
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const numbers = PRIORITIES.flatMap((p) => [form.targets[p].fr, form.targets[p].res]).map(Number)
    if (numbers.some((n) => !Number.isInteger(n) || n < 1)) {
      setError('Enter whole numbers of minutes, 1 or more, for every target.')
      return
    }
    setError(null)
    save.mutate()
  }

  const setTarget = (p: Priority, key: 'fr' | 'res', value: string) =>
    setForm((f) => ({ ...f, targets: { ...f.targets, [p]: { ...f.targets[p], [key]: value } } }))
  const setRanges = (d: Day, ranges: Range[]) => setForm((f) => ({ ...f, schedule: { ...f.schedule, [d]: ranges } }))
  const setRange = (d: Day, i: number, key: keyof Range, value: string) =>
    setRanges(d, form.schedule[d].map((r, idx) => (idx === i ? { ...r, [key]: value } : r)))

  return (
    <form onSubmit={submit} noValidate>
      {!editable && (
        <p className="mb-6 rounded-panel border border-line bg-fog px-4 py-3 text-[14px] text-slate">
          Only an owner or admin can change service levels. You can see the current settings here.
        </p>
      )}
      <fieldset disabled={!editable} className="m-0 min-w-0 border-0 p-0">
        <div className="flex flex-col gap-3">
          <label className="flex items-center gap-2.5 text-[15px]">
            <input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} className="h-4 w-4 accent-[var(--accent)]" />
            Track service levels
          </label>
          <label className="flex items-center gap-2.5 text-[15px]">
            <input type="checkbox" checked={form.business_hours_only} onChange={(e) => setForm({ ...form, business_hours_only: e.target.checked })} className="h-4 w-4 accent-[var(--accent)]" />
            Count business hours only
          </label>
        </div>

        <h2 className="mb-1 mt-9 text-[18px] font-semibold tracking-tight">Targets</h2>
        <p className="mb-4 max-w-[60ch] text-[14px] text-slate">
          How long a ticket may wait for its first reply, and for a resolution. The clock pauses while a ticket is waiting on the customer.
        </p>
        <table className="w-full max-w-[640px] text-left text-[14px]">
          <thead className="text-[13px] text-slate">
            <tr className="border-b border-line">
              <th className="py-2 pr-3 font-medium">Priority</th>
              <th className="py-2 pr-3 font-medium">First response (minutes)</th>
              <th className="py-2 font-medium">Resolution (minutes)</th>
            </tr>
          </thead>
          <tbody>
            {[...PRIORITIES].reverse().map((p) => (
              <tr key={p} className="border-b border-line/70">
                <th scope="row" className="py-2.5 pr-3 font-medium">{PRIORITY_LABEL[p]}</th>
                {(['fr', 'res'] as const).map((key) => (
                  <td key={key} className="py-2 pr-3">
                    <div className="flex items-center gap-2">
                      <TextInput
                        type="number"
                        min={1}
                        aria-label={`${PRIORITY_LABEL[p]}: ${key === 'fr' ? 'first response' : 'resolution'} (minutes)`}
                        value={form.targets[p][key]}
                        onChange={(e) => setTarget(p, key, e.target.value)}
                        className="!h-9 !w-28"
                      />
                      <span className="tabular text-[13px] text-slate">{minutesPreview(form.targets[p][key])}</span>
                    </div>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>

        <h2 className="mb-1 mt-9 text-[18px] font-semibold tracking-tight">Business hours</h2>
        <p className="mb-4 max-w-[60ch] text-[14px] text-slate">Used when you count business hours only. Outside these hours the clock does not run.</p>
        <label className="mb-4 flex flex-col gap-1.5 text-[13px] text-slate">
          Time zone
          <select
            value={form.timezone}
            onChange={(e) => setForm({ ...form, timezone: e.target.value })}
            className="h-9 w-64 rounded-control border border-line bg-paper px-3 text-[15px] text-ink"
          >
            {zones(form.timezone).map((z) => (
              <option key={z} value={z}>
                {z}
              </option>
            ))}
          </select>
        </label>
        <ul className="flex max-w-[640px] flex-col">
          {DAYS.map((d) => {
            const ranges = form.schedule[d]
            return (
              <li key={d} className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line/70 py-2.5">
                <label className="flex w-40 items-center gap-2.5 text-[15px]">
                  <input
                    type="checkbox"
                    aria-label={`${DAY_NAME[d]} open`}
                    checked={ranges.length > 0}
                    onChange={(e) => setRanges(d, e.target.checked ? [{ start: '09:00', end: '17:00' }] : [])}
                    className="h-4 w-4 accent-[var(--accent)]"
                  />
                  {DAY_NAME[d]}
                </label>
                {ranges.length === 0 && <span className="text-[14px] text-slate">Closed</span>}
                <div className="flex flex-col gap-2">
                  {ranges.map((r, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <input
                        type="time"
                        aria-label={i === 0 ? `${DAY_NAME[d]} opens` : `${DAY_NAME[d]} range ${i + 1} opens`}
                        value={r.start}
                        onChange={(e) => setRange(d, i, 'start', e.target.value)}
                        className="h-9 rounded-control border border-line bg-paper px-2 text-[14px]"
                      />
                      <span className="text-slate">to</span>
                      <input
                        type="time"
                        aria-label={i === 0 ? `${DAY_NAME[d]} closes` : `${DAY_NAME[d]} range ${i + 1} closes`}
                        value={r.end}
                        onChange={(e) => setRange(d, i, 'end', e.target.value)}
                        className="h-9 rounded-control border border-line bg-paper px-2 text-[14px]"
                      />
                      {ranges.length > 1 && (
                        <Button type="button" variant="ghost" aria-label={`Remove ${DAY_NAME[d]} range ${i + 1}`} onClick={() => setRanges(d, ranges.filter((_, idx) => idx !== i))}>
                          Remove
                        </Button>
                      )}
                    </div>
                  ))}
                  {ranges.length > 0 && ranges.length < 4 && (
                    <Button type="button" variant="ghost" aria-label={`Add hours for ${DAY_NAME[d]}`} className="!w-fit" onClick={() => setRanges(d, [...ranges, { start: '13:00', end: '17:00' }])}>
                      Add hours
                    </Button>
                  )}
                </div>
              </li>
            )
          })}
        </ul>

        <h2 className="mb-1 mt-9 text-[18px] font-semibold tracking-tight">Closed dates</h2>
        <p className="mb-4 max-w-[60ch] text-[14px] text-slate">Whole days when the team is closed, such as public holidays. The clock does not run on these days.</p>
        <div className="mb-3 flex items-end gap-2">
          <label className="flex flex-col gap-1.5 text-[13px] text-slate">
            Closed date
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="h-9 rounded-control border border-line bg-paper px-2 text-[14px] text-ink" />
          </label>
          <Button
            type="button"
            disabled={!date || form.holidays.includes(date)}
            onClick={() => {
              setForm({ ...form, holidays: [...form.holidays, date].sort() })
              setDate('')
            }}
          >
            Add closed date
          </Button>
        </div>
        {form.holidays.length > 0 && (
          <ul className="flex flex-wrap gap-2">
            {form.holidays.map((h) => (
              <li key={h} className="inline-flex items-center gap-1 rounded-full border border-line bg-fog py-0.5 pl-3 pr-1 text-[14px] tabular">
                {h}
                <button
                  type="button"
                  aria-label={`Remove ${h}`}
                  onClick={() => setForm({ ...form, holidays: form.holidays.filter((x) => x !== h) })}
                  className="flex h-6 w-6 items-center justify-center rounded-full text-slate hover:bg-wash hover:text-ink"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
      </fieldset>

      {editable && (
        <div className="sticky bottom-0 -mx-6 mt-10 flex items-center gap-4 border-t border-line bg-paper px-6 py-4">
          <Button type="submit" variant="primary" disabled={!dirty || save.isPending}>
            {save.isPending ? 'Saving…' : 'Save changes'}
          </Button>
          <div className="min-w-0 flex-1">
            <FormError message={error} />
          </div>
        </div>
      )}
    </form>
  )
}

export function SlaSettingsPage() {
  const { can } = useAuth()
  const settings = useQuery({ queryKey: ['sla-settings'], queryFn: () => api<Settings>('/api/settings/sla') })

  return (
    <div className="h-full overflow-y-auto bg-paper">
      <div className="mx-auto max-w-[760px] px-6 pb-0 pt-8">
        <h1 className="text-[24px] font-semibold tracking-tight">Service levels</h1>
        <p className="mb-6 mt-1 max-w-[60ch] text-[14px] text-slate">
          The deadlines every ticket is measured against. Changes reach open tickets within a minute or so.
        </p>
        {settings.isPending && <Spinner label="Loading service levels" />}
        {settings.isError && <p className="text-danger">{settings.error.message}</p>}
        {settings.data && <SettingsForm key={settings.data.version} initial={settings.data} editable={can('settings:update')} />}
      </div>
    </div>
  )
}
