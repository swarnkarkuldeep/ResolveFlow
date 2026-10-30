# M1 Core Inbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (chosen by user) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. Frontend tasks (T12–T16) must also follow `frontend-design:frontend-design` and the Design Language below.

**Goal:** A working multi-tenant support inbox: sign up, invite teammates, receive email/web-form requests as tickets, triage, reply, merge, bulk-act, with RBAC, Postgres RLS tenant isolation, audit log, demo seed data and an aesthetic keyboard-first UI.

**Architecture:** Extends the M0 modular monolith. Request → cookie session auth → tenant context (`SET LOCAL app.workspace_id`) → permission check → service layer → one DB transaction containing domain rows **and** audit rows. Outbound email is a queued row processed by a Celery task with a beat sweeper that re-queues stuck rows (recoverable). Inbound email enters via a provider adapter behind an interface; a dev/demo "simulate email" endpoint feeds the same ingestion function.

**Tech Stack:** M0 stack + argon2-cffi, python-multipart; React Router, lucide-react, @fontsource-variable (Hanken Grotesk, Newsreader), Playwright (e2e). No new infrastructure.

**Spec:** `docs/superpowers/specs/2026-10-30-resolveflow-design.md` (§6 tenancy, §7.1 ingestion, §7.2 tickets, §7.6 RBAC, §7.7 audit, §7.10 privacy, §8 UI, §12 M1) and `docs/PRD.md` FR-1..FR-10, FR-26..28, NFR-2.

## Global Constraints

- Python 3.12 / FastAPI / SQLAlchemy 2 sync / Alembic; React + TS; Postgres 16; Redis + Celery. No new infrastructure, no Kafka/K8s/paid services.
- Roles: Owner, Admin, Agent, Viewer only (no custom roles). Ticket statuses `new|open|pending|resolved|closed`; priorities `low|normal|high|urgent`.
- Every tenant table has `workspace_id` + RLS policy; API/tasks connect as non-superuser role `rf_app`; migrations as owner. A query never relies on app-layer filtering alone.
- Passwords argon2id; sessions are server-side rows (random 32-byte token, only SHA-256 stored), httpOnly + SameSite=Lax cookie `rf_session`; unsafe methods require header `X-CSRF-Token`. Login rate limit: 10 attempts / 15 min per (IP, email) via Redis.
- Audit row written in the **same transaction** as the change; `audit_log` is append-only (trigger blocks UPDATE/DELETE).
- Message bodies are plain text, always rendered as text (never `dangerouslySetInnerHTML`).
- Providers behind interfaces: `InboundEmailProvider` (Postmark adapter) and `OutboundEmailProvider` (SMTP→Mailpit default, Postmark API). Local dev needs no paid provider.
- No auto-replies, no Slack, no holidays, no SLA (M2), no search (M4), no customer portal. Deferred features never appear in the UI.
- UI: no mock data or dead controls; every control calls the real API.
- Branch `m1-core-inbox`; Conventional Commits; push per task; PR + merge + tag `m1-complete` after full verification.

## Design Language (binding for T12–T16)

- Palette tokens (light / dark): fog `#F2F4F6` / `#0E141A`, paper `#FFFFFF` / `#151D25`, ink `#16212B` / `#E7ECF1`, slate `#5C6B79` / `#93A1AE`, line `#DDE3E9` / `#263340`, accent harbor `#0F766E` / `#2DD4BF`. Status/priority colours are muted and appear only as small markers. No gradients, no drop-shadow stacks, radii 6px (controls) / 10px (panels), never all-rounded-everything.
- Type: Hanken Grotesk (UI) + Newsreader (message bodies, ticket subject in detail). Sentence case everywhere; no all-caps labels or eyebrows; tabular numerals for ticket numbers/times. Line length < 75ch in threads.
- Layout: three zones: 56px nav rail, queue (resizable-free fixed 420px, collapses on mobile), ticket pane. Keyboard: `j/k` move, `Enter` open, `x` select, `e` resolve, `a` assign to me, `r` reply, `/` focus filter, `?` shortcuts. Visible focus rings; `prefers-reduced-motion` respected.
- Motion only in response to actions (pane open, toast, row removal). No page-load orchestration.
- Copy: plain verbs ("Send reply", "Add note", "Invite teammate"); errors say what happened and what to do; empty states point to the next action.

## Review Focus

- Guessing another workspace's ticket/user/invite id → 404 (not 403, not data), for every id-taking route.
- Same inbound `Message-ID` delivered twice (and concurrently) → exactly one ticket/message.
- Unsafe request without CSRF header → 403; logout/deactivation invalidates server sessions immediately.
- Demoting/deactivating the last Owner is rejected; a deactivated user cannot act with an old cookie.
- Odd inbound payloads: no subject, HTML-only body, oversize/many attachments, unknown recipient token (→ 200 `ignored`, logged), bad webhook auth (→ 401); script tags in a body are displayed as inert text.

---

## File Structure

