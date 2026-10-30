# M0 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A running skeleton (FastAPI API, Celery worker + beat, React SPA, Postgres, Redis, Mailpit) that starts with one click on Windows/Docker Desktop, is covered by CI, and proves every moving part is really wired (health checks, migrations, heartbeat task, generated API client).

**Architecture:** Modular monolith. One Python package `resolveflow` (API + Celery tasks share code), one Vite React SPA, PostgreSQL as source of truth, Redis only as Celery broker/pub-sub. Compose runs `api`, `worker`, `beat`, `web`, `db`, `redis`, `mailpit` as separate processes. No product features yet; M0 only builds the rails M1–M5 run on.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 (sync) + psycopg 3, Alembic, Celery 5 + Redis, pydantic-settings, pytest + testcontainers, ruff, mypy; Node 22, Vite, React 18, TypeScript, TanStack Query, Tailwind, Vitest, openapi-typescript; Docker Compose; GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-30-resolveflow-design.md` (esp. §4, §5, §9, §10, §12, §16), `docs/PRD.md` (NFR-6..8).

## Global Constraints

- Backend Python 3.12 + FastAPI; frontend React + TypeScript; PostgreSQL 16; Redis + Celery. No Kafka, Kubernetes, microservices or paid services.
- Modular monolith; `api`, `worker`, `beat` are logically independent processes (separate compose services/commands).
- Windows 11 + Docker Desktop is the primary dev environment; CI runs on Linux; ship `start.bat` **and** `start.sh`/`Makefile`.
- One-click start: `start.bat` starts Docker Desktop if needed, builds, waits for API health, opens `http://localhost:3000`; Mailpit UI on `:8025`.
- Local dev must not require any paid provider or secret; `.env.example` has working defaults.
- Every UI element wired to the real backend; no mock data, no dead controls.
- Git: branch `m0-foundation`, small commits (Conventional Commits), push often, PR into `main` after tests pass, merge, push `main`.
- Shell/entrypoint scripts must be LF (`.gitattributes`), since Windows checkouts break Linux containers otherwise.

## Review Focus

- Docker Desktop not running / not installed: `start.bat` must say so plainly and exit non-zero, not hang.
- Host ports 3000/8000/5432/6379/8025 already taken: ports configurable via `.env`; message tells which port clashed.
- Redis or Postgres down while API is up: `/api/health/ready` returns 503 with per-check detail, never a 500/stack trace.
- Second `start.bat` run (containers and volume already exist): idempotent, migrations are no-ops, no data loss; `reset.bat` is the only thing that wipes data.
- CRLF line endings in `*.sh`/entrypoint after a Windows git checkout: container still starts.
- Scheduler dead: `/api/health/system` reports the beat heartbeat as stale (visible, not silent).

---

## File Structure

```
.gitattributes  .env.example  docker-compose.yml  Makefile
start.bat stop.bat reset.bat start.sh
.github/workflows/ci.yml
backend/  pyproject.toml  Dockerfile  alembic.ini  entrypoint.sh
  alembic/env.py  alembic/versions/0001_baseline.py
  src/resolveflow/{__init__,config,db,main,health,celery_app}.py
  src/resolveflow/tasks/{__init__,system}.py
  tests/{conftest.py,test_config.py,test_health.py,test_migrations.py,test_heartbeat.py}
frontend/  package.json  vite.config.ts  Dockerfile  nginx.conf  index.html
  src/{main.tsx,App.tsx,api/health.ts,api/schema.d.ts(generated),pages/StatusPage.tsx}
  src/__tests__/StatusPage.test.tsx
scripts/{wait_for_health.py,gen_api_client.sh}
CONTRIBUTING.md  README.md (update)
```

### Task 1: Backend skeleton, config and liveness

**Files:**
- Create: `backend/pyproject.toml`, `backend/src/resolveflow/{__init__,config,main}.py`, `backend/tests/{conftest.py,test_config.py,test_health.py}`
- Branch: `git switch -c m0-foundation`

**Interfaces:**
- Produces: `resolveflow.config.Settings` (pydantic-settings, env-driven) with fields `env: str = "dev"`, `database_url: str`, `redis_url: str`, `smtp_host: str = "mailpit"`, `smtp_port: int = 1025`; `get_settings() -> Settings` (lru_cached). `resolveflow.main.app: FastAPI`, `GET /api/health/live -> {"status": "ok"}`.

