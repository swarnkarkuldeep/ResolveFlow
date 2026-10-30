from resolveflow import retention
from resolveflow.celery_app import celery
from resolveflow.db import system_engine


@celery.task(name="resolveflow.tasks.retention.apply")
def apply() -> int:
    """Redact finished tickets older than each workspace's retention window."""
    return retention.apply_all(system_engine())