```
backend/src/resolveflow/
  config.py db.py tenancy.py security.py permissions.py audit.py
  email/{__init__,outbound,inbound,postmark,threading}.py
  services/{auth,members,tickets,messages,ingest,forms}.py
  api/{deps,auth,members,tickets,audit,settings,webhooks,public}.py
  tasks/{email,seed_hooks}.py   seed.py
backend/alembic/versions/{0002_roles_and_core_schema,0003_...}.py
backend/tests/{test_rls.py,test_auth.py,test_rbac.py,test_tickets.py,test_messages.py,test_ingest.py,test_forms.py,test_audit.py,test_seed.py,test_isolation_matrix.py}
frontend/src/{design/{tokens.css,fonts.ts},app/{shell,router,auth}.tsx, features/{inbox,ticket,people,channels,audit,newticket,publicform}/*, lib/{api.ts,keys.ts}}
frontend/e2e/*.spec.ts   frontend/playwright.config.ts
```

### Task 1: Settings, DB roles and tenant context

**Files:** Modify `config.py`, `db.py`; Create `tenancy.py`, `alembic/versions/0002_roles_and_core_schema.py` (roles part; schema in T2), `tests/test_rls.py`; Modify `docker-compose.yml` (api/worker/beat `APP_DATABASE_URL`), `.env.example`.

**Interfaces:**
- Settings add: `app_database_url: str | None`, `app_db_password: str = "rf_app_dev"`, `public_base_url`, `inbound_domain`, `email_provider: Literal["smtp","postmark","memory"]="smtp"`, `mail_from`, `postmark_server_token: str|None`, `postmark_webhook_secret: str|None`, `seed_demo: bool=False`, `simulate_inbound_enabled: bool=False`, `cookie_secure: bool=False`.
- `db.app_engine() -> Engine` (uses `app_database_url or database_url`); `tenancy.tenant_session(workspace_id: UUID | None, user_id: UUID | None) -> Iterator[Session]` — one transaction, executes `select set_config('app.workspace_id', :w, true), set_config('app.user_id', :u, true)`; commits on success, rolls back on error.
- Migration creates roles idempotently: `rf_app` (LOGIN, NOSUPERUSER, NOBYPASSRLS, password from settings) and `rf_system` (LOGIN, BYPASSRLS) used only by beat/sweepers; grants set in T2.

- [ ] **Step 1: Write failing tests** `test_rls.py::test_app_role_is_not_superuser_and_cannot_bypass_rls` (query `pg_roles`: `rolsuper` and `rolbypassrls` both false for `rf_app`, `rolbypassrls` true for `rf_system`); `::test_tenant_session_sets_and_scopes_context` (inside `tenant_session(w,u)`, `current_setting('app.workspace_id')==str(w)`; after exit a new session sees empty setting).
- [ ] **Step 2: Run** `cd backend && pytest tests/test_rls.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** settings, `db.app_engine`, `tenancy.tenant_session`, roles in migration 0002 (`DO $$ … IF NOT EXISTS …`), compose env (api/worker use `APP_DATABASE_URL=postgresql+psycopg://rf_app:${APP_DB_PASSWORD:-rf_app_dev}@db:5432/…`; beat uses `rf_system` URL via `SYSTEM_DATABASE_URL` setting added likewise).
- [ ] **Step 4: Run** `pytest -q && ruff check . && mypy src alembic`. Expected: pass.
- [ ] **Step 5: Commit** `feat(backend): rf_app/rf_system roles and tenant session context`.

### Task 2: Core schema, RLS policies, audit table

**Files:** Modify `alembic/versions/0002_roles_and_core_schema.py` (split a `0003_core_schema.py` if cleaner); Create `tests/test_isolation_matrix.py` (table-level part).

**Interfaces — tables** (UUID PKs `gen_random_uuid()`, `created_at timestamptz default now()`): `users(email citext unique, name, password_hash, active)`, `sessions(token_hash unique, user_id, workspace_id null, csrf_token, expires_at, revoked_at)`, `workspaces(slug unique, name, inbound_token unique, next_ticket_number int default 1)`, `memberships(workspace_id, user_id, role check in owner|admin|agent|viewer, active; unique(workspace_id,user_id))`, `invitations(workspace_id, email, role, token_hash unique, invited_by, expires_at, accepted_at)`, `customers(workspace_id, email citext, name; unique(workspace_id,email))`, `tickets(workspace_id, number, subject, status, priority, channel check in email|form|manual, requester_id→customers, assignee_id null→users, merged_into_id null, possible_duplicate_of null, last_activity_at; unique(workspace_id,number))`, `messages(workspace_id, ticket_id, kind check in public|note, direction check in inbound|outbound|internal, author_user_id null, author_customer_id null, body text, message_id text null, in_reply_to text null, delivery_status check in none|queued|sent|failed, delivery_attempts int, unique(workspace_id,message_id) where message_id is not null)`, `tags(workspace_id,name unique per ws)`, `ticket_tags(ticket_id,tag_id)`, `audit_log(workspace_id, actor_type check in user|system|rule, actor_id null, action, entity_type, entity_id, before jsonb, after jsonb, request_id, created_at)`. Indexes: `tickets(workspace_id,status,last_activity_at desc)`, `tickets(workspace_id,assignee_id)`, `messages(ticket_id,created_at)`, `audit_log(workspace_id,created_at desc)`.
- RLS enabled + forced on every table with `workspace_id` using `workspace_id = nullif(current_setting('app.workspace_id', true),'')::uuid`; `memberships` and `workspaces` policies additionally allow rows where the user is a member (`user_id = nullif(current_setting('app.user_id',true),'')::uuid`). `users`, `sessions` are not tenant-scoped (granted to `rf_app` with column-level care). `audit_log`: trigger raises on UPDATE/DELETE; `rf_app` has INSERT+SELECT only. `rf_system` BYPASSRLS.

