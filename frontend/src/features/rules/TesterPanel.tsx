import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../lib/api'
import { PRIORITIES, STATUSES } from '../../lib/types'
import type { TestResult, TraceNode } from '../../lib/types'
import { Button, Field, FormError, Select, TextArea, TextInput } from '../../ui'
import { EVENT_LABEL, FIELD_LABEL, operatorLabel } from './vocab'
import type { FieldName, RuleDefinition } from './vocab'

function Trace({ node }: { node: TraceNode }) {
  if (node.kind === 'group') {
    return (
      <ul className="flex flex-col gap-1.5 border-l border-line pl-3">
        <li className="text-[13px] text-slate">
          {node.op === 'and' ? 'All of these must match' : 'Any of these must match'}: {node.passed ? 'passed' : 'did not pass'}
        </li>
        {node.children.map((c, i) => (
          <li key={i}>
            <Trace node={c} />
          </li>
        ))}
      </ul>
    )
  }
  const value = Array.isArray(node.value) ? node.value.map((v) => `“${String(v)}”`).join(', ') : node.value ? `“${String(node.value)}”` : ''
  const field = node.field as FieldName
  const actual = Array.isArray(node.actual) ? node.actual.join(', ') || 'nothing' : node.actual === null || node.actual === undefined ? 'nobody' : String(node.actual)
  return (
    <div className="flex flex-col text-[14px]">
      <span className="flex items-center gap-2">
        <span aria-hidden="true" className={node.passed ? 'text-[var(--st-resolved)]' : 'text-danger'}>
          {node.passed ? '✓' : '✗'}
        </span>
        <span className="font-medium">{node.passed ? 'Passed' : 'Did not pass'}</span>
        <span>
          {FIELD_LABEL[field] ?? node.field} {operatorLabel(field, node.operator)} {value}
        </span>
      </span>
      <span className="ml-6 text-[13px] text-slate">Checked: {actual}</span>
    </div>
  )
}

