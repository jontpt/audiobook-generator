"""
api/routes/books.py  ─  Book management + WebSocket progress endpoint
"""
from __future__ import annotations
import uuid
import json
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
from services.radio_markup import summarize_radio_cues

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/books", tags=["Books"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".epub", ".txt"}
MAX_FILE_SIZE_MB = 50
ALLOWED_MUSIC_PROVIDERS = {"auto", "mubert", "soundraw", "jamendo"}
ALLOWED_MUSIC_STYLES = {"auto", "ambient", "cinematic", "orchestral", "electronic", "piano"}


def _slugify_filename_part(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in (value or "").strip())
    return cleaned[:120] or "source"


def _next_revision_title(title: str, revision_number: int) -> str:
    base = (title or "Untitled Book").strip()
    return f"{base} (Rework v{revision_number})"


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _normalize_counts(raw: dict | None) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in raw.items():
        key = str(k).strip().lower()
        if not key:
            continue
        out[key] = _safe_int(v, 0)
    return out


def _normalize_voice_plan(raw: dict | None) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        name = str(k).strip()
        voice_id = str(v).strip()
        if name and voice_id:
            out[name] = voice_id
    return out


def _resolve_rework_source_revision(
    anchor_book: dict,
    revisions: list[dict],
    source_revision_id: str | None,
) -> dict:
    if not source_revision_id:
        return anchor_book
    by_id = {str(r.get("id")): r for r in revisions}
    requested = by_id.get(str(source_revision_id))
    if not requested:
        raise HTTPException(404, "Selected source revision was not found in this chain")
    if str(requested.get("id")) == str(anchor_book.get("id")):
        raise HTTPException(422, "Selected source revision must be different from current revision")
    return requested


