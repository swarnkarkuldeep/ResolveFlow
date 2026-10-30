# ResolveFlow — Design Document

Date: 2026-10-30 · Version: v1.0 · Status: **APPROVED by user 2026-10-30**. Next step: implementation plan (superpowers:writing-plans).
Companion: `docs/PRD.md`. Choices you made are marked **(decided)**. Everything else is **my call** and open to veto.

## 1. Intent
A lightweight, opinionated shared support inbox for small service businesses and agencies. Its value is *accountability*: every request has an owner, a deadline, an explanation of that deadline, and automations the admin can test before they go live. It is also a portfolio piece showing production-minded backend engineering: transactional consistency, background job reliability, idempotency, retries, event processing, RBAC, audit logging and efficient queries. **(decided)**

## 2. Goals / non-goals / anti-goals
Goals, non-goals and anti-goals follow PRD §5–7. The anti-goals you set are binding on this design: not a CRUD app in disguise, no unreliable SLA math, no broken tenant isolation, no duplicate notifications, no non-functional rules, no incomplete demo. **(decided)** Also: no dead buttons. **(decided)**

## 3. Constraints
- 6–8 weeks, two developers in parallel via GitHub **(decided)**; Windows 11 primary dev env **(decided)**.
- Free-tier infrastructure only; no Kafka, Kubernetes, microservices or paid services **(decided)**.
- Public demo URL if feasible; local Docker is essential **(decided)**.
- **One-click start with Docker Desktop (decided)**, see §10.

## 4. Stack
| Concern | Choice | Status |
|---|---|---|
| Backend | Python 3.12 + FastAPI, Pydantic v2 | decided |
| Frontend | React + TypeScript (Vite), TanStack Query, Tailwind, Linear-inspired minimal UI | decided (libs are my call) |
| DB | PostgreSQL 16 | decided |
| Background jobs | Celery + Redis (worker + beat) | decided |
| ORM/migrations | SQLAlchemy 2.0 (sync, psycopg 3) + Alembic | my call |
| Search | Postgres full-text (`tsvector` + GIN) | my call |
| Realtime in-app | Server-Sent Events fed by Redis pub/sub | my call |
| Auth | Email+password (argon2), httpOnly session cookie + CSRF | decided method, my call on details |
| Email in | Provider webhook (Postmark inbound is the first adapter) behind an `InboundEmailProvider` interface | decided pattern, provider my call |
| Email out | `OutboundEmailProvider` interface; SMTP→Mailpit locally, Postmark API in prod | my call |
| Tests | pytest (+ testcontainers/real Postgres), Playwright e2e, Vitest for pure UI logic | my call |
| Lint/types | ruff, mypy, ESLint, tsc; GitHub Actions CI | my call |

Modular monolith: one FastAPI codebase, one Celery worker codebase (same package), one SPA. **(decided)**

## 5. Architecture
```
 Provider webhook ─┐
 Web form ─────────┤
 Agent SPA (REST) ─┴► FastAPI: auth → tenant ctx → RBAC → service layer
                              │ ONE DB transaction: domain rows + audit row + outbox row
                              ▼
                  outbox_events ──(relay task, every few sec + on commit hint)──► Celery queues
                                                                                    │
        ┌───────────────┬────────────────┬──────────────────┬──────────────────────┘
   Rules engine     SLA engine     Notification        Search/denorm
        │          (sweeper)        dispatcher           updater
        └─ actions go back through the service layer → new outbox events
 Celery beat: sla_sweeper (1/min), outbox_relay, retention_purge (daily), dlq_report
```
Rationale: the outbox gives atomic "change + event"; Celery gives retries and workers; **the DB, not the queue, is the source of truth for time-based work** (see §7.3).

## 6. Multi-tenancy (decided: from day one, kept simple)
Shared schema, `workspace_id` on every tenant table, composite indexes starting with `workspace_id`. Every request resolves a `TenantContext` (user, workspace, role); repositories *require* it and always filter on it. Defence in depth: PostgreSQL Row-Level Security policies using `SET LOCAL app.workspace_id` per transaction, with an isolation test suite that tries cross-tenant reads/writes on every endpoint. Background tasks carry `workspace_id` explicitly and set the same context.

