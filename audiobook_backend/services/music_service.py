"""
services/music_service.py  ─  AI Background Music Generation
─────────────────────────────────────────────────────────────
Providers (in priority order, based on which API key is configured):
  1. Mubert   — REST API, tag-based generation, returns MP3 URL
  2. Soundraw — REST API, style-based generation
  3. Fallback — returns None (caller uses silence / skips music)
"""
from __future__ import annotations
import hashlib
import logging
import time
from pathlib import Path
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

# Cache dir for downloaded music tracks
_MUSIC_CACHE_DIR = settings.AUDIO_DIR.parent / "music_cache"
_MUSIC_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── Emotion → Mubert tags mapping ─────────────────────────────────────────────
EMOTION_TO_MUBERT_TAGS: dict[str, list[str]] = {
    "suspense":   ["suspense", "thriller", "dark", "tension"],
    "romantic":   ["romantic", "love", "soft", "emotional"],
    "sad":        ["sad", "melancholic", "slow", "piano"],
    "happy":      ["happy", "upbeat", "cheerful", "positive"],
    "dramatic":   ["dramatic", "epic", "orchestral", "cinematic"],
    "action":     ["action", "intense", "fast", "energetic"],
    "mysterious": ["mysterious", "ambient", "dark", "atmospheric"],
    "peaceful":   ["peaceful", "calm", "relaxing", "nature"],
    "neutral":    ["ambient", "background", "neutral"],
}

# Soundraw mood mapping
EMOTION_TO_SOUNDRAW_MOOD: dict[str, str] = {
    "suspense":   "Tense",
    "romantic":   "Romantic",
    "sad":        "Sad",
    "happy":      "Happy",
    "dramatic":   "Dramatic",
    "action":     "Exciting",
    "mysterious": "Dark",
    "peaceful":   "Peaceful",
    "neutral":    "Calm",
}


async def get_background_music(
    emotion: str,
    duration_seconds: int = 120,
    mubert_api_key: Optional[str] = None,
    soundraw_api_key: Optional[str] = None,
) -> Optional[Path]:
    """
    Try each provider in order and return a local Path to an MP3 file,
    or None if no music could be obtained.
    """
    # Build cache key so the same (emotion, duration) reuses the file
    cache_key = hashlib.md5(f"{emotion}_{duration_seconds}".encode()).hexdigest()[:12]
    cached = _MUSIC_CACHE_DIR / f"{cache_key}.mp3"
    if cached.exists() and cached.stat().st_size > 1000:
        logger.info(f"Music cache hit: {cached.name}")
        return cached

    # Try Mubert first
    if mubert_api_key:
        path = await _mubert_generate(emotion, duration_seconds, mubert_api_key, cached)
        if path:
            return path

    # Try Soundraw
    if soundraw_api_key:
        path = await _soundraw_generate(emotion, duration_seconds, soundraw_api_key, cached)
        if path:
            return path

    # Both failed or no keys
    logger.warning(f"No music generated for emotion='{emotion}' — music disabled")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Mubert implementation
# ─────────────────────────────────────────────────────────────────────────────

async def _mubert_generate(
    emotion: str,
    duration: int,
    api_key: str,
    dest: Path,
) -> Optional[Path]:
    """
    Call Mubert Render API to generate a track matching emotion tags.
    Docs: https://api-b2b.mubert.com/v2/
    """
    tags = EMOTION_TO_MUBERT_TAGS.get(emotion, ["ambient"])
    payload = {
        "method":  "RecordTrackTTM",
        "params": {
            "pat":      api_key,
            "duration": min(max(duration, 15), 300),   # Mubert: 15s–300s
            "mode":     "track",
            "tags":     tags,
            "format":   "mp3",
            "intensity": "medium",
        }
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api-b2b.mubert.com/v2/RecordTrackTTM",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            data = resp.json()

        # Mubert returns a polling URL or immediate track URL
        if data.get("status", {}).get("code") == 1:
            track_url = data.get("data", {}).get("tasks", [{}])[0].get("download_link")
            if track_url:
                return await _download_music(track_url, dest)

        # Handle async polling (Mubert sometimes queues the job)
        task_id = data.get("data", {}).get("tasks", [{}])[0].get("pat")
        if task_id:
            return await _mubert_poll(task_id, api_key, dest)

        logger.warning(f"Mubert unexpected response: {data}")
        return None

    except Exception as exc:
        logger.error(f"Mubert API error: {exc}")
        return None


async def _mubert_poll(task_id: str, api_key: str, dest: Path, max_polls: int = 20) -> Optional[Path]:
    """Poll Mubert for async task completion."""
    for _ in range(max_polls):
        await _async_sleep(3)
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://api-b2b.mubert.com/v2/GetTracksByMusicIds",
                    json={"method": "GetTracksByMusicIds", "params": {"pat": api_key, "ids": [task_id]}},
                )
                data = resp.json()
            track = (data.get("data", {}).get("tasks") or [{}])[0]
            if track.get("status") == "ready":
                url = track.get("download_link")
                if url:
                    return await _download_music(url, dest)
        except Exception:
            pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Soundraw implementation
# ─────────────────────────────────────────────────────────────────────────────

async def _soundraw_generate(
    emotion: str,
    duration: int,
    api_key: str,
    dest: Path,
) -> Optional[Path]:
    """
    Call Soundraw API to generate a track.
    Docs: https://soundraw.io/api  (beta – key obtained from soundraw.io/api_access)
    """
    mood  = EMOTION_TO_SOUNDRAW_MOOD.get(emotion, "Calm")
    genre = "Ambient"

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://soundraw.io/api/v1/musics",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type":  "application/json",
                },
                json={
                    "length": duration,
                    "mood":   mood,
                    "genre":  genre,
                    "tempo":  "medium",
                },
            )
            if resp.status_code not in (200, 201):
                logger.warning(f"Soundraw status {resp.status_code}: {resp.text[:200]}")
                return None
            data = resp.json()

        # Extract the MP3 download URL from Soundraw response
        download_url = (
            data.get("download_url")
            or data.get("url")
            or (data.get("music") or {}).get("url")
        )
        if download_url:
            return await _download_music(download_url, dest)
        return None

    except Exception as exc:
        logger.error(f"Soundraw API error: {exc}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _download_music(url: str, dest: Path) -> Optional[Path]:
    """Download an MP3 URL to a local file."""
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(dest, "wb") as f:
                    async for chunk in resp.aiter_bytes(8192):
                        f.write(chunk)
        if dest.stat().st_size > 1000:
            logger.info(f"Music downloaded: {dest.name} ({dest.stat().st_size // 1024}kB)")
            return dest
    except Exception as exc:
        logger.error(f"Music download failed: {exc}")
        if dest.exists():
            dest.unlink(missing_ok=True)
    return None


async def _async_sleep(seconds: float):
    import asyncio
    await asyncio.sleep(seconds)
