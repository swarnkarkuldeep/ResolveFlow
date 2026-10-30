# Contributing

Setup, testing and code conventions are in the [development guide](docs/DEVELOPMENT.md). This file covers the workflow.

## Workflow
- `main` is always green and deployable. Never push to it directly.
- One branch per phase/feature: `m<N>-<topic>` (e.g. `m1-auth-tickets`). Small Conventional Commits (`feat(backend): …`, `fix:`, `docs:`, `ci:`).
- Open a PR into `main`; required checks: `backend`, `frontend`, `compose-smoke`. Merge (squash) only when green, then delete the branch.
- Tests first (TDD). A change without a test that failed before it is not done.

## Two-developer split
- **Dev A** — backend/platform: API, DB/migrations, background jobs, infra.
- **Dev B** — frontend/product: React app, UX, e2e tests.
- Contract first: change the API, run `sh scripts/gen_api_client.sh`, commit the regenerated `frontend/src/api/schema.d.ts`.

## Local checks
```
cd backend  && ruff check . && ruff format --check . && mypy src alembic && pytest -q
cd frontend && npm run lint && npx tsc -b && npm test -- --run && npm run build
```
End-to-end tests (`npm run e2e`, needs the stack running via `start.bat`; set `E2E_CHANNEL=chrome` to reuse an installed Chrome) drive the real UI against the real API, worker and Mailpit.
Backend tests start real Postgres/Redis with testcontainers (Docker required) or use `TEST_DATABASE_URL`/`TEST_REDIS_URL`.