## 7. Subsystems

### 7.1 Ingestion
`POST /webhooks/email/{provider}` verifies the provider signature/token → adapter normalizes to `InboundMessage` → idempotency on `Message-ID` (unique constraint) → thread match (`In-Reply-To`/`References`, then plus-address token `support+T-1042@…`) → create ticket or append message → outbox event. Web form: public endpoint per workspace with honeypot + rate limit. Duplicate heuristic flags "possible duplicate" with a one-click merge; never auto-merges.
Local inbound: Mailpit only captures *outbound* mail, so locally inbound is exercised by a `scripts/simulate_inbound` CLI plus a dev-only UI button hitting the same webhook with a provider-shaped payload (no separate code path). Outbound mail shows up in Mailpit.

### 7.2 Tickets & assignment
Statuses `new/open/pending/resolved/closed`, priorities `low/normal/high/urgent`, tags, internal notes vs public replies, attachments (local volume in dev, S3-compatible optional later), merge, bulk actions, saved views. Teams: a `team` groups users for assignment targets and round-robin; no hierarchy **(decided: basic teams only)**.

### 7.3 SLA engine (the accuracy-critical part)
- Targets: first-response and resolution per priority **(decided)**; next-response deferred **(decided)**.
- Business hours: per-workspace weekly schedule + IANA timezone **(decided)**. Holidays: a simple list of dates per calendar (all-day closed) **(my call: this is the "simplified" version)**.
- Pure function `compute_due(start, target_minutes, calendar, paused_intervals)`; no I/O; DST-aware; exhaustively fixture-tested.
- Clock state is derived from an append-only `sla_events` stream (`started, paused, resumed, first_response, resolved, reopened, priority_changed, policy_changed`). `ticket_sla` is a rebuildable cache. The ticket page shows an **SLA explainer** built from these events.
- Pause when status = `pending`, resume on customer reply **(decided)**.
- **Escalation scheduling: DB sweeper, not per-ticket ETA tasks (my call).** `ticket_sla` stores `next_check_at` (warn/breach instants). A Celery-beat task each minute selects due rows with `FOR UPDATE SKIP LOCKED`, records an idempotent `sla_threshold_crossed` event (unique on ticket+threshold+version), and emits it. Survives Redis flushes and restarts; no lost timers, no duplicate escalations.

### 7.4 Rules engine
- Definition is validated JSON: trigger (`ticket.created`, `message.received`, `status.changed`, `sla.threshold`), condition tree of AND/OR groups over fixed fields (sender, sender domain, keywords in subject/body, channel, priority, tags, status) **(decided: no regex/custom fields)**, actions (assign user/team/round-robin, set priority, add tag, set status, notify, escalate) **(decided: no auto-replies)**.
- Pure `evaluate(rules, ctx) → plan`. Live mode executes the plan through the normal service layer (audited, evented). Dry-run returns the plan only, with no side effects.
- **Synthetic-ticket tester first (decided):** a form builds a fake ticket context, shows which rules matched, which conditions passed/failed, and the planned actions in order. **Historical replay with before/after diff is a later enhancement (decided)**, but the evaluator is already pure so adding it is cheap.
- Lifecycle `draft → active → archived`, versioned; activation is blocked until the current version has a recorded passing test run (my call); rollback = reactivate prior version. Each ticket has a "why" panel listing executed rules. Loop guard: actions tagged with causing rule/execution id; max chain depth 3.
- Conflict policy (my call): rules run by explicit order; per action type, first match wins except tags (additive).

### 7.5 Notifications (decided: in-app + email; Slack deferred)
`notifications` (intent) → `notification_deliveries` (per channel) with a unique idempotency key (`event_id + recipient + channel`) so retries and redelivered events cannot duplicate. Celery task with exponential backoff, max attempts, then dead-letter status visible to admins with a working "retry" button. In-app via SSE (Redis pub/sub) with catch-up from DB on reconnect. Per-user preferences. Email batching/digest not in v1.

### 7.6 RBAC
Roles Owner/Admin/Agent/Viewer **(decided)** mapped to explicit permissions (`ticket:read`, `ticket:assign`, `rule:activate`, `user:manage`, `audit:read`, …). A single FastAPI dependency enforces permission per route; a table-driven test walks every route × role. Service layer re-checks for non-HTTP callers (tasks run as `system` or a named rule).

