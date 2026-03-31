"""
celery_app.py  ─  Celery application factory
──────────────────────────────────────────────
Broker:   Redis  (REDIS_URL env var, default redis://localhost:6379/0)
Backend:  Redis  (same URL, database 1)

Tasks:
  process_book_task(book_id, file_path_str, options_dict)
"""
from __future__ import annotations
import asyncio
import logging
from celery import Celery
from config import settings

logger = logging.getLogger(__name__)

celery_app = Celery(
    "audiobook",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL.replace("/0", "/1"),  # use DB 1 for results
    include=["celery_app"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,           # Re-queue on worker crash
    worker_prefetch_multiplier=1,  # One task per worker at a time
    task_routes={
        "celery_app.process_book_task": {"queue": "pipeline"},
    },
    task_default_queue="pipeline",
    beat_schedule={},              # Add scheduled tasks here later
)


@celery_app.task(
    bind=True,
    name="celery_app.process_book_task",
    max_retries=2,
    default_retry_delay=10,
    soft_time_limit=1800,   # 30 min
    time_limit=2100,        # 35 min hard kill
)
def process_book_task(self, book_id: str, file_path_str: str, options_dict: dict):
    """
    Celery task wrapping the async audiobook pipeline.
    Runs in a worker process, uses asyncio.run() to invoke the async pipeline.
    """
    from pathlib import Path
    from models.schemas import ProcessingOptions, ExportFormat

    options = ProcessingOptions(
        add_background_music=options_dict.get("add_background_music", False),
        export_format=ExportFormat(options_dict.get("export_format", "mp3")),
        speech_rate=options_dict.get("speech_rate", 1.0),
        music_volume_db=options_dict.get("music_volume_db", -18.0),
    )
    file_path = Path(file_path_str)

    logger.info(f"[Celery] Starting pipeline for book {book_id}")

    try:
        asyncio.run(_run_pipeline(book_id, file_path, options))
        logger.info(f"[Celery] Pipeline completed for book {book_id}")
    except Exception as exc:
        logger.error(f"[Celery] Pipeline failed for {book_id}: {exc}", exc_info=True)
        # Update DB with failure status
        try:
            from models.database import db
            db.update_by_id_sync(db.books, book_id, {
                "status": "failed",
                "error_message": str(exc),
            })
        except Exception:
            pass
        raise self.retry(exc=exc)


async def _run_pipeline(book_id, file_path, options):
    from services.pipeline import run_pipeline
    await run_pipeline(book_id, file_path, options)
