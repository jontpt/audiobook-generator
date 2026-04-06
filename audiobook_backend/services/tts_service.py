"""
services/tts_service.py
ElevenLabs TTS integration with:
  - Per-segment synthesis
  - Retry logic with exponential back-off
  - Audio caching (same text + voice_id = same file)
  - Graceful degradation (mock mode when no API key configured)
"""
from __future__ import annotations
import hashlib
import logging
import time
import asyncio
from pathlib import Path
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)

AUDIO_DIR: Path = settings.AUDIO_DIR
MOCK_AUDIO_BYTES = b"MOCK_AUDIO"   # Returned when API key not set


# ─────────────────────────────────────────────────────────────────────────────
# Cache helpers
# ─────────────────────────────────────────────────────────────────────────────

def _cache_key(text: str, voice_id: str, model_id: str, emotion: str, key_mode: str) -> str:
    content = f"{text}|{voice_id}|{model_id}|{emotion}|{key_mode}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _cached_path(cache_key: str, book_id: str) -> Path:
    book_dir = AUDIO_DIR / book_id
    book_dir.mkdir(parents=True, exist_ok=True)
    return book_dir / f"{cache_key}.mp3"


def _is_cached(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


# ─────────────────────────────────────────────────────────────────────────────
# Mock TTS (no API key)
# ─────────────────────────────────────────────────────────────────────────────

def _generate_mock_audio(text: str, output_path: Path) -> Path:
    """
    Generate a tiny silent MP3 stub so the pipeline can continue
    without a real API key (useful for testing).
    Uses pydub to create actual silent audio proportional to text length.
    """
    try:
        from pydub import AudioSegment
        # 80ms per word, minimum 500ms
        words = len(text.split())
        duration_ms = max(500, words * 80)
        silence = AudioSegment.silent(duration=duration_ms)
        silence.export(str(output_path), format="mp3")
        logger.debug(f"Mock audio: {duration_ms}ms for '{text[:30]}...'")
        return output_path
    except Exception as e:
        # Ultimate fallback: write raw bytes
        logger.warning(f"pydub unavailable for mock audio: {e}")
        output_path.write_bytes(b"")
        return output_path


# ─────────────────────────────────────────────────────────────────────────────
# ElevenLabs TTS
# ─────────────────────────────────────────────────────────────────────────────

def _build_voice_settings(emotion: str) -> dict:
    """Tune voice settings based on scene emotion."""
    presets = {
        "happy":      {"stability": 0.35, "similarity_boost": 0.75, "style": 0.60},
        "sad":        {"stability": 0.55, "similarity_boost": 0.80, "style": 0.30},
        "suspense":   {"stability": 0.25, "similarity_boost": 0.70, "style": 0.70},
        "dramatic":   {"stability": 0.20, "similarity_boost": 0.75, "style": 0.80},
        "romantic":   {"stability": 0.45, "similarity_boost": 0.80, "style": 0.50},
        "action":     {"stability": 0.20, "similarity_boost": 0.70, "style": 0.80},
        "mysterious": {"stability": 0.40, "similarity_boost": 0.75, "style": 0.60},
        "peaceful":   {"stability": 0.65, "similarity_boost": 0.80, "style": 0.20},
        "neutral":    {"stability": 0.50, "similarity_boost": 0.75, "style": 0.0},
    }
    return presets.get(emotion, presets["neutral"])


def synthesize_segment(
    text: str,
    voice_id: str,
    book_id: str,
    segment_id: str,
    emotion: str = "neutral",
    model_id: str = None,
    elevenlabs_api_key: Optional[str] = None,
    max_retries: int = 3,
) -> Path:
    """
    Synthesize a single text segment to an MP3 file.
    Returns the path to the saved audio file.
    """
    model_id = model_id or settings.ELEVENLABS_MODEL_ID

    # Allow per-request key override (user key), fallback to env-level key.
    active_api_key = elevenlabs_api_key or settings.ELEVENLABS_API_KEY
    key_mode = "real" if active_api_key else "mock"

    cache_key = _cache_key(text, voice_id, model_id, emotion, key_mode)
    out_path = _cached_path(cache_key, book_id)

    # Return from cache if available
    if _is_cached(out_path):
        logger.debug(f"Cache hit for segment {segment_id}")
        return out_path

    # No API key → mock mode
    if not active_api_key:
        logger.warning("No ELEVENLABS_API_KEY set — using mock TTS audio")
        return _generate_mock_audio(text, out_path)

    voice_settings = _build_voice_settings(emotion)

    for attempt in range(1, max_retries + 1):
        try:
            from elevenlabs.client import ElevenLabs
            from elevenlabs import VoiceSettings
            client = ElevenLabs(api_key=active_api_key)

            audio_iterator = client.text_to_speech.convert(
                text=text,
                voice_id=voice_id,
                model_id=model_id,
                voice_settings=VoiceSettings(
                    stability=voice_settings["stability"],
                    similarity_boost=voice_settings["similarity_boost"],
                    style=voice_settings.get("style", 0.0),
                    use_speaker_boost=True,
                ),
                output_format="mp3_44100_128",
            )

            # Write streamed bytes
            with open(out_path, "wb") as f:
                for chunk in audio_iterator:
                    if chunk:
                        f.write(chunk)

            logger.info(
                f"Synthesized segment {segment_id} "
                f"({len(text)} chars, voice={voice_id}, emotion={emotion})"
            )
            return out_path

        except Exception as e:
            err_str = str(e)
            if "rate_limit" in err_str.lower() or "429" in err_str:
                wait = 2 ** attempt
                logger.warning(f"Rate limited. Retrying in {wait}s (attempt {attempt}/{max_retries})")
                time.sleep(wait)
            elif attempt == max_retries:
                logger.error(f"TTS failed for segment {segment_id} after {max_retries} attempts: {e}")
                # Fallback to mock so pipeline continues
                return _generate_mock_audio(text, out_path)
            else:
                logger.warning(f"TTS attempt {attempt} failed: {e}. Retrying...")
                time.sleep(1)

    return _generate_mock_audio(text, out_path)


async def synthesize_segment_async(
    text: str,
    voice_id: str,
    book_id: str,
    segment_id: str,
    emotion: str = "neutral",
    model_id: str = None,
    elevenlabs_api_key: Optional[str] = None,
) -> Path:
    """Async wrapper around synchronous synthesize_segment."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        synthesize_segment,
        text, voice_id, book_id, segment_id, emotion, model_id, elevenlabs_api_key
    )


# ─────────────────────────────────────────────────────────────────────────────
# Batch synthesis
# ─────────────────────────────────────────────────────────────────────────────

async def synthesize_all_segments(
    segments,                         # list[TextSegment]
    voice_assignment: dict[str, str],
    book_id: str,
    progress_callback=None,
) -> list:
    """
    Synthesize all segments with optional progress callback.
    Runs with concurrency limit to respect API rate limits.
    """
    from services.voice_manager import get_voice_for_speaker

    total = len(segments)
    completed = 0
    CONCURRENCY = 3   # Max parallel ElevenLabs calls

    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def _synth_one(seg):
        nonlocal completed
        async with semaphore:
            voice_id = get_voice_for_speaker(seg.speaker, voice_assignment)
            path = await synthesize_segment_async(
                text=seg.text,
                voice_id=voice_id,
                book_id=book_id,
                segment_id=seg.id,
                emotion=seg.emotion.value,
            )
            seg.audio_path = str(path)
            completed += 1
            if progress_callback:
                await progress_callback(completed / total, f"Synthesized {completed}/{total} segments")
            return seg

    tasks = [_synth_one(seg) for seg in segments]
    return await asyncio.gather(*tasks)
