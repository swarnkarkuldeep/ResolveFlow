# Changelog

Built in five phases. Each was developed on its own branch, tested, reviewed and squash-merged to `main`, then tagged.

## M5: retention, hardening and documentation (`m5-complete`)
- Configurable data retention with redaction of expired finished tickets and customer details, an hourly job, and an on-demand erase with confirmation.
- Security headers on every API response and a same-origin Content-Security-Policy on the web app.
- Full documentation set: README with screenshots, user guide, architecture, development guide, API reference, security notes, troubleshooting and a demo walkthrough.

## M4: search, notifications, analytics (`m4-complete`)
- Full-text search over subjects and messages with ranking and highlighted snippets.
- In-app and email notifications for assignments, customer replies, service-deadline warnings and breaches, and automation alerts. Per-person preferences, no duplicates, retries with backoff, dead-lettering and an admin retry.
- Analytics for service-level compliance, response times and volume.
- Customer history page.

## M3: automations (`m3-complete`)
- Versioned automation rules (AND/OR conditions, assign, round-robin, priority, status, tags, notify, escalate).
- Synthetic-ticket tester bound to the exact rule version; activation requires a passing test; rollback to tested versions.
- Teams, and a per-ticket "Automations that ran" explanation.

## M2: service levels (`m2-complete`)
- First-response and resolution targets per priority, counted in business hours and timezones, with pause while waiting on the customer.
- Event-sourced clocks, an idempotent, concurrency-safe, restart-recoverable sweeper for warnings and breaches, and an explanation of every deadline.

## M1: the inbox (`m1-complete`)
- Workspaces, accounts, roles, invitations and an audit log.
- Shared inbox with tickets, messages, notes, tags, assignment, merge, bulk actions and keyboard shortcuts.
- Email in and out through provider interfaces, a public web form, and demo seed data.
- Tenant isolation enforced by PostgreSQL row-level security.

## M0: foundation (`m0-complete`)
- Docker Compose stack with one-click start, health checks, CI (backend, frontend, Compose smoke with end-to-end tests).
