# Architecture

ResolveFlow is a modular monolith. One Python codebase is started three ways (API, worker, scheduler), all talking to one PostgreSQL database.

```
browser -> web (nginx, static React app) -> /api -> api (FastAPI)
                                                      |
                     worker (Celery)  <-- Redis --  beat (scheduler)
                          |                              |
                          +---------- PostgreSQL <-------+      mailpit (SMTP sink)
```

## Principles

- **PostgreSQL is the source of truth.** Redis only wakes workers up. Every job (email delivery, SLA checks, retention, notification mail) is a row with a state, so a restart, a lost message or a duplicate task can never lose or repeat work.
- **Tenant isolation in the database.** Every tenant table has `workspace_id`, composite foreign keys `(id, workspace_id)` and forced row-level security. The API connects as `rf_app` (RLS enforced, cannot read password hashes). Only trusted system flows (scheduler, inbound ingest, login lookup) use `rf_system`.
- **Pure engines, thin services.** Business rules live in pure modules with no database access (`sla/engine.py`, `rules/engine.py`), covered by direct unit tests. Services call them and persist the results.
- **Everything is audited.** Changes write an append-only `audit_log` row in the same transaction, naming the actor: a user, the system, or a rule.

## Modules (`backend/src/resolveflow`)

| Module | Responsibility |
| --- | --- |
| `api/` | HTTP routes, request context, permission checks |
| `services/` | tickets, messages, inbound ingest, members, auth, search, analytics |
| `email/` | provider interfaces (SMTP, Postmark, in-memory) and threading |
| `sla/` | calendar maths, event-sourced clocks, restart-safe sweeper |
| `rules/` | rule schema, evaluator, tester, executor, teams |
| `notifications/` | one creator with preferences and dedupe, email delivery |
| `retention.py` | redaction of expired finished tickets |

## Key designs

**SLA clocks.** `sla_events` is append-only (started, paused, resumed, first response, resolved, threshold...). The `ticket_sla` row is a rebuildable cache of what those events imply. The sweeper claims due tickets with `FOR UPDATE SKIP LOCKED`, records each threshold once through a dedupe key, and parks a ticket that fails instead of blocking the rest. It runs every minute and immediately when the worker starts.

**Rules.** A rule is a versioned, immutable definition. A test records the content hash of the exact version it ran against; activation needs a passing positive test for that hash. When a rule triggers a ticket change, further rules may fire, up to depth 3 and once per rule per ticket. Actions are applied as the rule (audited), each inside a savepoint, so a failing action is recorded in the ticket's "why" panel and never breaks the change that triggered it.

**Email.** Outbound and inbound sit behind provider interfaces. Outbound replies are queue rows retried from the database. Inbound is idempotent by `Message-ID` and threads by `In-Reply-To`/`References`, then by a per-workspace plus-address.

**Notifications.** Only `notifications/service.py` creates them. Each has a dedupe key, so the same event notifies once. Email is leased in a short transaction, sent with no transaction open, and each result committed alone, so a crash re-sends at most the one message in flight.

## Frontend

React with TanStack Query for server state and React Router. No global client store. Permissions are mirrored from the server for display only; the server is the authority.
