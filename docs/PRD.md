# ResolveFlow — Product Requirements Document

Status: DRAFT v0.3 (reconciled with design doc, which wins on conflicts) (2026-10-30). Your 24 product decisions are folded in. Items marked **[ASSUMPTION]** are still my guesses.

## 1. Problem
Small service businesses get complaints and requests through email, web forms and messaging channels. Requests get missed, duplicated or left unanswered because nobody owns the inbox, nobody knows what's overdue, and history is scattered across personal mailboxes.

## 2. Product
ResolveFlow is an opinionated, lightweight shared support inbox for small teams (2–15 people). It turns every inbound message into a ticket with an owner, a priority and a response-time target, and escalates automatically when a target is about to be missed.

## 3. Differentiators
1. **Transparent SLA tracking.** Every ticket shows its deadline, the clock state (running/paused), and *why* (which policy, which business hours, which rule set the priority). No black box.
2. **Testable rules.** Assignment/priority/escalation rules are authored as drafts, tested against a synthetic ticket (showing which rules match and what they would do), then activated. Rules are versioned and roll-back-able.
3. **Opinionated and small.** One way to do things. No 200-field admin panel.

## 4. Target users
- **Primary customers:** small agencies, service providers, online stores, software startups (2–15 support-handling people).
- **Personas**
  - *Owner/Admin* — configures channels, SLA policies, rules, users; wants to know "are we meeting our promises?"
  - *Agent* — works tickets; wants a clear queue, "what's due next", fast search.
  - *Viewer/Stakeholder* — read-only access to tickets and reports.
  - *Customer* — emails in or submits a form; receives replies by email. (No customer portal in v1.)

## 5. Goals
- G1: No inbound request is lost or duplicated; every ticket has an owner or sits in a visible unassigned queue.
- G2: Every ticket has first-response and resolution targets; breaches are predicted and alerted *before* they happen.
- G3: Admins can test a rule change safely before it affects live tickets.
- G4: Full searchable history across tickets, comments, customers.
- G5: Everything in the UI works against the real backend. **No mock features, no dead buttons.**

## 6. Non-goals (v1)
- WhatsApp, Slack inbound, live chat, voice/phone, social DMs (email + web form only in v1)
- Customer portal / knowledge base (customers get email only)
- AI auto-replies / AI classification
- Billing, plans, payments, multi-region
- Native mobile apps (responsive web only)
- Per-field custom ticket schemas, marketplace/integrations

## 7. Anti-goals (failure even if it "works")
- A feature visible in the UI that isn't wired to real behavior.
- Rules that silently change tickets without an audit trail.
- SLA numbers a user can't explain or reproduce by hand.
- Duplicate notifications or missed escalations because of retries/restarts.
- Becoming a configurable-everything helpdesk.

## 8. Functional requirements

### 8.1 Channels & ingestion
- FR-1 Inbound email → ticket (new) or comment on existing ticket (matched by reply headers `In-Reply-To`/`References` and a ticket token in the subject/address).
- FR-2 Public web form per workspace (embeddable + hosted page) → ticket. Spam protection (honeypot + rate limit).
- FR-3 Manual ticket creation by agents (e.g., from a phone call).
- FR-4 Duplicate detection: same message-id ignored; same sender + near-identical subject within a window flagged as "possible duplicate" with one-click merge.
- FR-5 Outbound replies by email from the app, threaded correctly.

### 8.2 Tickets
- FR-6 Fields: subject, requester (customer record), status (`new`, `open`, `pending` [waiting on customer], `resolved`, `closed`), priority (`low`, `normal`, `high`, `urgent`), assignee, tags, channel, timestamps.
- FR-7 Conversation thread: public replies + internal notes; attachments.
- FR-8 Assignment: manual, claim-from-queue, and rule-based (round-robin within a team / specific user or team).
- FR-9 Merge, bulk actions (assign, priority, status, tag).
- FR-10 Saved views / filters (My tickets, Unassigned, Breaching soon, Breached).

### 8.3 SLA
- FR-11 SLA policies with targets per priority: first-response time and resolution time.
- FR-12 Business-hours calendars with weekly schedule and IANA timezone; simple holiday date list (simplified); clock counts only business time if the policy says so. Next-response SLA deferred.
- FR-13 Clock states: running, paused (while `pending`), stopped (met), breached. State changes are recorded as events so the number is reproducible.
- FR-14 Ticket page shows an "SLA explainer": policy applied, targets, elapsed/paused time, due time, and event timeline.
- FR-15 SLA report: compliance %, breaches, avg first response / resolution, by agent/priority/channel/period.

