from fastapi import APIRouter, FastAPI

api = APIRouter(prefix="/api")


@api.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


app = FastAPI(title="ResolveFlow")
app.include_router(api)
