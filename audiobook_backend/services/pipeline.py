"""
services/pipeline.py  ─  Core audiobook generation pipeline
────────────────────────────────────────────────────────────
Orchestrates: text extraction → NLP → TTS synthesis → audio mixing → export.
Broadcasts real-time progress over WebSocket (ws_manager).
"""
from __future__ import annotations
import asyncio
import logging
from functools import partial
from pathlib import Path
from datetime import datetime

import json

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
        # extract_text now returns (chapters, char_declarations)
        chapters_raw, char_declarations, voice_hints = extract_text(file_path)

        if not chapters_raw:
            raise ValueError("No text could be extracted from the uploaded file.")

        # Log declared characters if present
        if char_declarations:
            logger.info(
                f"[{book_id[:8]}] CHARACTERS block found: {list(char_declarations.keys())}"
            )
        if voice_hints:
            logger.info(
                f"[{book_id[:8]}] CHARACTER voice hints found: {list(voice_hints.keys())}"
            )

        total_words = sum(
            sum(len(p.split()) for p in c.get("paragraphs", []))
            for c in chapters_raw
        )
        await db.update_by_id(db.books, book_id, {"total_words": total_words})
        await _update(book_id, "extracting", 0.12,
                      f"Extracted {len(chapters_raw)} chapters, {total_words:,} words"
                      + (f" ({len(char_declarations)} declared chars)" if char_declarations else ""))

        # Optional predeclared voice plan stored at upload time / request.
        book_record = await db.get_by_id(db.books, book_id) or {}
        character_voice_plan = _parse_character_voice_plan(book_record.get("character_voice_plan"))
        # Explicit per-run overrides from API payload take precedence.
        if options.character_voice_overrides:
            character_voice_plan.update(options.character_voice_overrides)

        # ─── 2. NLP analysis ─────────────────────────────────────────────────
        await _update(book_id, "analyzing", 0.16, "Detecting characters & emotions…")

        from services.nlp_processor import process_chapters
        chapters, characters, segments = process_chapters(
            chapters_raw, book_id, char_declarations=char_declarations
        )

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

        # ─── 3. Voice assignment ─────────────────────────────────────────────
        # assign_voices returns dict[str, str]: {character_name → voice_id}
        from services.voice_manager import assign_voices
        voice_assignment = await asyncio.get_event_loop().run_in_executor(
            None, assign_voices, characters, voice_hints
        )
        _apply_character_voice_plan(voice_assignment, characters, character_voice_plan)
        # Update each character DB record with its assigned voice_id
        for char in characters:
            char_name = char.get("name", "")
            if char_name in voice_assignment:
                await db.update_by_id(
                    db.characters, char["id"],
                    {"voice_id": voice_assignment[char_name]}
                )

        # Resolve owner-scoped API keys once for this run.
        user_id = book_record.get("user_id")
        elevenlabs_api_key = None
        if user_id:
            from api.routes.settings import get_user_api_key
            elevenlabs_api_key = get_user_api_key(user_id, "elevenlabs")
            if elevenlabs_api_key:
                logger.info(f"[{book_id[:8]}] Using user-scoped ElevenLabs API key")
        if not elevenlabs_api_key:
            elevenlabs_api_key = settings.ELEVENLABS_API_KEY or None

        # ─── 4. TTS synthesis ────────────────────────────────────────────────
        await _update(book_id, "synthesizing", 0.42, "Generating voice audio…")

        from services.tts_service import synthesize_segment
        total_segs = len(segments)
        synthesized = 0

        for seg in segments:
            speaker  = seg.get("speaker")
            voice_id = _resolve_voice(voice_assignment, speaker)
            synth_call = partial(
                synthesize_segment,
                text=seg["text"],
                voice_id=voice_id,
                book_id=book_id,
                segment_id=seg["id"],
                emotion=seg.get("emotion", "neutral"),
                elevenlabs_api_key=elevenlabs_api_key,
            )
            audio_path = await asyncio.get_event_loop().run_in_executor(
                None,
                synth_call,
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
            music_tracks = await _fetch_music(book_id, chapters, options)

        # ─── 6. Audio mixing ─────────────────────────────────────────────────
        await _update(book_id, "mixing", 0.83, "Assembling chapter audio…")

        from services.audio_mixer import assemble_chapter, merge_chapters
        from types import SimpleNamespace
        from collections import defaultdict
        # Refresh segments with audio paths from DB
        segments_fresh = await db.search(db.segments, "book_id", book_id)

        # Group segments by chapter_index, convert dict → obj for assemble_chapter
        segs_by_chapter: dict[int, list] = defaultdict(list)
        for seg in segments_fresh:
            seg_obj = SimpleNamespace(**seg)
            segs_by_chapter[seg.get("chapter_index", 0)].append(seg_obj)

        # Sort segments within each chapter by segment_index so that
        # paragraph order AND within-paragraph dialogue order are preserved
        # after the DB round-trip (DB does not guarantee insertion order).
        for ch_key in segs_by_chapter:
            segs_by_chapter[ch_key].sort(
                key=lambda s: (getattr(s, "segment_index", 0),
                               getattr(s, "paragraph_index", 0))
            )

        # Assemble each chapter with granular per-segment progress callbacks
        chapter_paths = []
        loop          = asyncio.get_running_loop()
        num_chapters  = max(len(chapters), 1)

        for ch_num, ch in enumerate(chapters):
            ch_idx   = ch.get("index", 0)
            ch_title = ch.get("title", f"Chapter {ch_idx + 1}")
            ch_segs  = segs_by_chapter.get(ch_idx, [])
            music_p  = music_tracks.get(ch.get("dominant_emotion", "neutral"))

            # Progress window for this chapter: 0.83 → 0.93 spread across chapters
            ch_base  = 0.83 + (ch_num / num_chapters) * 0.10
            ch_range = 0.10 / num_chapters

            def _make_progress_cb(base: float, rng: float, bk_id: str):
                """Return a thread-safe callback that fires _update on the event loop."""
                def _cb(done: int, total: int) -> None:
                    frac = done / max(total, 1)
                    prog = base + frac * rng
                    asyncio.run_coroutine_threadsafe(
                        _update(bk_id, "mixing", round(prog, 4),
                                f"Mixing segment {done}/{total}…"),
                        loop,
                    )
                return _cb

            ch_path = await loop.run_in_executor(
                None,
                assemble_chapter,
                ch_segs, ch_title, book_id, ch_idx,
                music_p, options.music_volume_db,
                _make_progress_cb(ch_base, ch_range, book_id),  # progress callback
            )
            if ch_path:
                chapter_paths.append(ch_path)
            await _update(book_id, "mixing",
                          round(0.83 + ((ch_num + 1) / num_chapters) * 0.10, 4),
                          f"Chapter {ch_num + 1}/{num_chapters} mixed")

        # Merge all chapters into the final audiobook file
        await _update(book_id, "mixing", 0.93, "Merging chapters…")
        book_record = await db.get_by_id(db.books, book_id)
        book_title  = book_record.get("title", "Audiobook") if book_record else "Audiobook"
        export_path = await loop.run_in_executor(
            None,
            merge_chapters,
            chapter_paths, book_id, book_title, "AudioBook Generator",
            str(options.export_format.value),
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

def _resolve_voice(voice_assignment: dict[str, str], speaker: str | None) -> str:
    """Look up voice_id from the assignment dict {name: voice_id}."""
    if not speaker:
        return voice_assignment.get("narrator", settings.DEFAULT_NARRATOR_VOICE_ID)
    return voice_assignment.get(
        speaker,
        voice_assignment.get("narrator", settings.DEFAULT_NARRATOR_VOICE_ID)
    )


async def _fetch_music(
    book_id: str,
    chapters: list[dict],
    options: ProcessingOptions,
) -> dict[str, Path | None]:
    """
    Fetch one music track per unique emotion in the book.
    Reads the user's stored Mubert / Soundraw / Jamendo API keys from the DB.
    """
    from services.music_service import get_background_music
    from api.routes.settings import get_user_api_key

    # Find book + owner-scoped API keys
    book = await db.get_by_id(db.books, book_id)
    user_id = book.get("user_id", "")
    preferred_provider = options.music_type or book.get("music_provider_preference", "auto")
    style_preset = options.music_style or book.get("music_style_preset", "auto")

    mubert_key   = get_user_api_key(user_id, "mubert")   if user_id else None
    soundraw_key = get_user_api_key(user_id, "soundraw") if user_id else None
    jamendo_key  = get_user_api_key(user_id, "jamendo")  if user_id else None

    # Fallback to env-level keys
    if not mubert_key:   mubert_key   = getattr(settings, "MUBERT_API_KEY", None) or None
    if not soundraw_key: soundraw_key = getattr(settings, "SOUNDRAW_API_KEY", None) or None
    if not jamendo_key:  jamendo_key  = getattr(settings, "JAMENDO_CLIENT_ID", None) or None

    emotions = list({ch.get("dominant_emotion", "neutral") for ch in chapters})
    result: dict[str, Path | None] = {}
    for emotion in emotions:
        result[emotion] = await get_background_music(
            emotion,
            mubert_api_key=mubert_key,
            soundraw_api_key=soundraw_key,
            jamendo_client_id=jamendo_key,
            music_type=preferred_provider,
            music_style=style_preset,
        )
    return result


def _parse_character_voice_plan(raw_plan) -> dict[str, str]:
    """
    Normalize stored character voice plan payload to {name: voice_id}.
    Supports:
      - {"Archer": "voice_id", ...}
      - [{"character_name": "Archer", "voice_id": "..."}, ...]
      - [{"name": "Archer", "voice_id": "..."}, ...]
    """
    if not raw_plan:
        return {}
    if isinstance(raw_plan, str):
        try:
            raw_plan = json.loads(raw_plan)
        except Exception:
            return {}
    if isinstance(raw_plan, dict):
        # already normalized
        return {str(k): str(v) for k, v in raw_plan.items() if k and v}
    if not isinstance(raw_plan, list):
        return {}
    normalized: dict[str, str] = {}
    for item in raw_plan:
        if not isinstance(item, dict):
            continue
        name = str(item.get("character_name", item.get("name", ""))).strip()
        voice_id = str(item.get("voice_id", "")).strip()
        if name and voice_id:
            normalized[name] = voice_id
    return normalized


def _apply_character_voice_plan(
    voice_assignment: dict[str, str],
    characters: list[dict],
    character_voice_plan: dict[str, str],
) -> None:
    """
    Apply explicit user overrides from pre-processing step.
    Case-insensitive by character name; exact name in assignment is preserved.
    """
    if not character_voice_plan:
        return
    lower_map = {name.lower(): voice_id for name, voice_id in character_voice_plan.items()}
    for char in characters:
        name = str(char.get("name", "")).strip()
        if not name:
            continue
        override = lower_map.get(name.lower())
        if override:
            voice_assignment[name] = override
