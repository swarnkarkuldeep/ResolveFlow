import type { Priority, Status } from '../../lib/types'

export type EventName = 'ticket.created' | 'message.received' | 'status.changed' | 'sla.threshold'
export type FieldName = 'sender_email' | 'sender_domain' | 'subject' | 'body' | 'channel' | 'priority' | 'status' | 'tags' | 'assignee'

export interface Condition {
  field: FieldName
  operator: string
  value: string | string[] | null
}
export interface Group {
  op: 'and' | 'or'
  items: (Condition | Group)[]
}

export interface AssignSpec {
  target: 'user' | 'round_robin'
  user_id?: string
  team_id?: string
}
export type Action =
  | ({ type: 'assign' } & AssignSpec)
  | { type: 'set_priority'; value: Priority }
  | { type: 'set_status'; value: Status }
  | { type: 'add_tag'; tag: string }
  | { type: 'notify'; target: 'user' | 'team' | 'assignee' | 'owners_admins'; user_id?: string; team_id?: string; message?: string }
  | { type: 'escalate'; assign: AssignSpec; message?: string }

export interface RuleDefinition {
  trigger: { event: EventName; level?: 'warning' | 'breach' }
  conditions: Group
  actions: Action[]
}

export const EVENT_LABEL: Record<EventName, string> = {
  'ticket.created': 'A new ticket arrives',
  'message.received': 'A customer replies',
  'status.changed': 'A ticket’s status changes',
  'sla.threshold': 'A service level deadline is reached',
}

export const EVENT_PHRASE: Record<EventName, string> = {
  'ticket.created': 'a new ticket arrives',
  'message.received': 'a customer replies',
  'status.changed': 'a ticket’s status changes',
  'sla.threshold': 'a service level deadline is reached',
}

export const FIELD_LABEL: Record<FieldName, string> = {
  sender_email: 'Sender email',
  sender_domain: 'Sender domain',
  subject: 'Subject',
  body: 'Message text',
  channel: 'Channel',
  priority: 'Priority',
  status: 'Status',
  tags: 'Tags',
  assignee: 'Assignee',
}

const TEXT_OPS = ['equals', 'not_equals', 'contains', 'not_contains', 'contains_any', 'starts_with', 'ends_with']
const ENUM_OPS = ['equals', 'not_equals', 'in']

export const FIELD_OPERATORS: Record<FieldName, string[]> = {
  sender_email: TEXT_OPS,
  sender_domain: ENUM_OPS,
  subject: TEXT_OPS,
  body: TEXT_OPS,
  channel: ENUM_OPS,
  priority: ENUM_OPS,
  status: ENUM_OPS,
  tags: ['contains', 'not_contains', 'contains_any', 'is_empty', 'is_not_empty'],
  assignee: ['is_empty', 'is_not_empty'],
}

export const OPERATOR_LABEL: Record<string, string> = {
  equals: 'is',
  not_equals: 'is not',
  contains: 'contains',
  not_contains: 'does not contain',
  contains_any: 'contains any of',
  starts_with: 'starts with',
  ends_with: 'ends with',
  in: 'is one of',
  is_empty: 'is empty',
  is_not_empty: 'is not empty',
}

export const ASSIGNEE_OPERATOR_LABEL: Record<string, string> = { is_empty: 'is nobody', is_not_empty: 'is somebody' }

export const ENUM_VALUES: Partial<Record<FieldName, string[]>> = {
  channel: ['email', 'form', 'manual'],
  priority: ['low', 'normal', 'high', 'urgent'],
  status: ['new', 'open', 'pending', 'resolved', 'closed'],
}

export const NO_VALUE = new Set(['is_empty', 'is_not_empty'])
export const LIST_OPS = new Set(['contains_any', 'in'])

export function operatorLabel(field: FieldName, op: string): string {
  return field === 'assignee' ? (ASSIGNEE_OPERATOR_LABEL[op] ?? op) : (OPERATOR_LABEL[op] ?? op)
}

export function emptyCondition(): Condition {
  return { field: 'subject', operator: 'contains', value: '' }
}

export function emptyDefinition(): RuleDefinition {
  return {
    trigger: { event: 'ticket.created' },
    conditions: { op: 'and', items: [emptyCondition()] },
    actions: [{ type: 'set_priority', value: 'high' }],
  }
}

export function isGroup(item: Condition | Group): item is Group {
  return 'op' in item
}

export const MAX_DEPTH = 3
export const MAX_ACTIONS = 10

/** Value shown/edited for a condition: list values are comma separated text. */
export function valueText(c: Condition): string {
  return Array.isArray(c.value) ? c.value.join(', ') : (c.value ?? '')
}

function conditionPhrase(c: Condition): string {
  const field = FIELD_LABEL[c.field].toLowerCase()
  const op = operatorLabel(c.field, c.operator)
  if (NO_VALUE.has(c.operator)) return `the ${field} ${op}`
  const v = Array.isArray(c.value) ? c.value.map((x) => `“${x}”`).join(', ') : `“${c.value ?? ''}”`
  return `the ${field} ${op} ${v}`
}

function groupPhrase(g: Group, root = true): string {
  if (g.items.length === 0) return 'always'
  const parts = g.items.map((i) => (isGroup(i) ? `(${groupPhrase(i, false)})` : conditionPhrase(i)))
  return parts.join(g.op === 'and' ? ' and ' : ' or ')
    .replace(/^$/, root ? 'always' : '')
}

export interface Names {
  users: Record<string, string>
  teams: Record<string, string>
}

function assignPhrase(s: AssignSpec, names: Names): string {
  return s.target === 'round_robin' ? `assign to the next person in ${names.teams[s.team_id ?? ''] ?? 'a team'}` : `assign to ${names.users[s.user_id ?? ''] ?? 'a teammate'}`
}

export function actionPhrase(a: Action, names: Names): string {
  switch (a.type) {
    case 'assign':
      return assignPhrase(a, names)
    case 'set_priority':
      return `set priority to ${a.value}`
    case 'set_status':
      return `set status to ${a.value}`
    case 'add_tag':
      return `add the tag “${a.tag}”`
    case 'notify':
      return a.target === 'assignee'
        ? 'notify the assignee'
        : a.target === 'owners_admins'
          ? 'notify the owners and admins'
          : a.target === 'team'
            ? `notify ${names.teams[a.team_id ?? ''] ?? 'a team'}`
            : `notify ${names.users[a.user_id ?? ''] ?? 'a teammate'}`
    case 'escalate':
      return `escalate: ${assignPhrase(a.assign, names)} and notify the owners and admins`
  }
}

export function describeDefinition(d: RuleDefinition, names: Names): string {
  const level = d.trigger.level ? ` (${d.trigger.level})` : ''
  const when = `When ${EVENT_PHRASE[d.trigger.event]}${level}`
  const cond = d.conditions.items.length === 0 ? '' : `, and ${groupPhrase(d.conditions)}`
  return `${when}${cond}: ${d.actions.map((a) => actionPhrase(a, names)).join(', ')}.`
}
