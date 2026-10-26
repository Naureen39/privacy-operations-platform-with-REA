"""The Celery application. Configure it from the settings with `configure()`."""

from celery import Celery
from celery.schedules import crontab

from app.core.config import Settings, get_settings

celery_app = Celery("processledger", include=["app.workers.tasks"])


def configure(settings: Settings | None = None) -> Celery:
    settings = settings or get_settings()
    celery_app.conf.update(
        broker_url=settings.celery_broker_url,
        result_backend=settings.celery_result_backend or settings.celery_broker_url,
        task_always_eager=settings.celery_eager,
        task_eager_propagates=False,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        broker_connection_retry_on_startup=True,
        broker_connection_timeout=3,
        task_publish_retry_policy={
            "max_retries": 2,
            "interval_start": 0,
            "interval_step": 0.3,
            "interval_max": 1,
        },
        task_ignore_result=True,
        beat_schedule={
            "review-reminders-daily": {
                "task": "workflow.review_reminders_all",
                "schedule": crontab(hour=6, minute=0),
            }
        },
    )
    return celery_app


configure()
