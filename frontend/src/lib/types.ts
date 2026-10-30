export type Role = 'owner' | 'admin' | 'agent' | 'viewer'
export type Status = 'new' | 'open' | 'pending' | 'resolved' | 'closed'
export type Priority = 'low' | 'normal' | 'high' | 'urgent'

export interface Me {
  user: { id: string; email: string; name: string }
  workspaces: { id: string; name: string; slug: string; role: Role }[]
  active_workspace: { id: string; name: string; slug: string; role: Role } | null
  role: Role | null
  permissions: string[]
  csrf_token: string
}

export type SlaState = 'none' | 'running' | 'paused' | 'met' | 'at_risk' | 'breached'

export interface SlaMetric {
  due_at: string | null
  met_at: string | null
  state: SlaState
}

export interface SlaSummary {
  state: SlaState
  next_due_at: string | null
  first_response: SlaMetric
  resolution: SlaMetric
}

export interface SlaExplain {
  policy: {
    enabled: boolean
    business_hours_only: boolean
    priority: Priority
    targets: { first_response_minutes: number; resolution_minutes: number } | null
  }
  calendar: { timezone: string; schedule_text: string; holidays: number }
  state: SlaState
  metrics: {
    key: 'first_response' | 'resolution'
    name: string
    target_minutes: number | null
    due_at: string | null
    met_at: string | null
    state: SlaState
    elapsed_minutes: number | null
    paused_minutes: number
  }[]
  events: { at: string; kind: string; text: string }[]
}

export interface TicketItem {
  id: string
  number: number
  subject: string
  status: Status
  priority: Priority
  channel: 'email' | 'form' | 'manual'
  requester: { id: string; email: string; name: string | null }
  assignee: { id: string; name: string } | null
  tags: string[]
  snippet: string | null
  last_activity_at: string
  created_at: string
  possible_duplicate_of: string | null
  merged_into_id: string | null
  sla?: SlaSummary
}

export interface Message {
  id: string
  kind: 'public' | 'note'
  direction: 'inbound' | 'outbound' | 'internal'
  body: string
  created_at: string
  delivery_status: 'none' | 'queued' | 'sent' | 'failed'
  author: { type: 'user' | 'customer'; name: string }
}

export interface TicketDetail extends TicketItem {
  messages: Message[]
}

export interface TicketPage {
  items: TicketItem[]
  next_cursor: string | null
}

export interface Member {
  user_id: string
  email: string
  name: string
  role: Role
  active: boolean
}

export interface Team {
  id: string
  name: string
  members: { user_id: string; name: string; role: Role; active: boolean }[]
}

export interface Invitation {
  id: string
  email: string
  role: Role
  expires_at: string
  link?: string
}

export interface ActivityEntry {
  action: string
  created_at: string
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  actor_type: string
  actor_name: string | null
}

export interface AuditEntry {
  id: string
  created_at: string
  actor_type: string
  actor_id: string | null
  actor_name: string | null
  action: string
  entity_type: string
  entity_id: string | null
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
}

export interface ChannelSettings {
  inbound_address: string
  form_url: string
  form_snippet: string
  simulate_enabled: boolean
}

export const STATUSES: Status[] = ['new', 'open', 'pending', 'resolved', 'closed']
export const PRIORITIES: Priority[] = ['low', 'normal', 'high', 'urgent']
export const ROLES: Role[] = ['owner', 'admin', 'agent', 'viewer']

export const STATUS_LABEL: Record<Status, string> = {
  new: 'New',
  open: 'Open',
  pending: 'Waiting on customer',
  resolved: 'Resolved',
  closed: 'Closed',
}
export const PRIORITY_LABEL: Record<Priority, string> = {
  low: 'Low',
  normal: 'Normal',
  high: 'High',
  urgent: 'Urgent',
}
export const ROLE_LABEL: Record<Role, string> = {
  owner: 'Owner',
  admin: 'Admin',
  agent: 'Agent',
  viewer: 'Viewer',
}

export interface RuleSummary {
  id: string
  name: string
  position: number
  status: 'draft' | 'active' | 'archived'
  active_version: number | null
  current_version: number
  definition: import('../features/rules/vocab').RuleDefinition
  tested: boolean
  updated_at: string
}

export interface RuleVersionInfo {
  version: number
  content_hash: string
  created_at: string
  author: string | null
  tested: boolean
  active: boolean
}

export interface RuleTestInfo {
  id: string
  version: number
  expectation: 'match' | 'no_match'
  matched: boolean
  passed: boolean
  created_at: string
  author: string | null
}

export interface RuleDetail extends RuleSummary {
  versions: RuleVersionInfo[]
  tests: RuleTestInfo[]
}

export type TraceNode =
  | { kind: 'group'; op: 'and' | 'or'; passed: boolean; children: TraceNode[] }
  | { kind: 'condition'; field: string; operator: string; value: unknown; actual: unknown; passed: boolean }

export interface TestResult {
  matched: boolean
  trigger_matched: boolean
  conditions: TraceNode | null
  actions: { type: string; text: string; status: 'apply' | 'applied' | 'skipped' | 'failed'; reason: string | null }[]
  passed?: boolean
  test_id?: string
  version?: number
}

export interface RuleExecution {
  at: string
  event: string
  rule: { id: string; name: string; version: number }
  matched: boolean
  depth: number
  actions: { type: string; text: string; status: 'applied' | 'skipped' | 'failed'; reason: string | null }[]
}

export interface SearchHit extends TicketItem {
  match: 'subject' | 'message'
  snippet_html: string
  rank: number
}

export type NotificationKind = 'assigned' | 'customer_reply' | 'sla' | 'escalation' | 'rule'

export interface AppNotification {
  id: string
  kind: NotificationKind
  title: string
  body: string | null
  read: boolean
  created_at: string
  ticket: { id: string; number: number } | null
}

export interface NotificationPref {
  kind: NotificationKind
  in_app: boolean
  email: boolean
}

export interface Delivery {
  id: string
  title: string
  kind: NotificationKind
  recipient: string
  attempts: number
  error: string | null
  status: string
  created_at: string
}

export interface Analytics {
  range: { days: number; since: string; timezone: string }
  totals: { created: number; resolved: number; open_now: number }
  sla: {
    first_response: { measured: number; met: number; compliance_pct: number | null }
    resolution: { measured: number; met: number; compliance_pct: number | null }
    breached: number
  }
  averages: { first_response_minutes: number | null; resolution_minutes: number | null }
  by_day: { date: string; created: number; resolved: number }[]
  by_priority: { priority: Priority; count: number }[]
  by_channel: { channel: string; count: number }[]
  by_agent: { agent: string; assigned: number; resolved: number }[]
}

export interface CustomerHistory {
  customer: { id: string; email: string; name: string | null; since: string }
  tickets: TicketItem[]
  stats: { total: number; open: number }
}
