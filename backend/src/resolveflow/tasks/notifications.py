from resolveflow.celery_app import celery
from resolveflow.db import system_engine
from resolveflow.notifications import delivery


@celery.task(name="resolveflow.tasks.notifications.deliver")
def deliver() -> int:
    """Mail queued notifications. Idempotent: rows are claimed with SKIP LOCKED and marked sent."""
    return delivery.deliver_due(system_engine())
