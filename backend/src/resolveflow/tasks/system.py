from sqlalchemy import text

from resolveflow.celery_app import celery
from resolveflow.config import get_settings
from resolveflow.db import engine_for


@celery.task(name="resolveflow.tasks.system.heartbeat")
def heartbeat() -> None:
    """Prove beat + worker are alive; idempotent single-row upsert."""
    with engine_for(get_settings().database_url).begin() as conn:
        conn.execute(
            text(
                "INSERT INTO system_heartbeat (id, beat_at) VALUES (1, now()) "
                "ON CONFLICT (id) DO UPDATE SET beat_at = EXCLUDED.beat_at"
            )
        )
