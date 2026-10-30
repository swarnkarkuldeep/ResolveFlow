from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

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
