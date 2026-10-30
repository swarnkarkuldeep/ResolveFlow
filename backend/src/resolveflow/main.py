from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from resolveflow.api import audit as audit_api
from resolveflow.api import auth as auth_api
from resolveflow.api import deliveries as deliveries_api
from resolveflow.api import members as members_api
from resolveflow.api import notifications as notifications_api
from resolveflow.api import public as public_api
from resolveflow.api import rules as rules_api
from resolveflow.api import search as search_api
from resolveflow.api import sla as sla_api
from resolveflow.api import teams as teams_api
from resolveflow.api import tickets as tickets_api
from resolveflow.api import webhooks as webhooks_api
from resolveflow.config import get_settings
from resolveflow.db import app_engine
from resolveflow.health import check_db, check_redis, check_scheduler

api = APIRouter(prefix="/api")


class CheckOut(BaseModel):
    name: str
    ok: bool
    detail: str


class SystemOut(BaseModel):
    status: str
    checks: list[CheckOut]


@api.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@api.get("/health/ready")
def ready() -> JSONResponse:
    settings = get_settings()
    checks = [check_db(app_engine()), check_redis(settings.redis_url)]
    ok = all(c.ok for c in checks)
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ready" if ok else "degraded", "checks": [c.to_dict() for c in checks]},
    )


@api.get("/health/system", response_model=SystemOut)
def system() -> SystemOut:
    """Informational: always 200; readiness does not depend on the scheduler."""
    settings = get_settings()
    engine = app_engine()
    checks = [check_db(engine), check_redis(settings.redis_url), check_scheduler(engine)]
    return SystemOut(
        status="ok" if all(c.ok for c in checks) else "degraded",
        checks=[CheckOut(name=c.name, ok=c.ok, detail=c.detail) for c in checks],
    )


app = FastAPI(title="ResolveFlow")
app.include_router(api)
app.include_router(auth_api.router)
app.include_router(audit_api.router)
app.include_router(members_api.router)
app.include_router(public_api.router)
app.include_router(deliveries_api.router)
app.include_router(notifications_api.router)
app.include_router(rules_api.router)
app.include_router(search_api.router)
app.include_router(sla_api.router)
app.include_router(tickets_api.router)
app.include_router(teams_api.router)
app.include_router(webhooks_api.router)