- [ ] **Step 1: Write failing tests** (`test_isolation_matrix.py`): `test_every_workspace_table_has_forced_rls` (introspect `pg_class.relforcerowsecurity` for every table with a `workspace_id` column); `test_cross_tenant_read_returns_nothing` (insert rows for ws A and B as owner; in `tenant_session(A)` select tickets/messages/customers/audit_log → only A); `test_cross_tenant_write_is_rejected` (as A, INSERT ticket with workspace_id=B → error; UPDATE/DELETE B's rows → 0 rows); `test_audit_log_is_append_only` (UPDATE and DELETE as `rf_app` and as owner both raise).
- [ ] **Step 2: Run** `pytest tests/test_isolation_matrix.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** migration(s) with raw SQL for RLS/trigger/grants; downgrade drops everything created.
- [ ] **Step 4: Run** the new tests + `pytest tests/test_migrations.py -q` (upgrade/downgrade still pass). Expected: pass.
- [ ] **Step 5: Commit** `feat(db): core schema with forced RLS, grants and append-only audit`.

### Task 3: Authentication and CSRF

**Files:** Create `security.py`, `services/auth.py`, `api/deps.py`, `api/auth.py`; Modify `main.py`; Test `tests/test_auth.py`.

**Interfaces:**
- `security.hash_password(pw) -> str`, `verify_password(pw, hash) -> bool` (argon2id); `new_token() -> tuple[str, str]` (raw, sha256 hex).
- `deps.RequestContext(user: User, workspace_id: UUID|None, role: str|None, session: Session, csrf_ok: bool)`; `deps.get_ctx()` FastAPI dependency: reads cookie `rf_session`, validates (not expired/revoked, user.active), opens `tenant_session`, for unsafe methods requires `X-CSRF-Token == session.csrf_token` else 403.
- Routes: `POST /api/auth/signup {email,password(min 10),name,workspace_name}` → creates user, workspace (slug from name, unique-suffixed), owner membership, session; sets cookie; returns `{user, workspace, csrf_token}`. `POST /api/auth/login {email,password}` (generic error on failure; rate limited → 429). `POST /api/auth/logout`. `GET /api/auth/me → {user, workspaces[], active_workspace, role, csrf_token}`. `POST /api/workspaces/switch {workspace_id}` (must be member, else 404).

- [ ] **Step 1: Write failing tests:** signup→me works with cookie; wrong password → 401 same body as unknown email; 11th failed login in window → 429; POST without `X-CSRF-Token` → 403, with → 200; logout then `/me` → 401 and the old cookie stays dead; deactivated user's cookie → 401; password stored is argon2 (`$argon2id$`); `switch` to non-member workspace → 404; session token not stored raw (DB value ≠ cookie value).
- [ ] **Step 2: Run** `pytest tests/test_auth.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** per interfaces; cookie `httponly`, `samesite=lax`, `secure=settings.cookie_secure`, 14-day expiry.
- [ ] **Step 4: Run** `pytest -q && ruff check . && mypy src`. Expected: pass.
- [ ] **Step 5: Commit** `feat(backend): signup/login/logout with server sessions, CSRF and login rate limit`.

### Task 4: RBAC, members, invitations, outbound email interface

**Files:** Create `permissions.py`, `email/outbound.py`, `services/members.py`, `api/members.py`, `tasks/email.py` (invite send), `tests/test_rbac.py`; Modify `api/deps.py`.

**Interfaces:**
- `permissions.PERMS: dict[str, frozenset[str]]` role→permissions (`ticket:read|create|update|reply|assign|merge|bulk`, `user:read|invite|manage`, `audit:read`, `settings:read|update`); Owner/Admin all; Agent all `ticket:*` + `user:read`; Viewer `ticket:read`,`user:read`. `deps.require(perm: str)` dependency → 403 if role lacks it.
- `email.outbound.OutboundEmailProvider` Protocol `send(to: str, subject: str, text: str, headers: dict[str,str]|None=None, message_id: str|None=None) -> None`; implementations `SmtpProvider`, `PostmarkProvider`, `MemoryProvider` (tests); `get_provider(settings)`.
- Routes: `GET /api/members`; `POST /api/invitations {email, role}` (Owner/Admin; role owner only by Owner); `GET /api/invitations`; `DELETE /api/invitations/{id}`; `PATCH /api/members/{user_id} {role?, active?}`; `POST /api/auth/accept-invite {token,name,password}` (creates user if new, membership, session). Invite emails sent through provider via Celery task `send_invitation(invitation_id)` containing `{public_base_url}/accept-invite?token=…`. Last-owner demote/deactivate → 409 `last_owner`; deactivation revokes that user's sessions for that workspace context.

- [ ] **Step 1: Write failing tests:** table-driven `test_permission_matrix` (role × route → expected status, using real endpoints created so far); Agent cannot invite (403); Admin cannot grant owner (403); invite→accept flow creates active membership and the invited email arrives in `MemoryProvider` with the token link; expired/used token → 410; demoting the only Owner → 409; deactivated member's existing session → 401 on next call; Smtp provider test sends one message to a real Mailpit container and reads it back via Mailpit HTTP API; cross-tenant: admin of A cannot `PATCH` a member id of B (404).
- [ ] **Step 2: Run** `pytest tests/test_rbac.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** per interfaces (audit rows for invite/role change/deactivate via `audit.record`, defined in T5 Step 3 — create `audit.py` here if needed: `record(session, *, workspace_id, actor_type, actor_id, action, entity_type, entity_id, before, after, request_id) -> None`).
- [ ] **Step 4: Run** full suite + lint + mypy. Expected: pass.
- [ ] **Step 5: Commit** `feat(backend): RBAC, members, invitations, outbound email providers`.

### Task 5: Tickets domain and API

**Files:** Create `services/tickets.py`, `api/tickets.py`, `audit.py` (if not yet), `tests/test_tickets.py`; Modify `main.py`.

**Interfaces:**
- `tickets.create_ticket(ctx, *, subject, body, requester_email, requester_name=None, priority="normal", channel="manual", message_id=None) -> Ticket` (upserts customer by email; allocates `number` atomically via `UPDATE workspaces SET next_ticket_number = next_ticket_number+1 … RETURNING`; first message inbound public; status `new`; audit `ticket.created`).
- `tickets.update_ticket(ctx, ticket_id, *, status=None, priority=None, assignee_id=_UNSET, tags=None) -> Ticket` (assignee must be an active member else 422; status/priority validated; audit with before/after; `last_activity_at` updated; first agent action moves `new→open`).
- Routes: `GET /api/tickets?status=&priority=&assignee=me|none|<uuid>&tag=&sort=activity|created&order=&limit=<=100&cursor=` → `{items, next_cursor}` (keyset pagination, items include requester, assignee, tags, snippet, number); `POST /api/tickets` (`ticket:create`); `GET /api/tickets/{id}` (with messages); `PATCH /api/tickets/{id}` (`ticket:update`; assignee change needs `ticket:assign`); `GET /api/tickets/{id}/activity` (audit rows for that ticket).

- [ ] **Step 1: Write failing tests:** create → number 1 then 2 per workspace independently (ws B also starts at 1); concurrent creates (8 threads) yield unique consecutive numbers; list filters (status, assignee=me/none, tag) and keyset pagination returns each ticket exactly once across pages; PATCH records audit with before/after; assigning a deactivated/non-member user → 422; Viewer PATCH → 403; GET another workspace's ticket id → 404; invalid status → 422.
- [ ] **Step 2: Run** `pytest tests/test_tickets.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** per interfaces.
- [ ] **Step 4: Run** full suite + lint + mypy. Expected: pass.
- [ ] **Step 5: Commit** `feat(backend): ticket creation, listing, updates with audit`.

### Task 6: Replies, notes and reliable outbound email

**Files:** Create `services/messages.py`, `tasks/email.py` (extend); Modify `api/tickets.py`, `celery_app.py` (beat entry `requeue_stuck_outbound` every 60 s, runs as `rf_system`); Test `tests/test_messages.py`.

**Interfaces:**
- `messages.add_message(ctx, ticket_id, *, body, kind: Literal["public","note"]) -> Message` (`public` → direction outbound, `delivery_status='queued'`, generates RFC `Message-ID` `<uuid@{inbound_domain}>`, sets `in_reply_to` to last inbound message id; enqueues Celery `send_outbound_message(message_id)` **after commit**; `note` → internal, no email). Reply sets status `pending` if ticket was `new|open` and `set_pending=true` flag passed (default false); audit `message.added`.
- Task `send_outbound_message(message_id: UUID) -> None`: loads under `rf_system`, idempotent (skip if `sent`), sends via provider to requester email with headers `Message-ID`, `In-Reply-To`, `References`, Reply-To `support+{inbound_token}.{number}@{inbound_domain}`; marks `sent`; on exception increments `delivery_attempts`, retries with backoff (max 5) then `failed`. `requeue_stuck_outbound()` re-enqueues `queued` rows older than 60 s.
- Route `POST /api/tickets/{id}/messages {body (1..20000 chars), kind}` (`ticket:reply`).

- [ ] **Step 1: Write failing tests:** reply creates `queued` message and after task run `MemoryProvider` holds one mail with correct To/Subject `Re: …`/headers and status `sent`; running the task twice sends once (idempotent); provider raising once → attempts=1 and then success on retry → `sent`; after 5 failures → `failed` and visible in GET ticket; a `queued` row older than 60 s is re-enqueued by `requeue_stuck_outbound` (simulate worker never ran); note sends nothing; empty/oversize body → 422; Viewer → 403.
- [ ] **Step 2: Run** `pytest tests/test_messages.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** per interfaces.
- [ ] **Step 4: Run** full suite + lint + mypy. Expected: pass.
- [ ] **Step 5: Commit** `feat(backend): replies and notes with recoverable outbound email`.

### Task 7: Bulk actions, merge and duplicate flag

**Files:** Modify `services/tickets.py`, `api/tickets.py`; Test `tests/test_tickets.py` (extend).

**Interfaces:** `tickets.bulk_update(ctx, ids: list[UUID], *, action: Literal["assign","status","priority","add_tag"], value) -> BulkResult(updated: list[UUID], skipped: list[UUID])` (max 200 ids; ids outside the workspace are reported `skipped`, never touched; one audit row per ticket); `tickets.merge(ctx, source_id, into_id) -> Ticket` (moves messages to target preserving order, closes source with `merged_into_id`, audit; cannot merge into itself/closed-merged chains → 422). On create, if an open ticket from the same requester has a normalized-equal subject (strip `Re:/Fwd:`, case-fold) created < 24 h earlier, set `possible_duplicate_of`. Routes `POST /api/tickets/bulk` (`ticket:bulk`), `POST /api/tickets/{id}/merge {into_id}` (`ticket:merge`).

- [ ] **Step 1: Write failing tests:** bulk status on 3 tickets updates all with 3 audit rows; mixed own+foreign ids → foreign ones in `skipped`, untouched; >200 ids → 422; merge moves messages in chronological order and source becomes closed with `merged_into_id`; merge into itself → 422; duplicate heuristic sets the flag for `Re: Invoice` after `Invoice`, but not for a different requester or a 3-day-old ticket; Viewer bulk → 403.
- [ ] **Step 2: Run** `pytest tests/test_tickets.py -q`. Expected: FAIL (new tests).
- [ ] **Step 3: Implement** per interfaces.
- [ ] **Step 4: Run** full suite + lint + mypy. Expected: pass.
- [ ] **Step 5: Commit** `feat(backend): bulk actions, merge, duplicate flagging`.

### Task 8: Inbound email (provider adapter, threading, webhook, simulate)

**Files:** Create `email/inbound.py`, `email/postmark.py`, `email/threading.py`, `services/ingest.py`, `api/webhooks.py`; Test `tests/test_ingest.py`.

**Interfaces:**
- `email.inbound.InboundMessage(message_id: str, from_email: str, from_name: str|None, to_addresses: list[str], subject: str, text: str, in_reply_to: str|None, references: list[str], attachments_dropped: int)`; `InboundEmailProvider` Protocol `parse(payload: dict) -> InboundMessage`. `PostmarkInbound.parse` maps Postmark fields (`MessageID`/Headers Message-ID, `FromFull`, `ToFull`, `Subject`, `TextBody`, `HtmlBody` fallback stripped to text, `Headers`, `Attachments`); text capped at 50 000 chars; attachments are dropped and counted (attachments storage is out of MVP scope; the count is noted in the first message footer: "N attachment(s) not stored").
- `threading.match_ticket(session, msg, workspace_id) -> UUID | None`: by `In-Reply-To`/`References` against `messages.message_id`, else by plus-address `support+{token}.{number}@domain` ticket number.
- `ingest.ingest_inbound(msg: InboundMessage) -> IngestResult(status: Literal["created","appended","duplicate","ignored"], ticket_id: UUID|None)`: resolves workspace from recipient plus-address/inbound token (`inbound-{token}@{domain}` or `support+{token}...`), unknown token → `ignored`; idempotent by `(workspace_id, message_id)` unique (concurrent duplicate → `duplicate`, via `ON CONFLICT DO NOTHING`); creates ticket (channel `email`) or appends public inbound message (reopens `resolved|pending` → `open`); audit actor `system`.
- Routes: `POST /api/webhooks/email/postmark` (HTTP Basic auth, constant-time compare with `postmark_webhook_secret`; bad/missing → 401; always 200 for `ignored|duplicate`); `POST /api/dev/simulate-inbound {from_email, from_name?, subject, text, in_reply_to?}` (requires session + `settings:update`, only when `simulate_inbound_enabled`, else 404) builds a Postmark-shaped payload for the current workspace and calls the **same** webhook handler function.

- [ ] **Step 1: Write failing tests:** Postmark sample payload → `created` ticket with requester and body; reply with matching `In-Reply-To` → `appended` to same ticket and reopens `pending`; plus-address ticket-number fallback matches; same payload twice sequentially and from 8 concurrent threads → exactly 1 message; unknown token → 200 `ignored` and no rows; wrong/missing basic auth → 401; HTML-only body becomes plain text without tags; missing subject → ticket subject `(no subject)`; 100 KB body truncated to 50 000; `<script>` in body stored verbatim as text; simulate endpoint 404 when disabled, works when enabled, and produces the same result as the webhook (shared function asserted by calling both and comparing stored rows).
- [ ] **Step 2: Run** `pytest tests/test_ingest.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** per interfaces. Ingestion runs as `rf_system` after resolving the workspace, then sets tenant context for writes.
- [ ] **Step 4: Run** full suite + lint + mypy. Expected: pass.
- [ ] **Step 5: Commit** `feat(backend): inbound email via provider adapter with idempotent threading`.

### Task 9: Public web form

**Files:** Create `services/forms.py`, `api/public.py`; Test `tests/test_forms.py`.

**Interfaces:** `GET /api/public/forms/{slug} → {workspace_name}` (404 unknown); `POST /api/public/forms/{slug} {name, email, subject, message, website}` — `website` is the honeypot (non-empty → respond 200 but create nothing); validates lengths (message ≤ 10 000); Redis rate limit 5/hour per IP+slug (429); creates ticket channel `form` via `create_ticket` as actor `system`; returns `{reference: "#<number>"}`; sends no auto-reply.

- [ ] **Step 1: Write failing tests:** valid submit creates ticket with channel `form` and returns reference; honeypot filled → 200, zero rows; 6th submit from same IP in an hour → 429; unknown slug → 404; invalid email/empty message → 422; submit to workspace A never appears in B.
- [ ] **Step 2: Run** `pytest tests/test_forms.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** **Step 4: Run** full suite. **Step 5: Commit** `feat(backend): public web form with honeypot and rate limit`.

### Task 10: Audit API, CSV export, channel settings

**Files:** Create `api/audit.py`, `api/settings.py`; Test `tests/test_audit.py`.

**Interfaces:** `GET /api/audit?entity_type=&actor_id=&action=&from=&to=&limit<=200&cursor=` (`audit:read` → Owner/Admin only); `GET /api/audit.csv` same filters, streamed, header row `time,actor,action,entity_type,entity_id,before,after`, CSV-injection safe (cells starting `= + - @` prefixed with `'`); `GET /api/settings/channels → {inbound_address: "inbound-{token}@{domain}", form_url: "{public_base_url}/form/{slug}", form_snippet: "<iframe …>"}` (`settings:read`).

- [ ] **Step 1: Write failing tests:** entries from ticket/member actions appear newest-first with actor names; filters work; Agent → 403; CSV contains header and escapes a subject `=HYPERLINK(...)`; audit of workspace A never visible to B; channel settings return correct slug/token URLs.
- [ ] **Step 2–5:** run RED, implement, GREEN + full suite, commit `feat(backend): audit log API, CSV export and channel settings`.

### Task 11: Demo seed and auto-seeding

**Files:** Create `seed.py`, `tests/test_seed.py`; Modify `backend/entrypoint.sh` (api: after migrations run `python -m resolveflow.seed --if-empty` when `SEED_DEMO=1`), `docker-compose.yml` (`SEED_DEMO: "1"`, `SIMULATE_INBOUND_ENABLED: "1"` for dev), `README.md`/`start.bat`/`start.sh` messages (replace "database starts empty" with demo credentials).

**Interfaces:** `seed.seed_demo(engine) -> SeedSummary` creates workspace "Brightwork Studio" (slug `brightwork`) with 4 users (owner `owner@brightwork.test`, admin, agent, viewer; password `resolveflow-demo` documented), 25 customers, ~60 tickets across statuses/priorities/channels with realistic multi-message histories (some assigned, tagged, one merged, one possible duplicate), deterministic with a fixed RNG seed, synthetic names only. `--if-empty` is a no-op when any workspace exists (idempotent restarts).

- [ ] **Step 1: Write failing tests:** `seed_demo` yields 4 members with each role, 60±5 tickets across all five statuses and four priorities, every ticket has ≥1 message, at least one note/outbound/merged/duplicate; running `--if-empty` twice leaves counts unchanged; seeded owner can log in via API and sees tickets through RLS; no two workspaces' data mixed.
- [ ] **Step 2–5:** RED, implement, GREEN + full suite, verify `docker compose up -d --build` from scratch shows seeded login works through `http://localhost:3000/api/auth/login`; commit `feat(backend): demo seed with auto-seed on first start`.

### Task 12: Frontend design system, shell, auth pages

**Files:** Create `frontend/src/design/{tokens.css,fonts.ts}`, `src/lib/{api.ts,keys.ts}`, `src/app/{router,shell,auth}.tsx`, `src/features/auth/{LoginPage,SignupPage,AcceptInvitePage}.tsx`, tests in `src/__tests__/`; Modify `main.tsx`, `index.css`, `package.json` (react-router-dom, lucide-react, @fontsource-variable/hanken-grotesk, @fontsource-variable/newsreader); regenerate `api/schema.d.ts`.

**Interfaces:** `lib/api.ts`: `api<T>(path, init?) → Promise<T>` adds JSON headers, `credentials: 'same-origin'`, `X-CSRF-Token` from the in-memory session on unsafe methods; throws `ApiError{status, code, message}`; 401 → clears session and routes to `/login`. `app/auth.tsx`: `AuthProvider`, `useAuth() → {user, workspace, role, can(perm), logout}`; `can` mirrors backend `PERMS` fetched from `/api/auth/me` (`permissions: string[]` added to the response in T3 — add it there). Tokens in `design/tokens.css` exactly as in Design Language, dark theme via `prefers-color-scheme` plus a persisted toggle. Shell: 56px rail (workspace initial, Inbox, People, Channels, Audit — items hidden when `can()` is false, theme toggle, account menu with sign out and workspace switcher when >1).

- [ ] **Step 1: Write failing tests (Vitest, real components, `fetch` stubbed only at the network edge):** login form shows API error text ("Email or password is incorrect.") without revealing which; successful login routes to inbox; `useAuth().can('audit:read')` false for agent; nav hides People/Audit for Viewer; unsafe request sends `X-CSRF-Token`; 401 from any call redirects to `/login`.
- [ ] **Step 2: Run** `npm test -- --run`. Expected: FAIL.
- [ ] **Step 3: Implement** with `frontend-design` quality: login/signup pages are calm, left-aligned, one column, with a short factual line about what ResolveFlow does (no marketing hero); focus rings, labelled inputs, inline validation.
- [ ] **Step 4: Run** `npm test -- --run && npx oxlint && npx tsc -b && npm run build`, then open the running app in the browser (claude-in-chrome) and check both themes at desktop and 390 px width via screenshots. Expected: pass; screenshots reviewed.
- [ ] **Step 5: Commit** `feat(frontend): design system, app shell, auth pages`.

### Task 13: Inbox (queue)

**Files:** Create `src/features/inbox/{InboxPage,QueueRow,FilterBar,BulkBar,useQueueKeys}.tsx` and tests.

**Interfaces:** Consumes `GET /api/tickets`, `POST /api/tickets/bulk`, `PATCH /api/tickets/{id}`. Views (real filter presets, URL-synced): Mine (`assignee=me`), Unassigned (`assignee=none`), All open (status not resolved/closed). Row: requester name, subject, 1-line snippet, relative time (tabular), status marker, priority marker, assignee avatar initials, `possible duplicate` badge when set. Infinite keyset pagination. Keyboard: `j/k`, `Enter`, `x`, `e`, `a`, `/`, `?`. Bulk bar appears on selection with Assign / Set status / Set priority / Add tag (real calls, optimistic update with rollback + toast on error). Empty states: per view with a next action (e.g. Unassigned: "Nothing waiting. New requests land here.").

- [ ] **Step 1: Write failing tests:** view switch changes request query string; `j`,`j`,`Enter` opens the 2nd row's ticket; `x` selects and bulk bar shows count; bulk status posts the expected body and rows update; API error rolls back and shows the error toast; empty state copy per view; `?` opens the shortcuts dialog with every bound key listed (test iterates the key map so no dead shortcut can exist).
- [ ] **Step 2–5:** RED, implement (frontend-design), GREEN + `oxlint/tsc/build`, browser check with seeded data (screenshot, keyboard flow), commit `feat(frontend): inbox with views, keyboard navigation and bulk actions`.

### Task 14: Ticket detail and composer

**Files:** Create `src/features/ticket/{TicketPane,Thread,Composer,Properties,Activity,MergeDialog}.tsx` and tests.

**Interfaces:** Consumes `GET/PATCH /api/tickets/{id}`, `POST …/messages`, `POST …/merge`, `GET …/activity`, `GET /api/members`. Thread: messages as correspondence — Newsreader body text at 17px/1.6, author + time in the UI face, internal notes visually distinct (tinted band + "Internal note" label, plain wording), delivery state on outbound messages ("Sending…", "Sent", "Couldn't send — retrying" / "Failed to send"), body rendered as text with preserved line breaks. Composer: Reply / Note tabs, `Ctrl+Enter` sends, disabled for Viewer with explanation, keeps draft per ticket in `localStorage`. Properties: status, priority, assignee (members select; "Assign to me"), tags (add/remove), real PATCH with optimistic update. Merge dialog (search among open tickets of the same list). Activity: real audit entries for this ticket.

- [ ] **Step 1: Write failing tests:** a message containing `<img src=x onerror=alert(1)>` renders as literal text (no element created); notes are visually and textually distinguished; sending a reply calls the API with `kind: public` and the new message appears; `Ctrl+Enter` sends; Viewer sees read-only composer with reason; failed PATCH reverts the control and shows an error; draft restored after navigation; delivery `failed` shows the failure state.
- [ ] **Step 2–5:** RED, implement (frontend-design), GREEN + lint/tsc/build, browser check (reply goes to Mailpit at :8025 — verify the mail really arrives), commit `feat(frontend): ticket pane with thread, composer and properties`.

### Task 15: People, channels, audit, new ticket, public form

**Files:** Create `src/features/{people,channels,audit,newticket,publicform}/*` and tests.

**Interfaces:** People: members table with role select / deactivate (confirm dialog), invite form, pending invitations with revoke; last-owner error shown plainly. Channels: shows inbound address with copy button, form URL + embed snippet with copy button, and (when `simulate_inbound_enabled` exposed via `/api/settings/channels.simulate_enabled`) a "Simulate customer email" form that posts to `/api/dev/simulate-inbound` and links to the created ticket. Audit: filterable table, "Export CSV" downloads `/api/audit.csv`. New ticket dialog (`c` key and button). Public form page at `/form/:slug` (no auth, standalone layout, honeypot field hidden accessibly, success state shows reference number).

- [ ] **Step 1: Write failing tests:** invite posts role and shows it pending; role change of last Owner shows the 409 message; deactivate requires confirmation; copy buttons write the exact strings to the clipboard; simulate form hidden when disabled; audit filters change query; public form shows the 429 message in plain language and success reference; honeypot field is not reachable by keyboard focus order.
- [ ] **Step 2–5:** RED, implement (frontend-design), GREEN + lint/tsc/build, browser check, commit `feat(frontend): people, channels, audit, new ticket and public form`.

### Task 16: End-to-end tests and CI

**Files:** Create `frontend/playwright.config.ts`, `frontend/e2e/{auth,tickets,people,channels}.spec.ts`; Modify `.github/workflows/ci.yml` (compose-smoke runs e2e after the stack is up; Playwright chromium installed in CI), `frontend/package.json` (`e2e` script), `CONTRIBUTING.md`.

**Interfaces:** Config `baseURL` from `E2E_BASE_URL` (default `http://localhost:3000`), `channel: 'chrome'` locally when `E2E_CHANNEL=chrome`, else bundled chromium; tests log in as the seeded users. Specs cover: sign up new workspace; log in/out; create ticket; open from queue via keyboard; reply and see it in Mailpit (`http://localhost:8025/api/v1/messages`); internal note; change status/priority/assign; bulk resolve; merge; simulate inbound email creates a ticket and a second one with `in_reply_to` appends; submit public form creates a ticket; invite → accept in a fresh context; Viewer cannot see composer; Agent has no People/Audit nav; audit shows the actions just performed; cross-workspace: user of workspace B opening A's ticket URL sees "not found".

- [ ] **Step 1: Write the specs** (they fail until the stack runs with seed data).
- [ ] **Step 2: Run** `docker compose up -d --build` (seeded), then `cd frontend && npx playwright test`. Expected: any failing spec exposes a real defect → fix the defect with a RED→GREEN unit/integration test at the right layer, then rerun until all pass.
- [ ] **Step 3:** wire into CI; push branch; Expected: `backend`, `frontend`, `compose-smoke` (now incl. e2e) green.
- [ ] **Step 4: Commit** `test(e2e): playwright coverage for core inbox flows; ci runs e2e`.

### Task 17: Phase close

- [ ] **Step 1:** full local verification: backend `pytest -q && ruff check . && ruff format --check . && mypy src alembic`; frontend `npm test -- --run && npx oxlint && npx tsc -b && npm run build`; e2e green; clean-clone `start.bat` shows seeded demo, login works, a reply reaches Mailpit.
- [ ] **Step 2:** independent whole-branch review (most capable model) with the Review Focus list; fix legitimate Critical/Important findings with RED→GREEN tests.
- [ ] **Step 3:** PR, CI green, squash-merge, tag `m1-complete`, push; write the M2 plan.

---

## Self-Review

- **Spec coverage:** §6 tenancy/RLS (T1–T2, matrix tests), §7.1 ingestion (T8, T9), §7.2 tickets/merge/bulk (T5–T7; teams deferred to M3 where team assignment is used), §7.6 RBAC (T4), §7.7 audit (T2, T10), §7.10 privacy basics (T3 argon2/rate limit, T2 RLS; retention setting is M5), §8 UI (T12–T15), §10 seed + start scripts (T11), PRD FR-1..10 except saved views beyond the three presets and "claim" (covered by `a`/Assign to me), FR-26..28.
- **Deliberately deferred (not in M1):** SLA, rules, notifications beyond invite/reply email, search, reports, customer page, attachments storage, teams, retention.
- **Type consistency:** `RequestContext`, `create_ticket`/`update_ticket`/`bulk_update`/`merge`, `InboundMessage`, `IngestResult`, `OutboundEmailProvider.send` signatures are used identically across T3–T9; `permissions` strings identical backend/frontend (`/api/auth/me.permissions`).
- **Proportion:** interfaces and test cases, no bodies.
