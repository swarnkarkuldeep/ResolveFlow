# M4: Search, Notifications, Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (inline). Ledger at `.superpowers/sdd/2026-10-30-m4-search-notifications-analytics/progress.md`.

**Goal:** Full-text ticket search, in-app + email notifications with reliable delivery and per-user preferences, a basic analytics page, and a customer history page.

**Architecture:** Postgres `tsvector` generated columns + GIN (no new infrastructure). One `notifications/service.py` is the only writer of notifications; it applies per-user preferences, dedupes by key, and marks email delivery `queued`. A DB-driven beat sweeper delivers queued email with attempts/backoff and dead-letters after 5 tries (same pattern as outbound replies). The UI polls the unread count (no SSE: ruling, see below). Analytics are plain SQL aggregates over `tickets` and `ticket_sla`.

**Tech Stack:** unchanged (FastAPI, SQLAlchemy `text()`, Alembic, Celery beat, React/TanStack Query).

**Spec:** `docs/superpowers/specs/2026-10-30-resolveflow-design.md`; PRD FR for search, notifications, analytics, customer history.

## Global Constraints

- Tenant isolation: every new table has `workspace_id`, composite FKs, forced RLS, grants to `rf_app`/`rf_system` like migration 0007.
- No duplicate notifications: dedupe key unique per `(workspace_id, dedupe_key)`; email sent only from a `queued` row, claimed `FOR UPDATE SKIP LOCKED`.
- Delivery survives restarts: state is in Postgres only.
- No new technologies; no regex/custom search syntax beyond `websearch_to_tsquery`.
- Sentence-case copy, accessible controls, no dead buttons.

## Rulings

- In-app delivery is polling (unread count every 20 s, list on open) rather than SSE: same user-visible result, no second transport to keep reliable; recorded cost: up to 20 s latency.
- Email notifications are sent by the beat sweeper (every 30 s), not enqueued from the request transaction, so a rolled-back transaction can never send mail.

## Review Focus

- Searching with punctuation, quotes, empty or very long input never errors; another workspace's tickets never appear.
- A notification created twice for the same event (retry, sweeper re-run) appears once and mails once.
- Email provider down: attempts counted, retried, dead-lettered after 5, visible to admins, retryable; nothing lost or double-sent after a worker restart.
- User turns a kind off: no in-app row and no mail for that kind; defaults documented.
- Analytics on an empty workspace, and with tickets lacking SLA data, return zeros not errors; no cross-tenant counts.
- Viewer/agent cannot read the delivery admin view or analytics.

---

## File Structure

- Create `backend/alembic/versions/0008_search_notifications.py`: `tickets.search_vec`, `messages.search_vec` (generated), GIN indexes; `notifications.email_status/email_attempts/email_last_error/email_sent_at/email_next_at`; `notification_prefs`.
- Create `backend/src/resolveflow/services/search.py`, `api/search.py`.
- Create `backend/src/resolveflow/notifications/{__init__,service,delivery}.py`, `api/notifications.py`, `tasks/notifications.py`.
- Create `backend/src/resolveflow/services/analytics.py`, `api/analytics.py`, `api/customers.py`.
- Modify hooks: `services/tickets.py` (assigned), `services/ingest.py` (customer reply), `sla/sweeper.py` (sla), `rules/notify.py` (route through service), `celery_app.py` (beat), `permissions.py` (`analytics:read`, `notification:admin`), `main.py`, `seed.py`.
- Frontend: `features/search/*`, `features/notifications/*` (Bell, NotificationsPage with preferences + delivery), `features/analytics/AnalyticsPage.tsx`, `features/customers/CustomerPage.tsx`, `app/Shell.tsx`, `app/router.tsx`, `lib/types.ts`, `lib/permissions.ts`; e2e `search.spec.ts`, `notifications.spec.ts`, `analytics.spec.ts`.

---

### Task 1: Search

**Interfaces:** Produces `GET /api/search?q=&status=&priority=&assignee=&tag=&limit=` → `{items:[{...ticket item, snippet_html?: str, match: "subject"|"message", rank: float}]}`; `search.search_tickets(ctx, q, *, statuses, priorities, assignee, tag, me, limit)`.

- [ ] Migration 0008 search parts: `ALTER TABLE tickets ADD COLUMN search_vec tsvector GENERATED ALWAYS AS (to_tsvector('english', subject)) STORED`; same on `messages` over `body`; GIN indexes.
- [ ] Tests (`tests/test_search.py`): finds by subject word and by message body word; ranks subject hit above body-only hit; `ts_headline` snippet marks matches with `<mark>` after escaping other HTML; quotes/punctuation/emoji/500-char query/empty query (422 for empty or whitespace) never 500; filters combine; other workspace's ticket never returned; viewer can search; limit capped at 50.
- [ ] Implement with `websearch_to_tsquery('english', :q)`; match tickets whose vec matches OR having a message whose vec matches; rank = max(ts_rank); snippet from best matching message else subject; escape HTML in headline source by selecting text then escaping `<`,`>`,`&` before headline using custom `StartSel`/`StopSel` of private tokens replaced by `<mark>` after escaping.
- [ ] Run tests; commit.

