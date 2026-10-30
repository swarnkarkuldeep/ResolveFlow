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