- [ ] **Step 1: Write failing tests** — `test_config.py::test_settings_read_env` sets `DATABASE_URL`, `REDIS_URL` via monkeypatch and asserts `get_settings().database_url`/`redis_url` equal them after `get_settings.cache_clear()`; `test_config.py::test_missing_database_url_raises` asserts `ValidationError`. `test_health.py::test_live_returns_ok` uses `TestClient(app)` and asserts `GET /api/health/live` → 200, `{"status": "ok"}`.
- [ ] **Step 2: Run** `cd backend && pip install -e ".[dev]" && pytest -q`. Expected: FAIL (modules missing).
- [ ] **Step 3: Implement** `pyproject.toml` (project `resolveflow`, src layout, deps: fastapi, uvicorn[standard], sqlalchemy>=2, psycopg[binary]>=3, alembic, celery[redis], redis, pydantic-settings; dev: pytest, httpx, testcontainers[postgres,redis], ruff, mypy; ruff + mypy strict config), `config.py`, `main.py` (router mounted under `/api`).
- [ ] **Step 4: Run** `pytest -q && ruff check . && mypy src`. Expected: all pass.
- [ ] **Step 5: Commit** `feat(backend): skeleton, settings, liveness endpoint`.

### Task 2: Database layer, baseline migration, readiness

**Files:**
- Create: `backend/src/resolveflow/{db,health}.py`, `backend/alembic.ini`, `backend/alembic/{env.py,versions/0001_baseline.py}`, `backend/tests/test_migrations.py`
- Modify: `backend/src/resolveflow/main.py`, `backend/tests/conftest.py` (session-scoped testcontainers `postgres_url`, `redis_url` fixtures; honour `TEST_DATABASE_URL`/`TEST_REDIS_URL` env in CI to use service containers instead)

**Interfaces:**
- Produces: `db.engine_for(url: str) -> Engine`; `db.get_session() -> Iterator[Session]` (FastAPI dependency). `health.CheckResult(name: str, ok: bool, detail: str)` dataclass; `health.check_db(engine) -> CheckResult`; `health.check_redis(url: str) -> CheckResult` (both catch all exceptions, never raise, use 2 s timeouts). `GET /api/health/ready` → 200 `{"status":"ready","checks":[…]}` or 503 `{"status":"degraded","checks":[…]}`, checks serialised as `{name, ok, detail}`.
- Migration `0001_baseline` creates table `system_heartbeat(id smallint primary key check (id = 1), beat_at timestamptz not null)`; downgrade drops it.

- [ ] **Step 1: Write failing tests** — `test_migrations.py::test_upgrade_head_then_downgrade_base` runs Alembic programmatically against the container, asserts `system_heartbeat` exists after upgrade and is gone after downgrade; `::test_upgrade_is_idempotent` runs upgrade twice, no error. `test_health.py::test_ready_ok` (real containers) → 200 and both checks `ok`; `::test_ready_503_when_redis_down` points `REDIS_URL` at an unused port → 503, redis check `ok == False`, db check `ok == True`, body has no traceback text; same for a bad DB URL.
- [ ] **Step 2: Run** `pytest tests/test_migrations.py tests/test_health.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `db.py`, `health.py`, `/api/health/ready`, Alembic env reading `get_settings().database_url`, baseline migration.
- [ ] **Step 4: Run** same command. Expected: PASS. Also `ruff check . && mypy src`.
- [ ] **Step 5: Commit** `feat(backend): db layer, baseline migration, readiness endpoint`.

### Task 3: Celery worker, beat and scheduler heartbeat

**Files:**
- Create: `backend/src/resolveflow/{celery_app.py,tasks/__init__.py,tasks/system.py}`, `backend/tests/test_heartbeat.py`
- Modify: `backend/src/resolveflow/{health.py,main.py}`

**Interfaces:**
- Produces: `celery_app.celery: Celery` (broker/result = `redis_url`, `task_acks_late=True`, `task_reject_on_worker_lost=True`, `broker_connection_retry_on_startup=True`, beat schedule `heartbeat` every 30 s). Task `resolveflow.tasks.system.heartbeat() -> None` upserts `system_heartbeat(id=1, beat_at=now())` (idempotent `INSERT … ON CONFLICT (id) DO UPDATE`). `health.check_scheduler(engine, max_age_s: int = 90) -> CheckResult` (`ok=False`, detail `"no heartbeat yet"` or `"stale: <n>s"`). `GET /api/health/system` → always 200 with checks db, redis, scheduler (informational; readiness does not depend on beat).

- [ ] **Step 1: Write failing tests** — `test_heartbeat.py::test_heartbeat_upserts_single_row` calls the task function twice, asserts exactly one row and `beat_at` advanced; `::test_scheduler_check_states` asserts no row → `ok False "no heartbeat yet"`, fresh row → `ok True`, row 5 min old → `ok False` detail starts with `"stale"`; `::test_system_endpoint_reports_stale_scheduler` hits `/api/health/system` with a stale row → 200 and scheduler check `ok == False`.
- [ ] **Step 2: Run** `pytest tests/test_heartbeat.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the Celery app, task and check.
- [ ] **Step 4: Run** `pytest -q && ruff check . && mypy src`. Expected: pass.
- [ ] **Step 5: Commit** `feat(backend): celery app, beat heartbeat, system health`.

