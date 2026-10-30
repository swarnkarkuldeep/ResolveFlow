import { PRIORITIES, PRIORITY_LABEL, STATUSES, STATUS_LABEL } from '../../lib/types'
import type { Member, Priority, Status, Team } from '../../lib/types'
import { Button, Select, TextInput } from '../../ui'
import { MAX_ACTIONS } from './vocab'
import type { Action, AssignSpec } from './vocab'

const TYPE_LABEL: Record<Action['type'], string> = {
  assign: 'Assign',
  set_priority: 'Set priority',
  set_status: 'Set status',
  add_tag: 'Add a tag',
  notify: 'Notify',
  escalate: 'Escalate',
}

interface Ctx {
  people: Member[]
  teams: Team[]
}

function assignable(people: Member[]) {
  return people.filter((p) => p.active && p.role !== 'viewer')
}

function defaultFor(type: Action['type'], ctx: Ctx): Action {
  const firstPerson = assignable(ctx.people)[0]?.user_id
  const firstTeam = ctx.teams[0]?.id
  switch (type) {
    case 'assign':
      return { type, target: 'user', user_id: firstPerson }
    case 'set_priority':
      return { type, value: 'high' }
    case 'set_status':
      return { type, value: 'open' }
    case 'add_tag':
      return { type, tag: '' }
    case 'notify':
      return { type, target: 'owners_admins' }
    case 'escalate':
      return { type, assign: { target: 'user', user_id: firstPerson }, message: '' }
  }
  void firstTeam
}

