from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse

from resolveflow.config import get_settings
from resolveflow.db import engine_for
from resolveflow.health import check_db, check_redis

api = APIRouter(prefix="/api")


@api.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@api.get("/health/ready")
def ready() -> JSONResponse:
    settings = get_settings()
    checks = [check_db(engine_for(settings.database_url)), check_redis(settings.redis_url)]
    ok = all(c.ok for c in checks)
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ready" if ok else "degraded", "checks": [c.to_dict() for c in checks]},
    )


app = FastAPI(title="ResolveFlow")
app.include_router(api)