def _normalize_music_inputs(music_provider: str, music_style: str) -> tuple[str, str]:
    music_provider = (music_provider or "auto").lower()
    music_style = (music_style or "auto").lower()
    if music_provider not in ALLOWED_MUSIC_PROVIDERS:
        raise HTTPException(422, f"Unsupported music_provider '{music_provider}'")
    if music_style not in ALLOWED_MUSIC_STYLES:
        raise HTTPException(422, f"Unsupported music_style '{music_style}'")
    return music_provider, music_style


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
    music_provider: str = Form(default="auto"),
    music_style: str = Form(default="auto"),
    voice_assignments_json: str = Form(default=""),
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
    music_provider, music_style = _normalize_music_inputs(music_provider, music_style)
    voice_assignments = _parse_voice_assignments(voice_assignments_json)

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
        music_provider_preference=music_provider,
        music_style_preset=music_style,
        character_voice_plan=voice_assignments,
    )
    await db.insert(db.books, book.model_dump())
    logger.info(f"Book uploaded: {book.title} ({size_mb:.2f} MB, music={add_music}, vol={music_volume_db}dB)")

    from models.schemas import ProcessingOptions, ExportFormat
    options = ProcessingOptions(
        add_background_music=add_music,
        export_format=ExportFormat(export_format),
        music_volume_db=music_volume_db,   # ← NEW
        music_type=music_provider,
        music_style=music_style,
        character_voice_overrides=voice_assignments,
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


@router.post("/start-with-voices", response_model=dict, status_code=202)
async def start_with_voices(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str = Form(default=""),
    author: str = Form(default=""),
    add_music: bool = Form(default=False),
    export_format: str = Form(default="mp3"),
    music_volume_db: float = Form(default=-18.0),
    music_provider: str = Form(default="auto"),
    music_style: str = Form(default="auto"),
    voice_assignments_json: str = Form(default="[]"),
    current_user: dict = Depends(get_current_user),
):
    """
    Explicit entrypoint for two-step UX:
      1) parse-characters
      2) start-with-voices
    Uses exactly the same pipeline as /upload, but expects assignment payload.
    """
    # Validate requested music controls here too, so this endpoint behaves exactly
    # like /upload for option validation and errors.
    music_provider, music_style = _normalize_music_inputs(music_provider, music_style)

    return await upload_book(
        background_tasks=background_tasks,
        file=file,
        title=title,
        author=author,
        add_music=add_music,
        export_format=export_format,
        music_volume_db=music_volume_db,
        music_provider=music_provider,
        music_style=music_style,
        voice_assignments_json=voice_assignments_json,
        current_user=current_user,
    )


@router.post("/parse-characters", response_model=dict)
async def parse_characters(
    file: UploadFile = File(...),
    title: str = Form(default=""),
    author: str = Form(default=""),
):
    """
    Parse the uploaded file and return a draft character list + suggested voices.
    This endpoint does not start synthesis; it powers a pre-processing review step.
    """
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(415, f"Unsupported file type '{ext}'. Allowed: {ALLOWED_EXTENSIONS}")

    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(413, f"File too large ({size_mb:.1f} MB). Max: {MAX_FILE_SIZE_MB} MB")

    temp_path = settings.UPLOAD_DIR / f"preview_{uuid.uuid4().hex}{ext}"
    temp_path.write_bytes(content)
    try:
        from services.text_extraction import extract_text
        from services.nlp_processor import process_chapters
        from services.voice_manager import assign_voices

        chapters_raw, char_declarations, voice_hints = extract_text(temp_path)
        preview_book_id = f"preview_{uuid.uuid4().hex}"
        _, characters, _ = process_chapters(
            chapters_raw, preview_book_id, char_declarations=char_declarations
        )
        suggested = assign_voices(characters, voice_hints)
        for char in characters:
            name = char.get("name")
            if name and name in suggested:
                char["voice_id"] = suggested[name]
        characters = sorted(characters, key=lambda c: -c.get("appearance_count", 0))
        return {
            "success": True,
            "characters": characters,
            "suggestions_count": len(suggested),
        }
    finally:
        temp_path.unlink(missing_ok=True)


@router.post("/preview-radio-cues", response_model=dict)
async def preview_radio_cues(
    file: UploadFile = File(...),
):
    """
    Parse radio-play markup directives from uploaded text and return cue preview.
    This does not start pipeline processing.
    """
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(415, f"Unsupported file type '{ext}'. Allowed: {ALLOWED_EXTENSIONS}")

    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(413, f"File too large ({size_mb:.1f} MB). Max: {MAX_FILE_SIZE_MB} MB")

    temp_path = settings.UPLOAD_DIR / f"cue_preview_{uuid.uuid4().hex}{ext}"
    temp_path.write_bytes(content)
    try:
        from services.text_extraction import extract_text
        from services.radio_markup import parse_radio_markup, lint_radio_markup, summarize_lint_issues

        chapters_raw, _, _ = extract_text(temp_path)
        _, cues = parse_radio_markup(chapters_raw)
        cue_counts = summarize_radio_cues(cues)
        lint_issues = lint_radio_markup(chapters_raw, cues)
        lint_counts = summarize_lint_issues(lint_issues)
        return {
            "success": True,
            "cues": cues,
            "cue_counts": cue_counts,
            "lint_issues": lint_issues,
            "lint_counts": lint_counts,
            "chapter_count": len(chapters_raw),
        }
    finally:
        temp_path.unlink(missing_ok=True)


async def _run_pipeline_bg(book_id: str, file_path: Path, options):
    try:
        from services.pipeline import run_pipeline
        await run_pipeline(book_id, file_path, options)
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)


def _parse_voice_assignments(raw: str) -> dict[str, str]:
    """
    Parse JSON voice assignment payload in shape:
      [{ "character_name": "Archer", "voice_id": "..." }, ...]
    and return dict[str, str].
    """
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, f"Invalid voice_assignments_json: {exc.msg}") from exc
    if not isinstance(parsed, list):
        raise HTTPException(422, "voice_assignments_json must be a JSON array")
    result: dict[str, str] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        name = str(item.get("character_name", "")).strip()
        voice_id = str(item.get("voice_id", "")).strip()
        if name and voice_id:
            result[name] = voice_id
    return result


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
    root_id = book.get("root_book_id") or book.get("id")
    revisions = await _get_revisions_for_root(root_id)
    return {
        **_sanitize(book),
        "characters": characters,
        "chapters":   sorted(chapters, key=lambda c: c.get("index", 0)),
        "revisions": revisions,
    }


@router.get("/{book_id}/revisions", response_model=list)
async def list_revisions(book_id: str, current_user: dict = Depends(get_current_user)):
    book = await _get_or_404(book_id)
    if current_user.get("id") and book.get("user_id") not in {None, current_user.get("id")}:
        raise HTTPException(403, "Not authorized to view revisions for this book")
    root_id = book.get("root_book_id") or book.get("id")
    return await _get_revisions_for_root(root_id)