function AssignFields({ spec, ctx, onChange }: { spec: AssignSpec; ctx: Ctx; onChange: (s: AssignSpec) => void }) {
  return (
    <>
      <Select
        aria-label="Assign to"
        value={spec.target}
        onChange={(e) => {
          const target = e.target.value as AssignSpec['target']
          onChange(target === 'user' ? { target, user_id: assignable(ctx.people)[0]?.user_id } : { target, team_id: ctx.teams[0]?.id })
        }}
        className="!w-auto"
      >
        <option value="user">A specific person</option>
        <option value="round_robin">The next person in a team</option>
      </Select>
      {spec.target === 'user' ? (
        <Select aria-label="Person" value={spec.user_id ?? ''} onChange={(e) => onChange({ target: 'user', user_id: e.target.value })} className="!w-auto">
          <option value="" disabled>
            Choose a person
          </option>
          {assignable(ctx.people).map((p) => (
            <option key={p.user_id} value={p.user_id}>
              {p.name}
            </option>
          ))}
        </Select>
      ) : (
        <Select aria-label="Team" value={spec.team_id ?? ''} onChange={(e) => onChange({ target: 'round_robin', team_id: e.target.value })} className="!w-auto">
          <option value="" disabled>
            {ctx.teams.length ? 'Choose a team' : 'No teams yet'}
          </option>
          {ctx.teams.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </Select>
      )}
    </>
  )
}

function ActionRow({ index, action, ctx, onChange, onRemove }: { index: number; action: Action; ctx: Ctx; onChange: (a: Action) => void; onRemove: () => void }) {
  return (
    <div role="group" aria-label={`Action ${index + 1}`} className="flex flex-wrap items-center gap-2 rounded-panel border border-line px-3 py-2.5">
      <Select aria-label="Action type" value={action.type} onChange={(e) => onChange(defaultFor(e.target.value as Action['type'], ctx))} className="!w-auto">
        {(Object.keys(TYPE_LABEL) as Action['type'][]).map((t) => (
          <option key={t} value={t}>
            {TYPE_LABEL[t]}
          </option>
        ))}
      </Select>
      {action.type === 'assign' && <AssignFields spec={action} ctx={ctx} onChange={(s) => onChange({ type: 'assign', ...s })} />}
      {action.type === 'set_priority' && (
        <Select aria-label="Priority" value={action.value} onChange={(e) => onChange({ type: 'set_priority', value: e.target.value as Priority })} className="!w-auto">
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>
              {PRIORITY_LABEL[p]}
            </option>
          ))}
        </Select>
      )}
      {action.type === 'set_status' && (
        <Select aria-label="Status" value={action.value} onChange={(e) => onChange({ type: 'set_status', value: e.target.value as Status })} className="!w-auto">
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABEL[s]}
            </option>
          ))}
        </Select>
      )}
      {action.type === 'add_tag' && (
        <TextInput aria-label="Tag" value={action.tag} maxLength={40} onChange={(e) => onChange({ type: 'add_tag', tag: e.target.value })} className="!h-9 !w-48" />
      )}
      {action.type === 'notify' && (
        <>
          <Select
            aria-label="Notify"
            value={action.target}
            onChange={(e) => {
              const target = e.target.value as typeof action.target
              onChange(
                target === 'user'
                  ? { type: 'notify', target, user_id: ctx.people.find((p) => p.active)?.user_id, message: action.message }
                  : target === 'team'
                    ? { type: 'notify', target, team_id: ctx.teams[0]?.id, message: action.message }
                    : { type: 'notify', target, message: action.message },
              )
            }}
            className="!w-auto"
          >
            <option value="owners_admins">The owners and admins</option>
            <option value="assignee">The assignee</option>
            <option value="user">A specific person</option>
            <option value="team">A team</option>
          </Select>
          {action.target === 'user' && (
            <Select aria-label="Person" value={action.user_id ?? ''} onChange={(e) => onChange({ ...action, user_id: e.target.value })} className="!w-auto">
              <option value="" disabled>
                Choose a person
              </option>
              {ctx.people.filter((p) => p.active).map((p) => (
                <option key={p.user_id} value={p.user_id}>
                  {p.name}
                </option>
              ))}
            </Select>
          )}
          {action.target === 'team' && (
            <Select aria-label="Team" value={action.team_id ?? ''} onChange={(e) => onChange({ ...action, team_id: e.target.value })} className="!w-auto">
              <option value="" disabled>
                {ctx.teams.length ? 'Choose a team' : 'No teams yet'}
              </option>
              {ctx.teams.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </Select>
          )}
          <TextInput aria-label="Message (optional)" placeholder="Message (optional)" value={action.message ?? ''} maxLength={200} onChange={(e) => onChange({ ...action, message: e.target.value })} className="!h-9 min-w-[12rem] flex-1" />
        </>
      )}
      {action.type === 'escalate' && (
        <>
          <AssignFields spec={action.assign} ctx={ctx} onChange={(s) => onChange({ ...action, assign: s })} />
          <span className="text-[14px] text-slate">and notify the owners and admins</span>
          <TextInput aria-label="Message (optional)" placeholder="Message (optional)" value={action.message ?? ''} maxLength={200} onChange={(e) => onChange({ ...action, message: e.target.value })} className="!h-9 min-w-[12rem] flex-1" />
        </>
      )}
      <Button type="button" variant="ghost" aria-label="Remove action" onClick={onRemove} className="ml-auto">
        Remove
      </Button>
    </div>
  )
}

export function ActionEditor({ actions, ctx, onChange }: { actions: Action[]; ctx: Ctx; onChange: (a: Action[]) => void }) {
  return (
    <div role="group" aria-label="Actions" className="flex flex-col gap-2.5">
      {actions.map((a, i) => (
        <ActionRow
          key={i}
          index={i}
          action={a}
          ctx={ctx}
          onChange={(next) => onChange(actions.map((x, idx) => (idx === i ? next : x)))}
          onRemove={() => onChange(actions.filter((_, idx) => idx !== i))}
        />
      ))}
      {actions.length === 0 && <p className="text-[14px] text-slate">Add at least one thing for this automation to do.</p>}
      {actions.length < MAX_ACTIONS && (
        <Button type="button" className="!w-fit" onClick={() => onChange([...actions, defaultFor('set_priority', ctx)])}>
          Add action
        </Button>
      )}
    </div>
  )
}