export function TesterPanel({
  definition,
  ruleId,
  dirty,
  onRecorded,
}: {
  definition: RuleDefinition
  ruleId?: string
  dirty: boolean
  onRecorded: () => void
}) {
  const [sender, setSender] = useState('customer@example.com')
  const [subject, setSubject] = useState('Question about my order')
  const [body, setBody] = useState('Hello, I have a question about my order.')
  const [channel, setChannel] = useState('email')
  const [priority, setPriority] = useState('normal')
  const [status, setStatus] = useState('new')
  const [tags, setTags] = useState('')
  const [include, setInclude] = useState(false)
  const [expectation, setExpectation] = useState<'match' | 'no_match'>('match')
  const [result, setResult] = useState<TestResult | null>(null)
  const [recorded, setRecorded] = useState<'passed' | 'failed' | null>(null)
  const [error, setError] = useState<string | null>(null)

  const facts = {
    event: definition.trigger.event,
    ...(definition.trigger.event === 'sla.threshold' ? { level: definition.trigger.level ?? 'warning' } : {}),
    sender_email: sender,
    subject,
    body,
    channel,
    priority,
    status,
    tags: tags.split(',').map((t) => t.trim()).filter(Boolean),
    assignee: { kind: 'none' },
  }

  const run = useMutation({
    mutationFn: () => api<TestResult>('/api/rules/test', { method: 'POST', body: { definition, facts, include_active_rules: include } }),
    onSuccess: (r) => {
      setResult(r)
      setRecorded(null)
      setError(null)
    },
    onError: (e) => setError(e.message),
  })

  const record = useMutation({
    mutationFn: () => api<TestResult>(`/api/rules/${ruleId}/tests`, { method: 'POST', body: { facts, expectation, include_active_rules: include } }),
    onSuccess: (r) => {
      setResult(r)
      setRecorded(r.passed ? 'passed' : 'failed')
      setError(null)
      onRecorded()
    },
    onError: (e) => setError(e.message),
  })

  return (
    <section aria-label="Test it" className="rounded-panel border border-line bg-paper p-4">
      <h2 className="mb-1 text-[16px] font-semibold tracking-tight">Test it</h2>
      <p className="mb-4 text-[13px] text-slate">
        Try this on a made-up ticket. Nothing is changed. Event: {EVENT_LABEL[definition.trigger.event].toLowerCase()}.
      </p>
      <div className="grid gap-3">
        <Field label="Sender email (test ticket)" htmlFor="t-sender">
          <TextInput id="t-sender" value={sender} onChange={(e) => setSender(e.target.value)} className="!h-9" />
        </Field>
        <Field label="Subject (test ticket)" htmlFor="t-subject">
          <TextInput id="t-subject" value={subject} onChange={(e) => setSubject(e.target.value)} className="!h-9" />
        </Field>
        <Field label="Message text (test ticket)" htmlFor="t-body">
          <TextArea id="t-body" rows={3} value={body} onChange={(e) => setBody(e.target.value)} />
        </Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Channel (test ticket)" htmlFor="t-channel">
            <Select id="t-channel" value={channel} onChange={(e) => setChannel(e.target.value)}>
              {['email', 'form', 'manual'].map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Priority (test ticket)" htmlFor="t-priority">
            <Select id="t-priority" value={priority} onChange={(e) => setPriority(e.target.value)}>
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Status (test ticket)" htmlFor="t-status">
            <Select id="t-status" value={status} onChange={(e) => setStatus(e.target.value)}>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label="Tags (test ticket, comma separated)" htmlFor="t-tags">
          <TextInput id="t-tags" value={tags} onChange={(e) => setTags(e.target.value)} className="!h-9" />
        </Field>
        <label className="flex items-center gap-2 text-[14px]">
          <input type="checkbox" checked={include} onChange={(e) => setInclude(e.target.checked)} className="h-4 w-4 accent-[var(--accent)]" />
          Include my other live automations
        </label>
        <Button type="button" onClick={() => run.mutate()} disabled={run.isPending}>
          {run.isPending ? 'Running…' : 'Run test'}
        </Button>
      </div>

      <FormError message={error} />

      {result && (
        <section aria-label="Test result" className="mt-5 flex flex-col gap-3 border-t border-line pt-4">
          <p className="text-[15px] font-medium">
            {result.matched
              ? 'This automation would run.'
              : result.trigger_matched
                ? 'This automation would not run: the conditions did not all match.'
                : 'This automation would not run: it is triggered by a different event.'}
          </p>
          {result.conditions && <Trace node={result.conditions} />}
          {result.actions.length > 0 && (
            <div>
              <h3 className="mb-1.5 text-[14px] font-semibold">What it would do</h3>
              <ul className="flex flex-col gap-1 text-[14px]">
                {result.actions.map((a, i) => (
                  <li key={i} className="flex flex-col">
                    <span>{a.text}</span>
                    {a.status === 'skipped' && <span className="text-[13px] text-slate">Skipped: {a.reason}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      <div className="mt-5 border-t border-line pt-4">
        {ruleId ? (
          <>
            <fieldset className="mb-3 flex flex-col gap-1.5 border-0 p-0 text-[14px]">
              <legend className="mb-1 text-[13px] text-slate">What do you expect?</legend>
              <label className="flex items-center gap-2">
                <input type="radio" name="expectation" checked={expectation === 'match'} onChange={() => setExpectation('match')} className="accent-[var(--accent)]" />
                I expect this to match
              </label>
              <label className="flex items-center gap-2">
                <input type="radio" name="expectation" checked={expectation === 'no_match'} onChange={() => setExpectation('no_match')} className="accent-[var(--accent)]" />
                I expect it not to match
              </label>
            </fieldset>
            <Button type="button" variant="primary" onClick={() => record.mutate()} disabled={dirty || record.isPending}>
              Record as test
            </Button>
            {dirty && <p className="mt-2 text-[13px] text-slate">Save your changes first so the test applies to this version.</p>}
            {recorded === 'passed' && <p className="mt-2 text-[14px] font-medium">Test passed</p>}
            {recorded === 'failed' && <p className="mt-2 text-[14px] text-danger">That did not match what you expected, so it does not count as a pass.</p>}
          </>
        ) : (
          <p className="text-[13px] text-slate">Save the automation to record a test. A passing test is needed before it can go live.</p>
        )}
      </div>
    </section>
  )
}
