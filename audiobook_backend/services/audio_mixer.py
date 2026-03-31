"""
services/audio_mixer.py
Audio assembly pipeline using pydub + FFmpeg:
  1. Concatenate TTS segments within a chapter (with pauses)
  2. Add optional background music (ducked under speech)
  3. Export individual chapter files and final merged audiobook
  4. Support MP3 and M4B output formats
"""
from __future__ import annotations
import logging
import subprocess
import json
from pathlib import Path
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)

EXPORT_DIR = settings.EXPORT_DIR
AUDIO_DIR  = settings.AUDIO_DIR


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ms_to_str(ms: int) -> str:
    """Convert milliseconds to human-readable duration."""
    secs = ms // 1000
    return f"{secs // 60}m {secs % 60}s"


def _get_audio_duration_ms(path: Path) -> int:
    """Get audio duration in milliseconds via pydub."""
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(str(path))
        return len(audio)
    except Exception:
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# Chapter assembly
# ─────────────────────────────────────────────────────────────────────────────

def assemble_chapter(
    segments,                # list[TextSegment] with audio_path set
    chapter_title: str,
    book_id: str,
    chapter_index: int,
    music_path: Optional[Path] = None,
    music_volume_db: float = None,
) -> Optional[Path]:
    """
    Assemble all segment audio files for one chapter into a single MP3.
    Optionally mix in background music.
    Returns path to chapter MP3, or None on failure.
    """
    try:
        from pydub import AudioSegment
        from pydub.effects import normalize

        music_volume_db = music_volume_db or settings.MUSIC_VOLUME_DB
        speech_pause = AudioSegment.silent(duration=settings.SPEECH_PAUSE_MS)

        # ── 1. Build narration track ─────────────────────────────────────────
        narration = AudioSegment.empty()
        valid_segments = [s for s in segments if s.audio_path and Path(s.audio_path).exists()]

        if not valid_segments:
            logger.warning(f"Chapter {chapter_index}: no valid audio segments")
            return None

        for seg in valid_segments:
            try:
                audio = AudioSegment.from_file(seg.audio_path)
                # Add slight pause between dialogue turns
                narration += audio + speech_pause
            except Exception as e:
                logger.warning(f"Skipping segment {seg.id}: {e}")
                continue

        if len(narration) == 0:
            return None

        narration = normalize(narration)

        # ── 2. Optionally add background music ──────────────────────────────
        if music_path and music_path.exists():
            narration = _mix_with_music(narration, music_path, music_volume_db)

        # ── 3. Export chapter ───────────────────────────────────────────────
        book_dir = EXPORT_DIR / book_id
        book_dir.mkdir(parents=True, exist_ok=True)
        safe_title = "".join(c if c.isalnum() or c in " -_" else "_"
                             for c in chapter_title)[:50]
        out_path = book_dir / f"ch{chapter_index:02d}_{safe_title}.mp3"
        narration.export(str(out_path), format="mp3", bitrate="128k")

        logger.info(
            f"Chapter {chapter_index} assembled → {out_path.name} "
            f"({_ms_to_str(len(narration))})"
        )
        return out_path

    except ImportError:
        logger.error("pydub not installed — cannot assemble audio")
        return None
    except Exception as e:
        logger.error(f"Error assembling chapter {chapter_index}: {e}", exc_info=True)
        return None


def _mix_with_music(
    narration,         # AudioSegment
    music_path: Path,
    music_volume_db: float,
) -> "AudioSegment":  # noqa: F821
    """Duck background music under narration speech."""
    from pydub import AudioSegment

    music = AudioSegment.from_file(str(music_path))
    music = music + music_volume_db  # Lower baseline volume

    # Loop music to fill narration length
    while len(music) < len(narration):
        music = music + music

    music = music[:len(narration)]

    # Simple sidechain: reduce music volume further when speech is loud
    CHUNK_MS   = 150    # Process in 150ms chunks
    DUCK_DB    = -10    # Additional reduction during speech
    RMS_THRESH = 200    # RMS above this = speech present

    ducked = AudioSegment.empty()
    for i in range(0, len(music), CHUNK_MS):
        m_chunk = music[i: i + CHUNK_MS]
        n_chunk = narration[i: i + CHUNK_MS]
        if len(n_chunk) > 0 and n_chunk.rms > RMS_THRESH:
            ducked += m_chunk + DUCK_DB
        else:
            ducked += m_chunk

    # Fade music in/out at chapter boundaries
    ducked = ducked.fade_in(1000).fade_out(1500)
    return narration.overlay(ducked)


# ─────────────────────────────────────────────────────────────────────────────
# Full audiobook merge
# ─────────────────────────────────────────────────────────────────────────────

def merge_chapters(
    chapter_paths: list[Path],
    book_id: str,
    book_title: str,
    book_author: str,
    export_format: str = "mp3",
) -> Optional[Path]:
    """
    Merge all chapter MP3s into a single audiobook file.
    Supports MP3 and M4B (with chapter markers).
    """
    if not chapter_paths:
        logger.error("No chapter files to merge")
        return None

    out_dir = EXPORT_DIR / book_id
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_title = "".join(c if c.isalnum() or c in " -_" else "_"
                         for c in book_title)[:60]

    if export_format == "m4b":
        return _merge_to_m4b(chapter_paths, out_dir, safe_title, book_title, book_author)
    else:
        return _merge_to_mp3(chapter_paths, out_dir, safe_title)


