# API reference

Generated from the running application's OpenAPI schema by `scripts/gen_api_doc.py`. While the stack is running, the same schema with request and response shapes is served at `http://localhost:8000/openapi.json`.

## Conventions

- **Authentication.** Sign in with `POST /api/auth/login`. The response sets an HTTP-only `rf_session` cookie and returns a `csrf_token`. Send it as the `X-CSRF-Token` header on every `POST`, `PUT`, `PATCH` and `DELETE`.
- **Errors.** `{"detail": {"code": "...", "message": "..."}}` with a plain-language message. Validation errors use the standard `detail` list.
- **Permissions.** Each endpoint requires a permission (for example `ticket:read`, `rule:manage`, `analytics:read`). Owners and admins have all of them, agents work with tickets, viewers read. See [the user guide](USER_GUIDE.md#roles-and-permissions).
- **Tenancy.** Every request runs inside the caller's workspace. Another workspace's ids return `404`.
- **Pagination.** Ticket lists use an opaque `cursor` and return `next_cursor`.

## Authentication and account

| Method | Path | What it does |
| --- | --- | --- |
| `POST` | `/api/auth/accept-invite` | Accept |
| `POST` | `/api/auth/login` | Login |
| `POST` | `/api/auth/logout` | Logout |
| `GET` | `/api/auth/me` | Me |
| `POST` | `/api/auth/signup` | Signup |

## Tickets and messages

| Method | Path | What it does |
| --- | --- | --- |
| `GET` | `/api/customers/{customer_id}` | Customer History |
| `GET` | `/api/search` | Search |
| `GET` | `/api/tickets` | List Tickets |
| `POST` | `/api/tickets` | Create Ticket |
| `POST` | `/api/tickets/bulk` | Bulk |
| `GET` | `/api/tickets/{ticket_id}` | Get Ticket |
| `PATCH` | `/api/tickets/{ticket_id}` | Patch Ticket |
| `GET` | `/api/tickets/{ticket_id}/activity` | Activity |
| `POST` | `/api/tickets/{ticket_id}/merge` | Merge Ticket |
| `POST` | `/api/tickets/{ticket_id}/messages` | Add Message |
| `GET` | `/api/tickets/{ticket_id}/rules` | Ticket Rules |
| `GET` | `/api/tickets/{ticket_id}/sla` | Ticket Sla |

## Public form and email webhooks

| Method | Path | What it does |
| --- | --- | --- |
| `POST` | `/api/dev/simulate-inbound` | Feeds a provider-shaped payload through the same handler as the real webhook. |
| `GET` | `/api/public/forms/{slug}` | Form Info |
| `POST` | `/api/public/forms/{slug}` | Submit Form |
| `POST` | `/api/webhooks/email/postmark` | Postmark Webhook |

## Service levels

| Method | Path | What it does |
| --- | --- | --- |
| `GET` | `/api/settings/sla` | Get Sla Settings |
| `PUT` | `/api/settings/sla` | Put Sla Settings |

## Automations and teams

| Method | Path | What it does |
| --- | --- | --- |
| `GET` | `/api/rules` | List Rules |
| `POST` | `/api/rules` | Create Rule |
| `POST` | `/api/rules/reorder` | Reorder |
| `POST` | `/api/rules/test` | Evaluates a draft against a synthetic ticket. Writes nothing. |
| `GET` | `/api/rules/{rule_id}` | Get Rule |
| `PUT` | `/api/rules/{rule_id}` | Update Rule |
| `POST` | `/api/rules/{rule_id}/activate` | Activate |
| `POST` | `/api/rules/{rule_id}/archive` | Archive |
| `POST` | `/api/rules/{rule_id}/restore` | Restore |
| `POST` | `/api/rules/{rule_id}/tests` | Record Test |
| `GET` | `/api/teams` | List Teams |
| `POST` | `/api/teams` | Create Team |
| `DELETE` | `/api/teams/{team_id}` | Delete Team |
| `PATCH` | `/api/teams/{team_id}` | Rename Team |
| `PUT` | `/api/teams/{team_id}/members` | Set Members |

## Notifications

| Method | Path | What it does |
| --- | --- | --- |
| `GET` | `/api/notification-deliveries` | List Deliveries |
| `POST` | `/api/notification-deliveries/{notification_id}/retry` | Retry |
| `GET` | `/api/notification-prefs` | Get Prefs |
| `PUT` | `/api/notification-prefs` | Put Prefs |
| `GET` | `/api/notifications` | List Notifications |
| `POST` | `/api/notifications/read-all` | Read All |
| `GET` | `/api/notifications/unread-count` | Unread Count |
| `POST` | `/api/notifications/{notification_id}/read` | Mark Read |

## Analytics

| Method | Path | What it does |
| --- | --- | --- |
| `GET` | `/api/analytics` | Analytics |

## Settings, people and audit

| Method | Path | What it does |
| --- | --- | --- |
| `GET` | `/api/audit` | List Audit |
| `GET` | `/api/audit.csv` | Export Csv |
| `GET` | `/api/invitations` | Invitations |
| `POST` | `/api/invitations` | Invite |
| `DELETE` | `/api/invitations/{invitation_id}` | Revoke |
| `GET` | `/api/members` | Members |
| `PATCH` | `/api/members/{user_id}` | Patch Member |
| `GET` | `/api/settings/channels` | Channel Settings |
| `GET` | `/api/settings/privacy` | Get Privacy |
| `PUT` | `/api/settings/privacy` | Put Privacy |
| `POST` | `/api/settings/privacy/apply` | Apply Privacy |
| `POST` | `/api/workspaces/switch` | Switch |

## Health

| Method | Path | What it does |
| --- | --- | --- |
| `GET` | `/api/health/live` | Live |
| `GET` | `/api/health/ready` | Ready |
| `GET` | `/api/health/system` | Informational: always 200; readiness does not depend on the scheduler. |
