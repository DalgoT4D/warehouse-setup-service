from celery import Celery
from app.core.config import settings

# Create Celery instance
celery_app = Celery(
    "warehouse_tasks",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks.terraform"]
)

# Configure Celery
celery_app.conf.task_routes = {
    "app.tasks.terraform.*": {"queue": "terraform"},
}

celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
) 