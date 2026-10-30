# ResolveFlow

Customer support and SLA automation for small service teams. One shared inbox, ticket assignment, priority rules, response-time targets that actually track business hours, escalation alerts, automation rules you can test before they go live, and searchable history.

Everything in the UI is wired to a real backend. There is no mock data path.

## Run it (Windows + Docker Desktop)

Double-click `start.bat`. It starts Docker Desktop if needed, builds and starts everything, waits until the API is healthy and opens http://localhost:3000.

| What | Where |
| --- | --- |
| App | http://localhost:3000 |
| Captured outgoing email (Mailpit) | http://localhost:8025 |
| Public contact form (demo workspace) | http://localhost:3000/form/brightwork |

Sign in with a demo account (password `resolveflow-demo` for all of them): `owner@brightwork.test`, `admin@brightwork.test`, `agent@brightwork.test`, `viewer@brightwork.test`. The data is synthetic and is created on first start only.

`stop.bat` stops the stack. `reset.bat` also **deletes all data**. On Linux, macOS or WSL use `./start.sh` or `make up`. Ports can be changed in `.env` (created from `.env.example` on first run). Host ports bind to `127.0.0.1` only.

A guided tour is in [docs/DEMO.md](docs/DEMO.md).

## What it does

- **Shared inbox.** Email in (simulated locally, real via a Postmark webhook), a public web form, manual tickets. Threading by headers and plus-addresses, duplicate detection, merge, bulk actions, keyboard shortcuts.
- **Service levels.** First-response and resolution targets per priority, counted in business hours in the workspace timezone, paused while waiting on the customer. Every deadline can explain how it was calculated. A scheduler records warnings and breaches exactly once and recovers after restarts.
- **Automations.** AND/OR conditions over a fixed set of fields, actions to assign (including round-robin across a team), set priority or status, tag, notify and escalate. Every rule version is immutable. A rule can only go live after a passing test of that exact version, and any edit requires a new test. Each ticket shows which rules ran and why.
- **Notifications.** In-app (bell) and email, per-person preferences, no duplicates, retried with backoff, dead-lettered after five failures with an admin retry.
- **Search and history.** Full-text search across subjects and messages with highlighted matches, and a history page per customer.
- **Analytics.** SLA compliance, average response and resolution times, volume by day, priority, channel and teammate.
- **Privacy.** Configurable retention that erases old finished tickets and customer details. See [docs/SECURITY.md](docs/SECURITY.md).
- **Teams.** Owner, Admin, Agent and Viewer roles, invitations, and strict per-workspace isolation enforced in the database.

## How it is built

A modular monolith: FastAPI (Python 3.12), PostgreSQL 16, Redis + Celery (worker and scheduler), React 19 + TypeScript + Vite + Tailwind. Seven containers: `db`, `redis`, `mailpit`, `api`, `worker`, `beat`, `web`. PostgreSQL is the source of truth for every job, so restarting any container never loses or repeats work. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Develop

```
cd backend  && ruff check . && ruff format --check . && mypy src alembic && pytest -q
cd frontend && npm run lint && npx tsc -b && npm test -- --run && npm run build
cd frontend && E2E_CHANNEL=chrome npm run e2e     # needs the stack running
```

Backend tests start real Postgres and Redis with testcontainers (Docker required). See [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow.

## Project documents

[Product requirements](docs/PRD.md) · [Design](docs/superpowers/specs/2026-10-30-resolveflow-design.md) · [Architecture](docs/ARCHITECTURE.md) · [Security and privacy](docs/SECURITY.md) · [Demo script](docs/DEMO.md) · [Phase plans](docs/superpowers/plans/)

## Using real email

Outgoing mail goes to Mailpit by default. To send through Postmark instead, put `EMAIL_PROVIDER=postmark` and `POSTMARK_SERVER_TOKEN=...` in your local `.env` (never commit it). Inbound mail arrives at `/api/webhooks/email/postmark` (basic auth with `POSTMARK_WEBHOOK_SECRET`); locally you simulate it from the Channels page.
