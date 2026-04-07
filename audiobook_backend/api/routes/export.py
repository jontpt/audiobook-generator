"""
api/routes/export.py — Audiobook export management
"""
from __future__ import annotations
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse

from models.database import db
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/export", tags=["Export"])
ALLOWED_MUSIC_PROVIDERS = {"auto", "mubert", "soundraw", "jamendo"}
ALLOWED_MUSIC_STYLES = {"auto", "ambient", "cinematic", "orchestral", "piano", "electronic"}


@router.post("/{book_id}", response_model=dict)
async def trigger_export(
    book_id: str,
    background_tasks: BackgroundTasks,
    export_format: str = "mp3",
    add_music: bool = False,
    music_volume_db: float = -18.0,   # dB range configured in settings
    music_provider: str = "auto",
    music_style: str = "ambient",
):
    book = await db.get_by_id(db.books, book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    if book.get("status") not in ("completed", "failed"):
        raise HTTPException(409, "Book is still being processed.")
    file_path_str = book.get("file_path")
    if not file_path_str or not Path(file_path_str).exists():
        raise HTTPException(400, "Source file no longer available. Please re-upload.")

    # Clamp to configured safe range so bad client values cannot break mixing.
    music_volume_db = max(
        settings.MUSIC_VOLUME_MIN_DB,
        min(settings.MUSIC_VOLUME_MAX_DB, music_volume_db),
    )
    music_provider = (music_provider or "auto").lower()
    music_style = (music_style or "auto").lower()
    if music_provider not in ALLOWED_MUSIC_PROVIDERS:
        raise HTTPException(422, f"Unsupported music_provider '{music_provider}'")
    if music_style not in ALLOWED_MUSIC_STYLES:
        raise HTTPException(422, f"Unsupported music_style '{music_style}'")

    from models.schemas import ProcessingOptions, ExportFormat
    options = ProcessingOptions(
        export_format=ExportFormat(export_format),
        add_background_music=add_music,
        music_volume_db=music_volume_db,   # ← NEW
        music_type=music_provider,
        music_style=music_style,
    )
    await db.update_by_id(db.books, book_id, {
        "status": "pending", "progress": 0.0,
        "error_message": None, "export_path": None,
    })

    if settings.USE_CELERY:
        from celery_app import process_book_task
        process_book_task.delay(book_id, file_path_str, options.model_dump())
    else:
        background_tasks.add_task(_rerun, book_id, Path(file_path_str), options)

    return {"success": True, "message": "Re-export started", "book_id": book_id}


async def _rerun(book_id: str, file_path: Path, options):
    """
    Re-run the full pipeline for a book.
    Deletes stale segments + chapters first (they'll be regenerated),
    but intentionally keeps character records so user voice choices survive.
    """
    try:
        # Clean stale segments
        for seg in await db.search(db.segments, "book_id", book_id):
            await db.delete_by_id(db.segments, seg["id"])

        # Clean stale chapters
        for ch in await db.search(db.chapters, "book_id", book_id):
            await db.delete_by_id(db.chapters, ch["id"])

        # NOTE: do NOT delete characters — they hold user voice assignments.
        # pipeline.py Step 3 will read them and keep the voice_ids intact.

        from services.pipeline import run_pipeline
        await run_pipeline(book_id, file_path, options)

    except Exception as e:
        logger.error(f"Re-export failed for {book_id}: {e}", exc_info=True)


@router.get("/{book_id}/status", response_model=dict)
async def export_status(book_id: str):
    book = await db.get_by_id(db.books, book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    stats = {}
    if (ep := book.get("export_path")):
        ep = Path(ep)
        if ep.exists():
            from services.audio_mixer import get_audio_stats
            stats = get_audio_stats(ep)
            stats["filename"]     = ep.name
            stats["download_url"] = f"/api/v1/export/{book_id}/download"
    return {
        "book_id":       book_id,
        "title":         book.get("title"),
        "status":        book.get("status"),
        "progress":      book.get("progress", 0),
        "export":        stats or None,
        "error_message": book.get("error_message"),
    }


@router.get("/{book_id}/download")
async def download_audiobook(book_id: str):
    book = await db.get_by_id(db.books, book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    if book.get("status") != "completed":
        raise HTTPException(425, f"Not ready yet. Status: {book.get('status')}")
    ep = Path(book.get("export_path", ""))
    if not ep.exists():
        raise HTTPException(404, "Export file not found")
    media = "audio/mp4" if ep.suffix == ".m4b" else "audio/mpeg"
    return FileResponse(str(ep), media_type=media, filename=ep.name,
                        headers={"Content-Disposition": f'attachment; filename="{ep.name}"'})
