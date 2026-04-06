"""
api/routes/books.py  ─  Book management + WebSocket progress endpoint
"""
from __future__ import annotations
import uuid
import logging
import asyncio
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Form, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import JSONResponse

from config import settings
from models.schemas import Book, ProcessingStatus
from models.database import db
from api.routes.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/books", tags=["Books"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".epub", ".txt"}
MAX_FILE_SIZE_MB = 50


# ─── Upload ────────────────────────────────────────────────────────────────────

@router.post("/upload", response_model=dict, status_code=202)
async def upload_book(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str = Form(default=""),
    author: str = Form(default=""),
    add_music: bool = Form(default=False),
    export_format: str = Form(default="mp3"),
    music_volume_db: float = Form(default=-18.0),   # dB range configured in settings
    current_user: dict = Depends(get_current_user),
):
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(415, f"Unsupported file type '{ext}'. Allowed: {ALLOWED_EXTENSIONS}")

    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(413, f"File too large ({size_mb:.1f} MB). Max: {MAX_FILE_SIZE_MB} MB")

    # Clamp to configured safe range so bad client values cannot break mixing.
    music_volume_db = max(
        settings.MUSIC_VOLUME_MIN_DB,
        min(settings.MUSIC_VOLUME_MAX_DB, music_volume_db),
    )

    book_id   = str(uuid.uuid4())
    safe_name = f"{book_id}{ext}"
    upload_path = settings.UPLOAD_DIR / safe_name
    upload_path.write_bytes(content)

    book = Book(
        id=book_id,
        user_id=current_user.get("id"),
        title=title or Path(file.filename).stem.replace("_", " ").replace("-", " ").title(),
        author=author or "Unknown",
        file_path=str(upload_path),
        file_type=ext.lstrip("."),
        status=ProcessingStatus.PENDING,
    )
    await db.insert(db.books, book.model_dump())
    logger.info(f"Book uploaded: {book.title} ({size_mb:.2f} MB, music={add_music}, vol={music_volume_db}dB)")

    from models.schemas import ProcessingOptions, ExportFormat
    options = ProcessingOptions(
        add_background_music=add_music,
        export_format=ExportFormat(export_format),
        music_volume_db=music_volume_db,   # ← NEW
    )

    # Dispatch to Celery if configured, else use BackgroundTasks
    if settings.USE_CELERY:
        from celery_app import process_book_task
        process_book_task.delay(book_id, str(upload_path), options.model_dump())
    else:
        background_tasks.add_task(_run_pipeline_bg, book_id, upload_path, options)

    return {
        "success":      True,
        "message":      "Book uploaded — processing has started.",
        "book_id":      book_id,
        "title":        book.title,
        "file_type":    book.file_type,
        "file_size_mb": round(size_mb, 2),
        "ws_url":       f"/api/v1/books/{book_id}/ws",
    }


async def _run_pipeline_bg(book_id: str, file_path: Path, options):
    try:
        from services.pipeline import run_pipeline
        await run_pipeline(book_id, file_path, options)
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)


# ─── WebSocket progress ────────────────────────────────────────────────────────

@router.websocket("/{book_id}/ws")
async def book_progress_ws(websocket: WebSocket, book_id: str):
    """
    WebSocket endpoint for real-time pipeline progress.
    Connect immediately after upload; receives JSON messages:
      { type: "progress", status, progress, message }
      { type: "completed", export_url, duration }
      { type: "error", error }
    """
    from services.websocket_manager import ws_manager
    await ws_manager.connect(book_id, websocket)

    # Send current state immediately on connect
    book = await db.get_by_id(db.books, book_id)
    if book:
        await websocket.send_json({
            "type":     "progress",
            "book_id":  book_id,
            "status":   book.get("status"),
            "progress": book.get("progress", 0),
            "message":  "Connected",
        })

    try:
        while True:
            # Keep connection alive; client can send pings if needed
            data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
            if data == "ping":
                await websocket.send_text("pong")
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    finally:
        await ws_manager.disconnect(book_id, websocket)


# ─── REST endpoints ────────────────────────────────────────────────────────────

@router.get("", response_model=list)
async def list_books():
    books = await db.get_all(db.books)
    return [_sanitize(b) for b in books]


@router.get("/{book_id}", response_model=dict)
async def get_book(book_id: str):
    book = await _get_or_404(book_id)
    characters = await db.search(db.characters, "book_id", book_id)
    chapters   = await db.search(db.chapters,   "book_id", book_id)
    return {
        **_sanitize(book),
        "characters": characters,
        "chapters":   sorted(chapters, key=lambda c: c.get("index", 0)),
    }


@router.get("/{book_id}/progress", response_model=dict)
async def get_progress(book_id: str):
    book = await _get_or_404(book_id)
    return {
        "book_id":       book_id,
        "status":        book.get("status"),
        "progress":      book.get("progress", 0),
        "error_message": book.get("error_message"),
        "title":         book.get("title"),
        "ws_url":        f"/api/v1/books/{book_id}/ws",
    }


@router.get("/{book_id}/segments", response_model=list)
async def get_segments(book_id: str, chapter_index: int = None):
    await _get_or_404(book_id)
    segments = await db.search(db.segments, "book_id", book_id)
    if chapter_index is not None:
        segments = [s for s in segments if s.get("chapter_index") == chapter_index]
    return sorted(segments, key=lambda s: (
        s.get("chapter_index", 0),
        s.get("segment_index", s.get("paragraph_index", 0)),
    ))


@router.delete("/{book_id}", response_model=dict)
async def delete_book(book_id: str):
    book = await _get_or_404(book_id)
    for path_key in ("file_path", "export_path"):
        if (p := book.get(path_key)):
            Path(p).unlink(missing_ok=True)
    import shutil
    for d in [settings.AUDIO_DIR / book_id, settings.EXPORT_DIR / book_id]:
        if d.exists():
            shutil.rmtree(str(d), ignore_errors=True)
    await db.delete_by_id(db.books, book_id)
    for seg  in await db.search(db.segments,   "book_id", book_id): await db.delete_by_id(db.segments,   seg["id"])
    for ch   in await db.search(db.chapters,   "book_id", book_id): await db.delete_by_id(db.chapters,   ch["id"])
    for char in await db.search(db.characters, "book_id", book_id): await db.delete_by_id(db.characters, char["id"])
    return {"success": True, "message": f"Book {book_id} deleted"}


# ─── Helpers ───────────────────────────────────────────────────────────────────

async def _get_or_404(book_id: str) -> dict:
    book = await db.get_by_id(db.books, book_id)
    if not book:
        raise HTTPException(404, f"Book '{book_id}' not found")
    return book

def _sanitize(book: dict) -> dict:
    return {k: v for k, v in book.items() if k != "file_path"}