@router.get("/{book_id}/revisions/diff", response_model=dict)
async def get_revision_diff(
    book_id: str,
    base_revision_id: str | None = None,
    compare_revision_id: str | None = None,
    current_user: dict = Depends(get_current_user),
):
    anchor_book = await _get_or_404(book_id)
    if current_user.get("id") and anchor_book.get("user_id") not in {None, current_user.get("id")}:
        raise HTTPException(403, "Not authorized to view revisions for this book")

    root_id = anchor_book.get("root_book_id") or anchor_book.get("id")
    revisions = await _get_revisions_for_root(root_id)
    by_id = {r.get("id"): r for r in revisions}

    compare_book = by_id.get(compare_revision_id) if compare_revision_id else anchor_book
    if not compare_book:
        raise HTTPException(404, "Compare revision not found in this version chain")

    if base_revision_id:
        base_book = by_id.get(base_revision_id)
        if not base_book:
            raise HTTPException(404, "Base revision not found in this version chain")
    else:
        compare_rev = _safe_int(compare_book.get("revision_number"), 1)
        previous = [
            rev for rev in revisions
            if _safe_int(rev.get("revision_number"), 1) < compare_rev
        ]
        if not previous:
            raise HTTPException(404, "No previous revision available for comparison")
        previous.sort(key=lambda r: _safe_int(r.get("revision_number"), 1))
        base_book = previous[-1]

    if str(base_book.get("id")) == str(compare_book.get("id")):
        raise HTTPException(422, "Choose two different revisions for comparison")

    diff = _compute_revision_diff(base_book, compare_book)
    return {
        "success": True,
        "root_book_id": root_id,
        "base": _book_brief(base_book),
        "compare": _book_brief(compare_book),
        "diff": diff,
    }