### Task 4: Frontend skeleton with real status page and generated API client

**Files:**
- Create: `frontend/` (Vite React TS template with Tailwind, TanStack Query, Vitest + Testing Library), `frontend/src/api/health.ts`, `frontend/src/pages/StatusPage.tsx`, `frontend/src/__tests__/StatusPage.test.tsx`, `scripts/gen_api_client.sh`
- Modify: `frontend/vite.config.ts` (dev proxy `/api` → `http://localhost:8000`)

**Interfaces:**
- Consumes: `GET /api/health/system` from Task 3.
- Produces: `fetchSystem(): Promise<{status: string; checks: {name: string; ok: boolean; detail: string}[]}>`; `<StatusPage/>` renders one row per check with name, ok/not-ok indicator and detail; shows an error state if the request fails. `scripts/gen_api_client.sh` runs `openapi-typescript http://localhost:8000/openapi.json -o frontend/src/api/schema.d.ts`; the committed `schema.d.ts` is generated, not hand-written.

- [ ] **Step 1: Write failing tests** — `StatusPage.test.tsx`: `renders each check from the API` (stub `fetch` with db ok, scheduler not ok "stale: 300s"; asserts both names and the stale text appear); `shows an error state when the API is unreachable` (fetch rejects → text matching /unable to reach/i).
- [ ] **Step 2: Run** `cd frontend && npm test -- --run`. Expected: FAIL.
- [ ] **Step 3: Implement** the page and client; wire `App.tsx` to render `StatusPage`; generate `schema.d.ts` against a locally running API.
- [ ] **Step 4: Run** `npm test -- --run && npm run lint && npx tsc --noEmit && npm run build`. Expected: pass. Manually: with API running, `npm run dev` shows live checks.
- [ ] **Step 5: Commit** `feat(frontend): skeleton, status page, generated api client`.

### Task 5: Containers and compose stack

**Files:**
- Create: `backend/Dockerfile`, `backend/entrypoint.sh`, `frontend/Dockerfile`, `frontend/nginx.conf`, `docker-compose.yml`, `.env.example`, `.gitattributes`, `scripts/wait_for_health.py`

**Interfaces:**
- Produces: compose services `db` (postgres:16, healthcheck `pg_isready`), `redis` (redis:7, healthcheck `redis-cli ping`), `mailpit` (axllent/mailpit, ports 1025/8025), `api` (runs `entrypoint.sh api`: `alembic upgrade head` then `uvicorn`), `worker` (`celery -A resolveflow.celery_app worker`), `beat` (`celery … beat` with schedule file on a writable volume), `web` (nginx serving the build, proxying `/api` to `api:8000`). All app services use `depends_on: condition: service_healthy`; `api` has a healthcheck on `/api/health/ready`. Host ports from `.env`: `WEB_PORT=3000`, `API_PORT=8000`, `DB_PORT=5432`, `REDIS_PORT=6379`, `MAILPIT_UI_PORT=8025`. `scripts/wait_for_health.py <url> <timeout_s>` exits 0 when URL returns 200, non-zero on timeout.

- [ ] **Step 1: Write failing check** — `docker compose config -q` exits 0 and `python scripts/wait_for_health.py http://localhost:1 3` exits non-zero within ~4 s (fast-fail verification of the helper).
- [ ] **Step 2: Run** both. Expected: FAIL (files missing).
- [ ] **Step 3: Implement** all files. `.gitattributes`: `* text=auto`, `*.sh text eol=lf`, `Dockerfile text eol=lf`. Containers run as non-root; no secrets baked in.
- [ ] **Step 4: Verify** `docker compose up -d --build`, then `python scripts/wait_for_health.py http://localhost:8000/api/health/ready 120` exits 0; `curl http://localhost:3000/api/health/system` shows scheduler `ok` within ~60 s; `docker compose logs worker beat` show heartbeat task executed; `docker compose down` then `up -d` again leaves data and migrations intact (no errors).
- [ ] **Step 5: Commit** `feat(infra): dockerfiles and compose stack with healthchecks`.

### Task 6: One-click scripts

