import type { Role } from './types'

const TICKET = [
  'ticket:read',
  'ticket:create',
  'ticket:update',
  'ticket:reply',
  'ticket:assign',
  'ticket:merge',
  'ticket:bulk',
]
const ADMIN = [
  'user:read',
  'user:invite',
  'user:manage',
  'audit:read',
  'settings:read',
  'settings:update',
  'rule:read',
  'rule:manage',
  'team:manage',
]

/** Mirrors backend `permissions.PERMS`; the server remains the authority (see /api/auth/me). */
export function permissionsFor(role: Role | null): string[] {
  switch (role) {
    case 'owner':
    case 'admin':
      return [...TICKET, ...ADMIN].sort()
    case 'agent':
      return [...TICKET, 'user:read'].sort()
    case 'viewer':
      return ['ticket:read', 'user:read']
    default:
      return []
  }
}