### 7.7 Audit log
Written in the *same transaction* as the change. Actor (user / system / rule), action, entity, before/after JSON, request id. Append-only enforced by DB trigger plus revoked UPDATE/DELETE. Filterable, CSV export.

### 7.8 Search
Generated `tsvector` over ticket subject + message bodies + customer name/email, GIN index, `websearch_to_tsquery`, `ts_headline` snippets, filters (status, assignee, tag, priority, date). Tenant filter first in every query; `EXPLAIN`-checked in tests against 50k seeded tickets.

### 7.9 Analytics (basic, decided)
SQL aggregates (no warehouse): SLA compliance %, breaches, avg first-response/resolution, volume by day/priority/channel/agent. Served from indexed queries; no pre-aggregation unless measured slow.

### 7.10 Privacy & retention (decided: basic practices + configurable retention)
Argon2 hashing, input validation on every schema, authorization on every route, rate limits on auth and public endpoints, secrets via env, safe logging (no bodies/PII in logs). Per-workspace retention setting (e.g., delete closed tickets older than N days; off by default); daily purge task that is audited. Synthetic data only in demo.

## 8. UI (decided: clean, minimal, Linear-inspired)
Command-palette (Ctrl/Cmd-K) search, keyboard-first list navigation, dense but calm list/detail layout, light + dark theme. Screens: Login/invite · Inbox (views, filters, bulk) · Ticket detail (thread, reply/note, properties, SLA explainer, why panel, timeline) · Customers · Rules (list, editor, tester) · SLA & business hours · Teams & users · Reports · Audit log · Notifications & delivery log · Channel settings (email, web form) · Workspace settings (retention). Mockups via the visual companion before UI work starts (needs your OK, see questions).

## 9. Reliability & error handling
Idempotent handlers everywhere; transactional outbox; `acks_late` + `reject_on_worker_lost` Celery settings; retry with jittered backoff; DLQ table; sweeper self-heals missing timers; startup reconciliation; graceful shutdown; health/readiness endpoints; an admin "system" page showing queue depth, last sweeper run, outbox lag.

## 10. Local & deployment (decided: one-click Docker; free-tier public demo)
**One click:** a `start.bat` at the project root (double-click) that (1) checks Docker Desktop is running and starts it if not, (2) runs `docker compose up -d --build`, (3) waits for the API health endpoint, (4) runs migrations + seed on first run, (5) opens the browser at `http://localhost:3000` (and prints Mailpit at `:8025`). Plus `stop.bat` and `reset.bat` (wipe volumes). Compose services: `db` (postgres), `redis`, `api`, `worker`, `beat`, `web`, `mailpit`; healthchecks and `depends_on: condition: service_healthy`; named volumes; one `.env.example`.
**Public demo (my call, to verify during M5):** Render or Fly.io free tier + Neon (free Postgres) + a free Redis (Render Key Value / Upstash). Free tiers do not allow separate worker dyno for free, so the demo image runs API + Celery worker + beat in one container via a supervisor process. Cold starts are expected and documented. Mark as risk R1. If a free Redis turns out unreliable for Celery, fallback is the same container with Redis embedded.

## 11. Testing & quality
TDD per superpowers. Pure unit tests for SLA, rules, thread matching. Integration tests on real Postgres + Redis (outbox, sweeper, idempotency, retry, RBAC matrix, tenant isolation incl. RLS). Crash test: kill worker mid-task; restart; assert exactly-once effects. Playwright e2e per UI control. CI on GitHub Actions. Seed script (decided): realistic workspace, users per role, customers, tickets of mixed priority/state with histories, SLA configs, rules.