**Files:**
- Create: `start.bat`, `stop.bat`, `reset.bat`, `start.sh`, `Makefile`

**Interfaces:**
- Produces: `start.bat` flow: (1) `docker info` fails → start `Docker Desktop.exe` (from `%ProgramFiles%\Docker\Docker`) and poll up to 120 s, else print "Docker Desktop is not installed or failed to start" and `exit /b 1`; (2) copy `.env.example` → `.env` if absent; (3) `docker compose up -d --build`; (4) wait for API ready via `scripts/wait_for_health.py` (falls back to a curl loop if Python is absent); (5) `start http://localhost:%WEB_PORT%`; prints Mailpit URL. On compose failure prints the ports in use hint and exits non-zero. `stop.bat` = `docker compose down`; `reset.bat` asks for confirmation, then `docker compose down -v`. `start.sh` + `Makefile` targets `up|down|reset|test|logs` mirror these.

- [ ] **Step 1: Define verification** — manual script checks listed in Step 4 (batch files are not unit-testable; the checks are the test).
- [ ] **Step 2: Run** `start.bat` with Docker Desktop quit. Expected before implementing: file missing.
- [ ] **Step 3: Implement** the scripts; paths quoted for spaces.
- [ ] **Step 4: Verify** (a) with Docker Desktop closed, double-clicking `start.bat` launches it and ends with the browser open on the status page; (b) running it a second time succeeds with no changes; (c) occupying port 3000 then running prints a clear port-clash hint and non-zero exit; (d) `reset.bat` + `start.bat` returns to a clean working state; (e) `make up` works in WSL/Linux CI.
- [ ] **Step 5: Commit** `feat(infra): one-click start/stop/reset scripts`.

### Task 7: CI and contribution workflow

**Files:**
- Create: `.github/workflows/ci.yml`, `CONTRIBUTING.md`
- Modify: `README.md` (quick start, repo layout, two-developer split: Dev A backend/platform, Dev B frontend/product)

**Interfaces:**
- Produces: workflow with jobs `backend` (ruff, mypy, pytest using postgres:16 and redis:7 service containers via `TEST_DATABASE_URL`/`TEST_REDIS_URL`), `frontend` (npm ci, lint, tsc, vitest, build), `compose-smoke` (build images, `docker compose up -d`, `wait_for_health.py` on `/api/health/ready`, assert `/api/health/system` scheduler ok within 90 s, dump logs on failure). Triggers: push to any branch, PR to `main`.

- [ ] **Step 1:** write workflow and docs.
- [ ] **Step 2: Run** `git push -u origin m0-foundation`. Expected: all three jobs green.
- [ ] **Step 3: Verify** the required checks (`backend`, `frontend`, `compose-smoke`) are all reported and passing on the PR.
- [ ] **Step 4: Commit** `ci: add backend, frontend and compose smoke workflows; contributing guide`.

### Task 8: Phase completion and merge

**Files:** none new.

- [ ] **Step 1:** on a clean clone (`git clone` into a temp dir), run `start.bat`; confirm status page shows db, redis and scheduler all OK.
- [ ] **Step 2:** run full local suites: `cd backend && pytest -q && ruff check . && mypy src`; `cd frontend && npm test -- --run && npx tsc --noEmit`.
- [ ] **Step 3:** confirm CI is green on the PR; squash-merge into `main`; `git switch main && git pull`; delete the branch.
- [ ] **Step 4:** tag `m0-complete`; push tags; write Plan 2 (M1) before starting M1.

---

## Self-Review

- **Spec coverage:** §4 stack ✔ (T1–T5); §5 processes separate ✔ (T5); §9 `acks_late`/`reject_on_worker_lost`, health endpoints, self-visible scheduler ✔ (T2–T3); §10 one-click Docker, Mailpit, `.env.example`, `start.sh`/Makefile ✔ (T5–T6); §12 M0 repo/Docker/CI/skeletons/OpenAPI client ✔ (T1–T7); §16 git workflow ✔ (T7–T8). Deliberately out of M0: auth, tenancy/RLS roles, outbox, seed script (M1; M0 starts with an empty database, and `start.bat`/`start.sh` get an automatic seed step only when the seed module is implemented in M1).
- **Seeding:** M0 ships no seed step; the scripts and README say the database starts empty. Automatic seeding is introduced with the seed module in M1.
- **Type consistency:** `CheckResult(name, ok, detail)` identical in T2, T3 and the frontend type in T4; `system_heartbeat` defined in T2 migration and used in T3.
- **Proportion:** plan is signatures, tests and verification commands; no function bodies.