def _merge_to_mp3(
    chapter_paths: list[Path],
    out_dir: Path,
    safe_title: str,
) -> Optional[Path]:
    """Concatenate chapters into one MP3 via pydub."""
    try:
        from pydub import AudioSegment
        from pydub.effects import normalize

        chapter_gap = AudioSegment.silent(duration=settings.CHAPTER_PAUSE_MS)
        combined = AudioSegment.empty()

        for path in chapter_paths:
            try:
                chapter_audio = AudioSegment.from_file(str(path))
                combined += chapter_audio + chapter_gap
            except Exception as e:
                logger.warning(f"Skipping chapter {path.name}: {e}")

        if len(combined) == 0:
            return None

        combined = normalize(combined)
        out_path = out_dir / f"{safe_title}.mp3"
        combined.export(str(out_path), format="mp3", bitrate="128k",
                        tags={"title": safe_title})
        logger.info(f"Exported MP3: {out_path} ({_ms_to_str(len(combined))})")
        return out_path

    except Exception as e:
        logger.error(f"MP3 merge failed: {e}", exc_info=True)
        return None


def _merge_to_m4b(
    chapter_paths: list[Path],
    out_dir: Path,
    safe_title: str,
    book_title: str,
    book_author: str,
) -> Optional[Path]:
    """
    Merge chapters into M4B audiobook with chapter markers using FFmpeg.
    """
    try:
        # Build FFmpeg concat list
        concat_file = out_dir / "concat.txt"
        with open(concat_file, "w") as f:
            for p in chapter_paths:
                f.write(f"file '{p.resolve()}'\n")

        out_path = out_dir / f"{safe_title}.m4b"

        # First: concatenate to intermediate AAC
        intermediate = out_dir / "merged_intermediate.aac"
        cmd_concat = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-c:a", "aac", "-b:a", "128k",
            str(intermediate),
        ]
        result = subprocess.run(cmd_concat, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"FFmpeg concat failed: {result.stderr}")
            return _merge_to_mp3(chapter_paths, out_dir, safe_title)

        # Build chapter metadata file
        metadata_file = _build_ffmpeg_chapter_metadata(
            chapter_paths, book_title, book_author, out_dir
        )

        # Final: embed metadata + chapter markers
        cmd_final = [
            "ffmpeg", "-y",
            "-i", str(intermediate),
            "-i", str(metadata_file),
            "-map_metadata", "1",
            "-c", "copy",
            str(out_path),
        ]
        result = subprocess.run(cmd_final, capture_output=True, text=True)
        if result.returncode != 0:
            logger.warning(f"M4B chapter metadata embed failed: {result.stderr}")
            # Still return the M4B without chapters
            import shutil
            shutil.copy(str(intermediate), str(out_path))

        # Cleanup temp files
        for f in [concat_file, intermediate, metadata_file]:
            try:
                f.unlink()
            except Exception:
                pass

        logger.info(f"Exported M4B: {out_path}")
        return out_path

    except FileNotFoundError:
        logger.warning("FFmpeg not found — falling back to MP3 export")
        return _merge_to_mp3(chapter_paths, out_dir, safe_title)
    except Exception as e:
        logger.error(f"M4B export failed: {e}", exc_info=True)
        return _merge_to_mp3(chapter_paths, out_dir, safe_title)


def _build_ffmpeg_chapter_metadata(
    chapter_paths: list[Path],
    title: str,
    artist: str,
    out_dir: Path,
) -> Path:
    """Build FFmpeg metadata file with chapter timestamps."""
    meta_path = out_dir / "metadata.txt"
    lines = [
        ";FFMETADATA1",
        f"title={title}",
        f"artist={artist}",
        f"album={title}",
        "",
    ]
    current_ms = 0
    for i, path in enumerate(chapter_paths):
        dur = _get_audio_duration_ms(path)
        chapter_name = path.stem.split("_", 1)[-1].replace("_", " ").title()
        lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={current_ms}",
            f"END={current_ms + dur}",
            f"title={chapter_name}",
            "",
        ]
        current_ms += dur + settings.CHAPTER_PAUSE_MS

    meta_path.write_text("\n".join(lines))
    return meta_path


# ─────────────────────────────────────────────────────────────────────────────
# Quick stats
# ─────────────────────────────────────────────────────────────────────────────

def get_audio_stats(file_path: Path) -> dict:
    """Return duration, size, and format info for an audio file."""
    if not file_path.exists():
        return {}
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(str(file_path))
        return {
            "duration_ms": len(audio),
            "duration_str": _ms_to_str(len(audio)),
            "channels": audio.channels,
            "frame_rate": audio.frame_rate,
            "file_size_mb": round(file_path.stat().st_size / (1024 * 1024), 2),
        }
    except Exception as e:
        return {"error": str(e)}
