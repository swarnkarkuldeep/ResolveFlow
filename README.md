# ResolveFlow

Customer support & SLA automation for small service teams: a shared inbox with ticket assignment, priority rules, transparent SLA tracking, escalation alerts, testable automation rules and searchable history.

**Status:** M0 foundation (runnable skeleton). Product features arrive in M1鈥揗5.

## Quick start (Windows + Docker Desktop)
Double-click `start.bat`. It starts Docker Desktop if needed, builds and starts everything, waits until the API is healthy and opens http://localhost:3000. Mailpit (captured outgoing email) is at http://localhost:8025.

- `stop.bat` stops the stack; `reset.bat` also **deletes all data**.
- Linux/macOS/WSL: `./start.sh` or `make up`.
- On first start the API seeds a **synthetic demo workspace** (Brightwork Studio, ~60 tickets). Sign in as `owner@brightwork.test`, `admin@卄, `agent@卄 or `viewer@卄 with password `resolveflow-demo`. Seeding only runs when no workspace exists.
- Ports are configurable in `.env` (host ports bind to 127.0.0.1 only; the DB is on 5433 to avoid clashing with a local Postgres) (copied from `.env.example` on first run).

## Layout
`backend/` FastAPI + Celery (Python 3.12) 路 `frontend/` React + TypeScript 路 `docker-compose.yml` 路 `scripts/` 路 `docs/` (PRD, design, plans)

- [PRD](docs/PRD.md) 路 [Design](docs/superpowers/specs/2026-10-30-resolveflow-design.md) 路 [M0 plan](docs/superpowers/plans/2026-10-30-m0-foundation.md) 路 [Contributing](CONTRIBUTING.md)
