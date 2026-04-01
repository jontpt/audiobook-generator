"""
services/pipeline.py  ─  Core audiobook generation pipeline
────────────────────────────────────────────────────────────
Orchestrates: text extraction → NLP → TTS synthesis → audio mixing → export.
Broadcasts real-time progress over WebSocket (ws_manager).
"""
from __future__ import annotations
import asyncio
import logging
from pathlib import Path
from datetime import datetime

from config import settings
from models.database import db
from models.schemas import ProcessingOptions, ProcessingStatus, ExportFormat
from services.websocket_manager import ws_manager

logger = logging.getLogger(__name__)

# ── Progress constants (cumulative 0→1) ──────────────────────────────────────
_STEPS = {
    "extracting":   (0.00, 0.15),
    "analyzing":    (0.15, 0.40),
    "synthesizing": (0.40, 0.80),
    "mixing":       (0.80, 0.95),
    "finalizing":   (0.95, 1.00),
}


async def _update(book_id: str, status: str, progress: float, message: str = ""):
    """Persist status to DB and broadcast to WebSocket clients."""
    await db.update_by_id(db.books, book_id, {
        "status":   status,
        "progress": round(progress, 3),
        "updated_at": datetime.utcnow().isoformat(),
    })
    await ws_manager.send_progress(book_id, status, progress, message)
    logger.info(f"[{book_id[:8]}] {status} {int(progress*100)}% — {message}")


async def run_pipeline(book_id: str, file_path: Path, options: ProcessingOptions):
    """Main async pipeline coroutine."""
    try:
        await _update(book_id, "extracting", 0.02, "Reading file…")

        # ─── 1. Text extraction ─────────────────────────────────────────────
        from services.text_extraction import extract_text
        chapters_raw = extract_text(file_path)

        if not chapters_raw:
            raise ValueError("No text could be extracted from the uploaded file.")

        total_words = sum(len(c.get("text", "").split()) for c in chapters_raw)
        await db.update_by_id(db.books, book_id, {"total_words": total_words})
        await _update(book_id, "extracting", 0.12,
                      f"Extracted {len(chapters_raw)} chapters, {total_words:,} words")

        # ─── 2. NLP analysis ─────────────────────────────────────────────────
        await _update(book_id, "analyzing", 0.16, "Detecting characters & emotions…")

        from services.nlp_processor import process_chapters
        chapters, characters, segments = process_chapters(chapters_raw, book_id)

        # Persist chapters
        for ch in chapters:
            await db.insert(db.chapters, ch)

        # Persist characters
        for char in characters:
            await db.insert(db.characters, char)

        # Persist segments
        for seg in segments:
            await db.insert(db.segments, seg)

        await db.update_by_id(db.books, book_id, {
            "chapter_count":   len(chapters),
            "character_count": len(characters),
            "segment_count":   len(segments),
        })
        await _update(book_id, "analyzing", 0.38,
                      f"Found {len(characters)} characters, {len(segments)} segments")

        # NEW (fixed)
        # assign_voices returns dict[str, str]: {character_name → voice_id}
        voice_assignment = await asyncio.get_event_loop().run_in_executor(
            None, assign_voices, characters
        )
        # Update each character DB record with its assigned voice_id
        for char in characters:
            char_name = char.get("name", "")
            if char_name in voice_assignment:
                await db.update_by_id(
                    db.characters, char["id"],
                    {"voice_id": voice_assignment[char_name]}
                )


        # ─── 4. TTS synthesis ────────────────────────────────────────────────
        await _update(book_id, "synthesizing", 0.42, "Generating voice audio…")
        voice_id = _resolve_voice(voice_assignment, speaker)
        from services.tts_service import synthesize_segment
        total_segs = len(segments)
        synthesized = 0

        for seg in segments:
            speaker  = seg.get("speaker")
            voice_id = _resolve_voice(characters_updated, speaker)
            audio_path = await asyncio.get_event_loop().run_in_executor(
                None,
                synthesize_segment,
                seg["text"], voice_id, book_id, seg["id"], seg.get("emotion", "neutral"),
            )
            if audio_path:
                await db.update_by_id(db.segments, seg["id"],
                                      {"audio_path": str(audio_path)})
            synthesized += 1
            pct = 0.42 + (synthesized / total_segs) * 0.38
            if synthesized % 5 == 0 or synthesized == total_segs:
                await _update(book_id, "synthesizing", pct,
                              f"Synthesized {synthesized}/{total_segs} segments")

        # ─── 5. Background music (optional) ─────────────────────────────────
        music_tracks: dict[str, Path | None] = {}
        if options.add_background_music:
            await _update(book_id, "mixing", 0.81, "Fetching background music…")
            music_tracks = await _fetch_music(book_id, chapters)

        # ─── 6. Audio mixing ─────────────────────────────────────────────────
        await _update(book_id, "mixing", 0.83, "Assembling chapter audio…")

        from services.audio_mixer import assemble_audiobook
        # Refresh segments with audio paths
        segments_fresh = await db.search(db.segments, "book_id", book_id)

        export_path = await asyncio.get_event_loop().run_in_executor(
            None,
            assemble_audiobook,
            book_id, chapters, segments_fresh, music_tracks,
            str(options.export_format.value), options.music_volume_db,
        )

        await _update(book_id, "mixing", 0.95, "Finalizing export…")

        # ─── 7. Completion ───────────────────────────────────────────────────
        await db.update_by_id(db.books, book_id, {
            "status":      "completed",
            "progress":    1.0,
            "export_path": str(export_path),
            "updated_at":  datetime.utcnow().isoformat(),
        })
        await ws_manager.send_completed(
            book_id,
            export_url=f"/api/v1/export/{book_id}/download",
            duration_str="",
        )
        logger.info(f"✅ Pipeline complete for book {book_id}")

    except Exception as exc:
        logger.error(f"Pipeline failed for {book_id}: {exc}", exc_info=True)
        await db.update_by_id(db.books, book_id, {
            "status":        "failed",
            "error_message": str(exc),
            "updated_at":    datetime.utcnow().isoformat(),
        })
        await ws_manager.send_error(book_id, str(exc))
        raise


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _resolve_voice(characters: list[dict], speaker: str | None) -> str:
    if not speaker:
        return settings.DEFAULT_NARRATOR_VOICE_ID
    for char in characters:
        if char.get("name") == speaker and char.get("voice_id"):
            return char["voice_id"]
    return settings.DEFAULT_NARRATOR_VOICE_ID


async def _fetch_music(book_id: str, chapters: list[dict]) -> dict[str, Path | None]:
    """
    Fetch one music track per unique emotion in the book.
    Reads the user's stored Mubert / Soundraw API keys from the DB.
    """
    from services.music_service import get_background_music
    from api.routes.settings import get_user_api_key

    # Find the book owner's API keys
    book = await db.get_by_id(db.books, book_id)
    user_id = book.get("user_id", "")

    mubert_key   = get_user_api_key(user_id, "mubert")   if user_id else None
    soundraw_key = get_user_api_key(user_id, "soundraw") if user_id else None

    # Fallback to env-level keys
    if not mubert_key:   mubert_key   = getattr(settings, "MUBERT_API_KEY", None) or None
    if not soundraw_key: soundraw_key = getattr(settings, "SOUNDRAW_API_KEY", None) or None

    emotions = list({ch.get("dominant_emotion", "neutral") for ch in chapters})
    result: dict[str, Path | None] = {}
    for emotion in emotions:
        result[emotion] = await get_background_music(
            emotion,
            mubert_api_key=mubert_key,
            soundraw_api_key=soundraw_key,
        )
    return result
