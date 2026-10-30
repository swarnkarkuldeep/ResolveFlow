from celery import Celery

from resolveflow.config import get_settings

_settings = get_settings()

celery = Celery(
    "resolveflow",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
    include=[
        "resolveflow.tasks.system",
        "resolveflow.tasks.email",
        "resolveflow.tasks.sla",
        "resolveflow.tasks.notifications",
    ],
)
celery.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    timezone="UTC",
    beat_schedule={
        "heartbeat": {"task": "resolveflow.tasks.system.heartbeat", "schedule": 30.0},
        "sla-sweep": {"task": "resolveflow.tasks.sla.sweep", "schedule": 60.0},
        "deliver-notifications": {
            "task": "resolveflow.tasks.notifications.deliver",
            "schedule": 30.0,
        },
        "requeue-stuck-outbound": {
            "task": "resolveflow.tasks.email.requeue_stuck_outbound",
            "schedule": 60.0,
        },
    },
)