## 12. Two-developer plan and milestones (decided order)
Dev A = backend/platform, Dev B = frontend/product, swapping on integration points; contract-first via an OpenAPI schema and generated TS client; short-lived branches, PRs with CI required.
- **M0 (days 1–3):** repo, docker compose + one-click scripts, CI, skeletons, OpenAPI client generation.
- **M1 (wk 1–2):** auth, workspaces, memberships/RBAC, tickets, inbox UI, email webhook + web form, audit log, tenant isolation tests.
- **M2 (wk 3–4):** business hours, SLA policies, event-sourced clocks, explainer, sweeper, escalations, pause/resume.
- **M3 (wk 4–5):** rules engine, synthetic tester, versioning, rule-based assignment/teams.
- **M4 (wk 5–6):** notifications (in-app SSE + email, DLQ UI), full-text search, basic analytics.
- **M5 (wk 7–8):** security pass, retention, load/crash tests, deploy demo, docs, polish, seed.
Cut order if late: Slack, advanced analytics, holiday calendar, team round-robin sophistication, then historical replay (already deferred).

## 13. Left to the builder
Exact schema columns/indexes, route naming, component structure, pagination style, seed content, rule tie-breaking within §7.4.

## 14. Builder-check outcomes: calls I made (please skim)
- **Precedence:** this doc wins over the PRD; PRD reconciled to match (cut: inactivity trigger, customer-attribute/business-hours conditions, least-loaded assignment, split-off, quiet hours, Slack, replay).
- **Deferred = absent:** deferred features (Slack, replay, split-off, holidays beyond a date list) do not appear in the UI at all, not even disabled.
- **SSE:** the SSE endpoint is an `async def` handler using async Redis pub/sub; all other routes are sync on the threadpool. Pool sizes tuned accordingly.
- **SLA policies:** one default SLA policy per workspace in v1, with per-priority first-response/resolution targets and a per-policy "business hours only" toggle. A priority change recomputes the deadline from the ticket's original start time minus already-paused time (recorded as `priority_changed`); a schedule edit applies to open tickets from that moment (`policy_changed` event). Multiple policies by customer/tag is future work.
- **DB roles/RLS:** three Postgres roles: `owner` (migrations), `app` (RLS enforced, used by API and tasks tied to a workspace), `system` (BYPASSRLS, used only by the sweeper/outbox relay/retention, which then iterate per workspace and set context). Public endpoints resolve the workspace first from a token, then run as `app` with that context.
- **Webhook → workspace:** each workspace gets a unique inbound address (`inbound-<random-token>@<domain>`); the webhook maps recipient token → workspace and rejects unknown tokens. Never guessed from sender or subject.
- **Rule semantics:** notify/escalate are not subject to first-match-wins (they all fire, deduped by notification idempotency key). Rule-caused status/priority changes can re-trigger rules up to depth 3. Round-robin skips deactivated users and is scoped to the target team.
- **Cross-platform:** `start.bat` plus a `Makefile`/`start.sh` equivalent; CI and demo run on Linux.
- **Scale target:** 50k seeded tickets for search/list performance, demo included.
- **Needs your answer:** inbound email domain for the public demo (see chat).


## 15. Approved clarifications (user, 2026-10-30)
1. **Demo inbound email:** no real inbound on the public demo. Customers use the web form and the "simulate email" button (same webhook code path); outbound email still goes through the provider.
2. **SLA scheduler:** escalation processing is idempotent, concurrency-safe (`FOR UPDATE SKIP LOCKED`) and recoverable after restarts. PostgreSQL is the source of truth for deadlines and escalation state; Redis/Celery only carry work.
3. **Rule tests are version-bound:** a passing test record references the exact `rule_version_id` (and a content hash). Any edit creates a new version with no passing test; activation requires a passing test on that exact version.
4. **Deployment:** API, worker and scheduler may share one demo container but run as logically independent processes (separate entrypoints/supervised processes). After a cold start or restart, missed jobs and escalations recover from DB state (sweeper catches up; outbox relay drains).
5. **Providers:** Postmark sits behind clean `InboundEmailProvider` / `OutboundEmailProvider` interfaces. Local dev needs no paid provider (Mailpit + simulate-inbound).
6. **Scope:** no expansion beyond the agreed MVP.
7. **Frontend:** the `frontend-design` skill will be used when UI work starts (after backend M1 foundations / mockup review).

## 16. Git workflow (user instruction)
Repo initialised and published to GitHub (private by default, can be made public). `main` is protected by convention: work happens on `m<N>-<topic>` branches; at the end of each phase (M0–M5) run the full tests, push the branch, open a PR, merge after CI/tests pass, then push `main`. Conventional commits; frequent pushes.