### 8.4 Rules engine (differentiator)
- FR-16 Rule = trigger event + conditions + actions. Triggers: ticket created, message received, status changed, SLA threshold reached (e.g., 75%, 100%).
- FR-17 Conditions: sender/domain, subject/body keywords, channel, priority, tag, status.
- FR-18 Actions: set priority, assign, add tag, change status, notify (user/team, in-app + email), escalate (reassign to a chosen user/team + notify Owners/Admins).
- FR-19 Lifecycle: `draft → active → archived` (activation requires a passing test on the current version); versioned; one-click rollback.
- FR-20 **Test before activate:** run a draft against a synthetic ticket built in a form; show which rules matched, which conditions passed/failed and the planned actions; no side effects. Activation requires a recorded passing test on the current version. *Later enhancement:* replay against historical tickets with a before/after diff.
- FR-21 Rule ordering and conflict display (which rule won and why) on each ticket's "why" panel.

### 8.5 Escalation & notifications
- FR-22 Scheduled escalations: warning before breach, alert at breach, optional second-level escalation.
- FR-23 Channels: in-app (live) and email. Slack webhook optional/later. No SMS or push.
- FR-24 Reliable delivery: at-least-once with idempotent dedupe, retries with backoff, delivery status visible, dead-letter view for admins.
- FR-25 Per-user notification preferences.

### 8.6 Access control & audit
- FR-26 Multiple workspaces from day one with isolated data (app-layer filtering + Postgres RLS). Roles: Owner, Admin, Agent, Viewer; basic teams for assignment, no custom roles or hierarchies. Permissions are explicit and enforced server-side on every endpoint.
- FR-27 Invitations by email; deactivate users (tickets are reassigned or surfaced).
- FR-28 Append-only audit log: who/what/when/before→after for tickets, rules, SLA policies, users, roles, settings. Filterable and exportable (CSV).

### 8.7 Search & history
- FR-29 Full-text search across subject, message bodies, notes, customer name/email, with filters (status, assignee, date, tag, priority) and highlighted snippets.
- FR-30 Customer page: all tickets and history for that requester.

## 9. Non-functional requirements
- NFR-1 Reliability: no lost events on crash/restart; scheduled jobs survive restarts.
- NFR-2 Security: hashed passwords (argon2), sessions with CSRF protection, tenant isolation at the query layer, rate limiting, secrets via env.
- NFR-3 Performance: search < 300 ms p95 at 50k seeded tickets; inbox list < 200 ms.
- NFR-4 Observability: structured logs, health endpoint, job/queue metrics page for admins.
- NFR-5 Testability: automated unit, integration (real Postgres) and a handful of end-to-end tests; the rules engine and SLA calculator are pure and exhaustively unit-tested.
- NFR-6 **One-click local start** on Windows with Docker Desktop (`start.bat`: starts Docker if needed, builds, migrates, seeds, opens the browser). Public free-tier demo URL if feasible.
- NFR-7 Privacy: argon2, input validation, authz on every route, PII-safe logs, per-workspace configurable data retention; synthetic demo data; no formal compliance.
- NFR-8 Stack: Python/FastAPI, React+TS, PostgreSQL, Redis+Celery; modular monolith; no Kafka/K8s/paid infra.

## 10. Success metrics
- 0 tickets lost across a restart test and duplicated-delivery test.
- SLA calculation matches hand-computed fixtures across business-hours, holidays, pause/resume.
- A synthetic rule test returns matched rules, per-condition results and planned actions in < 1 s with zero side effects.
- Every button/route in the UI has an automated test hitting the real API.

## 11. Milestones (6–8 weeks, two developers)
- **M0 (days 1–3):** repo, Docker one-click, CI, skeletons.
- **M1:** auth, workspaces, inbox and ticket management, email webhook + web form, audit log.
- **M2:** SLA engine, business hours, escalation workflows.
- **M3:** automation rules and synthetic rule testing.
- **M4:** full-text search, notifications, basic analytics.
- **M5:** testing, security, deployment, documentation, polish.
Priority if short on time: core inbox, SLA accuracy, rule testing, reliable background jobs. Cut optional integrations and advanced analytics first.

## 12. Open questions
See design doc §14; answered items are recorded as decisions above.
