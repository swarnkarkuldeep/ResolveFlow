from datetime import datetime

from celery.signals import worker_ready

from resolveflow.celery_app import celery
from resolveflow.db import system_engine
from resolveflow.sla import sweeper


@celery.task(name="resolveflow.tasks.sla.sweep")
def sweep(now: str | None = None) -> dict[str, int]:
    """Warn/breach detection. Safe to run any number of times, anywhere, at any moment."""
    result = sweeper.sweep(system_engine(), now=datetime.fromisoformat(now) if now else None)
    return {
        "thresholds": result.thresholds,
        "recomputed": result.recomputed,
        "backfilled": result.backfilled,
    }


@worker_ready.connect
def sweep_on_start(**_: object) -> None:
    """Catch up immediately after a restart instead of waiting for the first beat tick."""
    sweep.delay()
