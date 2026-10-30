# Development guide

How to work on ResolveFlow. For the workflow and branching rules, see [CONTRIBUTING.md](../CONTRIBUTING.md).

## Repository layout

```
backend/                 FastAPI app, Celery tasks, migrations, tests
  alembic/versions/      database migrations (0001 ... 0009)
  src/resolveflow/       application code (see ARCHITECTURE.md)
  tests/                 pytest suite (real Postgres and Redis via testcontainers)
frontend/                React + TypeScript + Vite app
  src/features/          one folder per product area
  src/__tests__/         component and page tests (Vitest + Testing Library)
  e2e/                   Playwright tests against the running stack
  scripts/screenshots.mjs  regenerates docs/images
docs/                    product and engineering documentation
scripts/                 helper scripts (health wait, API doc generator)
docker-compose.yml       the whole stack
start.bat / stop.bat / reset.bat / start.sh / Makefile
```

## Prerequisites

- Docker Desktop (runs the stack and the backend tests).
- Python 3.12 and Node 20 or newer, only if you run code outside Docker.

## Run the whole stack

`start.bat` (Windows) or `./start.sh` / `make up`. The first start builds the images and seeds the demo workspace.

Services and ports (all bound to `127.0.0.1`, configurable in `.env`):

| Service | Port | Notes |
| --- | --- | --- |
| web (nginx + built frontend) | 3000 | proxies `/api` to the API |
| api (FastAPI) | 8000 | interactive docs at `/docs` |
| db (PostgreSQL 16) | 5433 | user `resolveflow`, database `resolveflow` |
| redis | 6379 | broker only |
| mailpit | 8025 (UI), 1025 (SMTP) | captures outgoing email |

Rebuild after changing code: `docker compose up -d --build`. Wipe all data: `reset.bat` or `docker compose down -v`.

## Backend without Docker for the app

```
cd backend
py -3.12 -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\python -m pytest -q
```

Tests start disposable Postgres and Redis containers. To use your own instances instead, set `TEST_DATABASE_URL` and `TEST_REDIS_URL`.

Quality gates (all enforced in CI):

```
ruff check . && ruff format --check . && mypy src alembic && pytest -q
```

### Database

- Migrations live in `backend/alembic/versions`. Add one with a new number and `down_revision` pointing at the latest.
- Three roles are used: the owner (migrations only), `rf_app` (the API and worker; row-level security enforced) and `rf_system` (the scheduler, inbound ingest and login lookup; bypasses RLS). Every new tenant table needs `workspace_id`, composite foreign keys `(id, workspace_id)`, forced RLS and grants for both roles. Migration 0007 is a good template.
- SQL is written with `text()` and bound parameters. Never build SQL from user input.

### Adding an endpoint

1. Add a route under `api/`, protected by `Depends(require("<permission>"))`.
2. Put the logic in `services/` (or a feature module). It receives a `ServiceCtx` (a tenant-scoped session plus the actor), so it works for requests, rules and background jobs alike.
3. Call `ctx.commit()` once at the end of a write endpoint. Anything you need after the commit must be read before it.
4. Add a new permission to `permissions.py` and to `frontend/src/lib/permissions.ts`.
5. Write the failing test first. Tests use the `client_factory` fixture and helpers in `tests/helpers.py`.
6. Regenerate the API reference: `python scripts/gen_api_doc.py` from `backend/`.

### Background jobs

Celery tasks live in `tasks/` and are scheduled in `celery_app.py`. Anything that must not be lost or repeated is stored as a row with a state and claimed with `FOR UPDATE SKIP LOCKED`; the task is only a wake-up call. See the SLA sweeper and `notifications/delivery.py`.

## Frontend

```
cd frontend
npm install
npm run dev          # Vite dev server on http://localhost:5173, proxies /api to :8000
npm run lint && npx tsc -b && npm test -- --run && npm run build
```

- Server state uses TanStack Query. There is no global client store.
- Components are small and live next to the feature that uses them. Shared primitives are in `src/ui`.
- Tests render the real routes with `renderApp` and stub `fetch` with `stubFetch` (`src/test-utils.tsx`).
- Copy is sentence case and written for the person using the product, not the system.

### End-to-end tests

With the stack running:

```
cd frontend
npx playwright install chromium     # or set E2E_CHANNEL=chrome to reuse Chrome
npm run e2e
```

They use the seeded demo accounts or create a fresh workspace per test, so they can run repeatedly.

### Regenerating the README screenshots

With the stack freshly reset (`reset.bat`, then `start.bat`):

```
cd frontend
E2E_CHANNEL=chrome node scripts/screenshots.mjs
```

## Testing strategy

| Layer | Tool | What it proves |
| --- | --- | --- |
| Pure engines | pytest | SLA maths and rule evaluation, with no database |
| Services and API | pytest + real Postgres/Redis | permissions, tenant isolation, idempotency, restart safety |
| Components and pages | Vitest + Testing Library | what a user sees and can do |
| Whole product | Playwright against Docker Compose | real browser, real API, worker and mail capture |

CI (`.github/workflows/ci.yml`) runs the backend, frontend and a Compose smoke job that includes the Playwright suite.

## Conventions

- Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`), one branch per piece of work, squash-merged to `main` after CI is green.
- Tests first. A bug fix starts with a test that fails.
- Every state change that matters is written to the audit log in the same transaction.
- Keep the scope tight: no new technology without a clear need.
