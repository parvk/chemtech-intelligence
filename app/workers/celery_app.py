from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "chemtech-intelligence",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.synthesis_worker"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=settings.job_timeout_seconds + 30,
    task_soft_time_limit=settings.job_timeout_seconds,
    worker_prefetch_multiplier=1,  # one task at a time - GPU contention
    task_acks_late=True,
)