@router.post("/{book_id}/rework", response_model=dict, status_code=202)
async def create_rework_revision(
    book_id: str,
    background_tasks: BackgroundTasks,
    source_revision_id: str | None = None,
    current_user: dict = Depends(get_current_user),
):
    anchor_book = await _get_or_404(book_id)
    owner_id = anchor_book.get("user_id")
    current_user_id = current_user.get("id")
    if owner_id and owner_id != current_user_id:
        raise HTTPException(403, "Not authorized to create rework version for this book")

    root_id = anchor_book.get("root_book_id") or anchor_book.get("id")
    revisions = await _get_revisions_for_root(root_id)
    source_book = _resolve_rework_source_revision(anchor_book, revisions, source_revision_id)

    source_file = source_book.get("file_path")
    if not source_file or not Path(source_file).exists():
        raise HTTPException(409, "Source file is not available for rework")

    max_revision = max((int(r.get("revision_number", 1) or 1) for r in revisions), default=1)
    new_revision_number = max_revision + 1

    source_ext = Path(source_file).suffix.lower()
    if source_ext and source_ext not in ALLOWED_EXTENSIONS:
        source_ext = f".{(source_book.get('file_type') or 'txt').strip('.')}"
    if not source_ext:
        source_ext = ".txt"

    rework_book_id = str(uuid.uuid4())
    source_stem = _slugify_filename_part(Path(source_file).stem)
    cloned_upload = settings.UPLOAD_DIR / f"{rework_book_id}_{source_stem}{source_ext}"
    cloned_upload.write_bytes(Path(source_file).read_bytes())

    music_provider = (source_book.get("music_provider_preference") or "auto").lower()
    music_style = (source_book.get("music_style_preset") or "auto").lower()
    music_provider, music_style = _normalize_music_inputs(music_provider, music_style)

    cloned_book = Book(
        id=rework_book_id,
        user_id=owner_id or current_user_id,
        title=_next_revision_title(source_book.get("title") or "Untitled Book", new_revision_number),
        author=source_book.get("author") or "Unknown",
        file_path=str(cloned_upload),
        file_type=(source_book.get("file_type") or source_ext.lstrip(".") or "txt"),
        status=ProcessingStatus.PENDING,
        progress=0.0,
        music_provider_preference=music_provider,
        music_style_preset=music_style,
        character_voice_plan=(source_book.get("character_voice_plan") or {}),
        parent_book_id=source_book.get("id"),
        root_book_id=root_id,
        revision_number=new_revision_number,
    )
    await db.insert(db.books, cloned_book.model_dump())

    from models.schemas import ProcessingOptions, ExportFormat
    options = ProcessingOptions(
        add_background_music=False,
        export_format=ExportFormat.MP3,
        music_volume_db=float(source_book.get("music_volume_db", -18.0) or -18.0),
        music_type=music_provider,
        music_style=music_style,
        character_voice_overrides=(source_book.get("character_voice_plan") or {}),
    )

    if settings.USE_CELERY:
        from celery_app import process_book_task
        process_book_task.delay(rework_book_id, str(cloned_upload), options.model_dump())
    else:
        background_tasks.add_task(_run_pipeline_bg, rework_book_id, cloned_upload, options)

    return {
        "success": True,
        "message": "Rework version created and processing started.",
        "book_id": rework_book_id,
        "root_book_id": root_id,
        "source_revision_id": source_book.get("id"),
        "parent_book_id": source_book.get("id"),
        "revision_number": new_revision_number,
        "title": cloned_book.title,
        "ws_url": f"/api/v1/books/{rework_book_id}/ws",
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


async def _get_revisions_for_root(root_id: str) -> list[dict]:
    all_books = await db.get_all(db.books)
    revisions = [
        _sanitize(b)
        for b in all_books
        if (b.get("root_book_id") or b.get("id")) == root_id
    ]
    revisions.sort(
        key=lambda b: (
            int(b.get("revision_number", 1) or 1),
            str(b.get("created_at", "")),
        )
    )
    return revisions


def _book_brief(book: dict) -> dict:
    return {
        "id": book.get("id"),
        "title": book.get("title"),
        "author": book.get("author"),
        "status": book.get("status"),
        "progress": book.get("progress", 0),
        "revision_number": _safe_int(book.get("revision_number"), 1),
        "parent_book_id": book.get("parent_book_id"),
        "root_book_id": book.get("root_book_id") or book.get("id"),
        "created_at": book.get("created_at"),
        "updated_at": book.get("updated_at"),
        "chapter_count": _safe_int(book.get("chapter_count"), 0),
        "character_count": _safe_int(book.get("character_count"), 0),
        "segment_count": _safe_int(book.get("segment_count"), 0),
        "total_words": _safe_int(book.get("total_words"), 0),
    }


def _compute_revision_diff(base_book: dict, compare_book: dict) -> dict:
    metric_fields = ("chapter_count", "character_count", "segment_count", "total_words")
    metrics: dict[str, dict[str, int]] = {}
    for field in metric_fields:
        base_val = _safe_int(base_book.get(field), 0)
        compare_val = _safe_int(compare_book.get(field), 0)
        metrics[field] = {
            "base": base_val,
            "compare": compare_val,
            "delta": compare_val - base_val,
        }

    settings_changes: list[dict] = []
    settings_map = {
        "music_provider_preference": "Music provider",
        "music_style_preset": "Music style",
    }
    for field, label in settings_map.items():
        before = str(base_book.get(field) or "auto")
        after = str(compare_book.get(field) or "auto")
        if before != after:
            settings_changes.append({
                "field": field,
                "label": label,
                "base": before,
                "compare": after,
            })

    base_voices = _normalize_voice_plan(base_book.get("character_voice_plan"))
    compare_voices = _normalize_voice_plan(compare_book.get("character_voice_plan"))
    base_names = set(base_voices.keys())
    compare_names = set(compare_voices.keys())
    added_characters = sorted(compare_names - base_names)
    removed_characters = sorted(base_names - compare_names)
    changed_voices = sorted(
        [
            {
                "character": name,
                "base_voice_id": base_voices[name],
                "compare_voice_id": compare_voices[name],
            }
            for name in (base_names & compare_names)
            if base_voices[name] != compare_voices[name]
        ],
        key=lambda item: item["character"].lower(),
    )

    base_cues = _normalize_counts(base_book.get("radio_cue_counts"))
    compare_cues = _normalize_counts(compare_book.get("radio_cue_counts"))
    cue_delta: dict[str, int] = {}
    for cue_type in sorted(set(base_cues.keys()) | set(compare_cues.keys())):
        delta = compare_cues.get(cue_type, 0) - base_cues.get(cue_type, 0)
        if delta != 0:
            cue_delta[cue_type] = delta

    return {
        "metrics": metrics,
        "settings_changes": settings_changes,
        "voice_plan": {
            "base_count": len(base_voices),
            "compare_count": len(compare_voices),
            "added_characters": added_characters,
            "removed_characters": removed_characters,
            "changed_voices": changed_voices,
        },
        "cue_counts": {
            "base": base_cues,
            "compare": compare_cues,
            "delta": cue_delta,
        },
        "has_changes": bool(
            any(m["delta"] != 0 for m in metrics.values())
            or settings_changes
            or added_characters
            or removed_characters
            or changed_voices
            or cue_delta
        ),
    }


def _sanitize(book: dict) -> dict:
    return {k: v for k, v in book.items() if k != "file_path"}