### Task 2: Notification core, preferences, in-app API

**Interfaces:** Produces `notifications.service.notify(ctx, user_ids, kind, ticket_id, title, body, dedupe_key) -> int` (kinds: `assigned`, `customer_reply`, `sla`, `escalation`, `rule`); `GET /api/notifications?unread=&limit=` → items; `GET /api/notifications/unread-count`; `POST /api/notifications/{id}/read`; `POST /api/notifications/read-all`; `GET/PUT /api/notification-prefs` (`[{kind,in_app,email}]`, defaults in_app true for all, email true for `sla`,`escalation` only).

- [ ] Tests (`tests/test_notifications.py`): assigning a ticket to someone else notifies them once, assigning to self does not; customer inbound reply notifies the assignee once (replay of same Message-ID → still one); SLA threshold notifies assignee, or owners/admins when unassigned; each at most once across repeated sweeps; rule notify/escalate go through prefs; pref `in_app=false` suppresses the row; mark read / read-all only affect own rows; another user cannot read or mark my notifications (404); prefs round-trip and reject unknown kinds.
- [ ] Implement service (insert `on conflict do nothing` on dedupe key; when `email` pref on set `email_status='queued', email_next_at=now()`, else `'none'`); hook the four call sites; route `rules/notify.create_intents` through `notify`.
- [ ] Run tests; commit.

### Task 3: Email delivery, retries, dead letters

**Interfaces:** Produces `delivery.deliver_due(limit) -> int`, beat task `resolveflow.tasks.notifications.deliver` every 30 s; `GET /api/notification-deliveries?status=failed|dead` and `POST /api/notification-deliveries/{id}/retry` (perm `notification:admin`, owner/admin).

- [ ] Tests (`tests/test_notification_delivery.py`, `MemoryProvider` and a failing provider): queued row is sent exactly once even when `deliver_due` runs twice concurrently/repeatedly; failure increments attempts, sets `email_next_at` with backoff (1, 5, 15, 60 min), keeps `queued`; 5th failure → `dead` with `email_last_error`; admin lists dead ones, retry resets to `queued` attempts 0; agent gets 403; rows from other workspaces not listed; a recipient who is deactivated is marked `skipped` not sent; mail body contains ticket link and subject without header injection (`clean_line`).
- [ ] Implement with `FOR UPDATE SKIP LOCKED`, system engine, per-row savepoint; register beat.
- [ ] Run tests; commit.

### Task 4: Analytics and customer history APIs

**Interfaces:** `GET /api/analytics?days=7|30|90` (perm `analytics:read`: owner/admin) → `{range, totals:{created,resolved,open_now}, sla:{first_response:{measured,met,compliance_pct}, resolution:{...}, breached}, averages:{first_response_minutes,resolution_minutes}, by_day:[{date,created,resolved}], by_priority:[{priority,count}], by_channel:[{channel,count}], by_agent:[{agent,assigned,resolved}]}`; `GET /api/customers/{id}` → `{customer, tickets:[item], stats}` (perm `ticket:read`).

- [ ] Tests (`tests/test_analytics.py`): hand-built tickets/`ticket_sla` rows give exact counts, compliance percentages and averages; empty workspace gives zeros and null averages; days outside range excluded; invalid `days` → 422; other workspace excluded; agent/viewer 403; customer history lists all the customer's tickets newest first with counts, other workspace's customer 404.
- [ ] Implement aggregates in SQL (`date_trunc('day', ...)` in the workspace calendar timezone); averages over `fr_met_at - start_at` and `res_met_at - start_at` wall-clock minutes.
- [ ] Run tests; commit.

### Task 5: Frontend search and notifications

- [ ] Tests (Vitest): search box in inbox header debounces, shows results with `<mark>` highlights, "No tickets match" empty state, clears back to queue; bell shows unread count, opens panel, clicking an item marks it read and opens the ticket, "Mark all read" works; preferences toggles save; delivery list shows dead items to admins with working Retry and is absent for agents.
- [ ] Implement `features/search`, `features/notifications` (Bell in Shell with 20 s polling, NotificationsPage at `/notifications` with preferences and, for admins, delivery problems).
- [ ] Run vitest/oxlint/tsc; commit.

### Task 6: Frontend analytics and customer page

- [ ] Tests: analytics page renders numbers from the API, range switcher refetches, empty state, hidden from agents; customer page lists history with link from the ticket's requester.
- [ ] Implement `/analytics` (clean figures and simple SVG bars, no chart library) and `/customers/:id`.
- [ ] Run tests; commit.

### Task 7: Seed, e2e, review, close

- [ ] Seed: some resolved tickets with SLA data so analytics are non-empty; notification prefs left default; a couple of notifications for the demo agent.
- [ ] e2e: search finds a ticket by message text; assigning a ticket produces a bell notification for the assignee (second context) that opens the ticket; prefs toggle persists; analytics page shows counts after creating a ticket; customer page reachable.
- [ ] Full verification (backend suite/ruff/mypy, frontend vitest/oxlint/tsc/build, e2e); independent Opus whole-branch review vs Review Focus; fix Critical/Important RED→GREEN; push, CI green, PR, squash-merge, tag `m4-complete`.
