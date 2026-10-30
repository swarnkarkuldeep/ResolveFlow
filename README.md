# ResolveFlow

Customer support & SLA automation for small service teams: a shared inbox with ticket assignment, priority rules, transparent SLA tracking, escalation alerts, testable automation rules and searchable history.

**Status:** M0 foundation (runnable skeleton). Product features arrive in M1–M5.

## Quick start (Windows + Docker Desktop)
Double-click `start.bat`. It starts Docker Desktop if needed, builds and starts everything, waits until the API is healthy and opens http://localhost:3000. Mailpit (captured outgoing email) is at http://localhost:8025.

- `stop.bat` stops the stack; `reset.bat` also **deletes all data**.
- Linux/macOS/WSL: `./start.sh` or `make up`.
- The database starts **empty**. Automatic seeding with demo data arrives with the seed module in M1.
- Ports are configurable in `.env` (copied from `.env.example` on first run).

## Layout
`backend/` FastAPI + Celery (Python 3.12) · `frontend/` React + TypeScript · `docker-compose.yml` · `scripts/` · `docs/` (PRD, design, plans)

- [PRD](docs/PRD.md) · [Design](docs/superpowers/specs/2026-10-30-resolveflow-design.md) · [M0 plan](docs/superpowers/plans/2026-10-30-m0-foundation.md) · [Contributing](CONTRIBUTING.md)
