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
import re
from pathlib import Path
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)

EXPORT_DIR = settings.EXPORT_DIR
AUDIO_DIR  = settings.AUDIO_DIR
RADIO_CUE_ASSETS_DIR = settings.RADIO_CUE_ASSETS_DIR


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


def _segment_attr(seg, key: str, default=None):
    """Read attribute from either object-like or dict-like segment records."""
    if isinstance(seg, dict):
        return seg.get(key, default)
    return getattr(seg, key, default)


def _parse_time_ms(value: str | None, default_ms: int) -> int:
    if not value:
        return default_ms
    raw = str(value).strip().lower()
    try:
        if raw.endswith("ms"):
            return max(50, int(float(raw[:-2])))
        if raw.endswith("s"):
            return max(50, int(float(raw[:-1]) * 1000))
        return max(50, int(float(raw) * 1000))
    except Exception:
        return default_ms


def _parse_db(value: str | None, default_db: float) -> float:
    if value is None:
        return default_db
    raw = str(value).strip().lower().replace("db", "")
    try:
        return float(raw)
    except Exception:
        return default_db


def _apply_spatial_params(audio, params: dict[str, str]):
    """Apply simple distance/pan interpretation for phase-2 cue rendering."""
    dist = (params.get("dist") or params.get("distance") or "").strip().lower()
    if dist == "far":
        audio = audio - 7
    elif dist == "mid":
        audio = audio - 3

    pan = (params.get("pan") or "").strip().lower()
    if pan:
        if "left" in pan and "right" not in pan:
            audio = audio.pan(-0.6)
        elif "right" in pan and "left" not in pan:
            audio = audio.pan(0.6)
        elif pan == "center":
            audio = audio.pan(0.0)
        elif "left_to_center" in pan:
            audio = audio.pan(-0.3)
        elif "right_to_center" in pan:
            audio = audio.pan(0.3)
    return audio


def _safe_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")


def _scene_profile(scene_label: str) -> dict[str, float]:
    """
    Map scene labels to a lightweight acoustic profile.
    Values are intentionally subtle to preserve intelligibility.
    """
    text = (scene_label or "").lower()
    profile = {
        "hp_hz": 120,
        "lp_hz": 6000,
        "wet_db": -18.0,
        "echo_delay_ms": 95,
        "echo_decay_db": -17.0,
    }
    if any(k in text for k in ("hall", "cathedral", "tunnel", "cavern")):
        profile.update({"hp_hz": 100, "lp_hz": 5400, "wet_db": -14.0, "echo_delay_ms": 120, "echo_decay_db": -14.0})
    elif any(k in text for k in ("outdoor", "forest", "street", "station", "city")):
        profile.update({"hp_hz": 150, "lp_hz": 7200, "wet_db": -24.0, "echo_delay_ms": 70, "echo_decay_db": -24.0})
    elif any(k in text for k in ("room", "office", "bedroom", "kitchen", "indoor")):
        profile.update({"hp_hz": 130, "lp_hz": 6200, "wet_db": -20.0, "echo_delay_ms": 85, "echo_decay_db": -20.0})
    return profile


def _find_asset_candidates(kind: str, label: str) -> list[Path]:
    """
    Deterministic asset lookup for phase-2 cue mapping.
    Search order:
      1) exact slug filename
      2) tokenized keyword filename
    """
    root = RADIO_CUE_ASSETS_DIR / kind
    if not root.exists():
        return []

    exts = ("*.mp3", "*.wav", "*.ogg", "*.flac", "*.m4a")
    candidates: list[Path] = []

    slug = _safe_slug(label)
    if slug:
        for ext in exts:
            candidates.extend(sorted(root.glob(f"{slug}{ext[1:]}")))
            candidates.extend(sorted(root.glob(f"{slug}_*{ext[1:]}")))

    if not candidates:
        tokens = [t for t in re.split(r"[^a-z0-9]+", (label or "").lower()) if t]
        for token in tokens:
            if len(token) < 3:
                continue
            for ext in exts:
                candidates.extend(sorted(root.glob(f"*{token}*{ext[1:]}")))

    # stable deterministic order
    unique: list[Path] = []
    seen: set[str] = set()
    for p in candidates:
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    return unique


def _load_cue_asset(kind: str, label: str):
    """Return an AudioSegment from local asset library, or None."""
    try:
        from pydub import AudioSegment
        candidates = _find_asset_candidates(kind, label)
        if not candidates:
            return None
        return AudioSegment.from_file(str(candidates[0]))
    except Exception:
        return None


def _tile_audio_to_duration(audio, duration_ms: int):
    from pydub import AudioSegment
    if duration_ms <= 0:
        return AudioSegment.silent(duration=0)
    if len(audio) <= 0:
        return AudioSegment.silent(duration=duration_ms)
    bed = audio
    while len(bed) < duration_ms:
        bed += audio
    return bed[:duration_ms]


def _apply_scene_profile(narration, scene_label: str):
    """
    Apply subtle scene acoustics to narration.
    Uses a low-level delayed wet layer for simple room feel.
    """
    profile = _scene_profile(scene_label)
    wet = narration
    try:
        wet = wet.high_pass_filter(int(profile["hp_hz"]))
        wet = wet.low_pass_filter(int(profile["lp_hz"]))
        wet = wet + float(profile["wet_db"])
        # Simple echo by delayed overlay
        delay = int(profile["echo_delay_ms"])
        if delay > 0:
            from pydub import AudioSegment
            delayed = AudioSegment.silent(duration=delay) + (wet + float(profile["echo_decay_db"]))
            wet = wet.overlay(delayed)
        return narration.overlay(wet)
    except Exception:
        return narration


def _generate_ambience_segment(label: str, duration_ms: int, level_db: float = -42.0):
    from pydub import AudioSegment
    from pydub.generators import Sine, WhiteNoise

    asset = _load_cue_asset("ambience", label)
    if asset is not None:
        return (_tile_audio_to_duration(asset, duration_ms) + level_db).fade_in(300).fade_out(500)

    text = (label or "").lower()
    bed = WhiteNoise().to_audio_segment(duration=max(250, duration_ms))
    bed = bed.low_pass_filter(3500).high_pass_filter(120)

    if any(k in text for k in ("rain", "storm", "wind")):
        texture = WhiteNoise().to_audio_segment(duration=max(250, duration_ms)).high_pass_filter(3500)
        bed = bed.overlay(texture - 8)
    elif any(k in text for k in ("city", "street", "station", "cafe")):
        hum = Sine(110).to_audio_segment(duration=max(250, duration_ms)) - 16
        bed = bed.overlay(hum)
    elif any(k in text for k in ("room", "hall", "indoor")):
        bed = bed.low_pass_filter(1200)
    elif any(k in text for k in ("forest", "night")):
        hiss = WhiteNoise().to_audio_segment(duration=max(250, duration_ms)).high_pass_filter(4500) - 10
        bed = bed.overlay(hiss)

    return (bed + level_db).fade_in(300).fade_out(500)


def _generate_foley_effect(label: str, params: dict[str, str]):
    from pydub import AudioSegment
    from pydub.generators import Sine, WhiteNoise

    text = (label or "").lower()
    duration_ms = _parse_time_ms(params.get("duration"), 900)
    level_db = _parse_db(params.get("level"), -20.0)

    asset = _load_cue_asset("foley", label)
    if asset is not None:
        effect = _tile_audio_to_duration(asset, duration_ms)
        return _apply_spatial_params(effect + level_db, params)

    if "foot" in text:
        step = (Sine(95).to_audio_segment(duration=90) - 8).fade_in(5).fade_out(50)
        silence = AudioSegment.silent(duration=90)
        effect = (step + silence + step + silence + step)[:duration_ms]
    elif any(k in text for k in ("door", "creak")):
        effect = WhiteNoise().to_audio_segment(duration=duration_ms).low_pass_filter(900).fade_in(120).fade_out(180)
    elif any(k in text for k in ("paper", "rustle")):
        effect = WhiteNoise().to_audio_segment(duration=duration_ms).high_pass_filter(1800).fade_in(30).fade_out(120)
    elif any(k in text for k in ("glass", "clink", "metal")):
        ping = Sine(1800).to_audio_segment(duration=220).fade_out(180)
        effect = (ping + AudioSegment.silent(duration=max(0, duration_ms - len(ping))))
    else:
        effect = WhiteNoise().to_audio_segment(duration=duration_ms).low_pass_filter(1400).fade_in(20).fade_out(140)

    effect = _apply_spatial_params(effect + level_db, params)
    return effect


def _generate_music_sting(label: str, params: dict[str, str]):
    from pydub import AudioSegment
    from pydub.generators import Sine

    text = (label or "").lower()
    duration_ms = _parse_time_ms(params.get("duration"), 1800)
    level_db = _parse_db(params.get("level"), -24.0)

    asset = _load_cue_asset("music", label)
    if asset is not None:
        sting = _tile_audio_to_duration(asset, duration_ms)
        fade_in_ms = _parse_time_ms(params.get("fade_in"), 250)
        fade_out_ms = _parse_time_ms(params.get("fade_out"), 500)
        sting = (sting + level_db).fade_in(fade_in_ms).fade_out(min(fade_out_ms, max(120, duration_ms // 2)))
        return _apply_spatial_params(sting, params)

    if any(k in text for k in ("tension", "dark", "suspense")):
        notes = [146, 174, 220]  # D minor-ish
    elif any(k in text for k in ("happy", "uplift", "light")):
        notes = [220, 277, 330]  # A major-ish
    else:
        notes = [196, 247, 294]  # G sus-ish

    bed = AudioSegment.silent(duration=duration_ms)
    for hz in notes:
        tone = Sine(hz).to_audio_segment(duration=duration_ms).fade_in(220).fade_out(500) - 10
        bed = bed.overlay(tone)

    fade_in_ms = _parse_time_ms(params.get("fade_in"), 250)
    fade_out_ms = _parse_time_ms(params.get("fade_out"), 500)
    sting = (bed + level_db).fade_in(fade_in_ms).fade_out(min(fade_out_ms, max(120, duration_ms // 2)))
    return _apply_spatial_params(sting, params)


def _apply_radio_cues(
    narration,
    chapter_cues: list[dict],
    paragraph_offsets_ms: dict[int, int],
):
    """Overlay ambience/foley/music cue layers on top of narration."""
    from pydub import AudioSegment

    if not chapter_cues:
        return narration

    timeline_len = len(narration)
    if timeline_len <= 0:
        return narration

    # 1) Build ambience automation from SCENE/AMBIENCE directives.
    ambience_cues = [
        cue for cue in chapter_cues
        if str(cue.get("type", "")).lower() in ("scene", "ambience")
    ]
    # Scene profile influences narrator reverb/EQ.
    scene_cues = [cue for cue in ambience_cues if str(cue.get("type", "")).lower() == "scene"]
    if scene_cues:
        last_scene = str(scene_cues[-1].get("label") or scene_cues[-1].get("value") or "").strip()
        if last_scene:
            narration = _apply_scene_profile(narration, last_scene)
    if ambience_cues:
        ambience_events: list[tuple[int, str, dict[str, str]]] = []
        for cue in ambience_cues:
            p_idx = int(cue.get("paragraph_index", 0) or 0)
            start_ms = paragraph_offsets_ms.get(p_idx, 0)
            label = str(cue.get("label") or cue.get("value") or cue.get("type") or "").strip()
            params = cue.get("params") or {}
            if label:
                ambience_events.append((max(0, start_ms), label, params))
        ambience_events.sort(key=lambda x: x[0])

        if ambience_events:
            ambience_track = AudioSegment.silent(duration=timeline_len)
            for i, (start_ms, label, params) in enumerate(ambience_events):
                end_ms = ambience_events[i + 1][0] if i + 1 < len(ambience_events) else timeline_len
                seg_len = max(200, end_ms - start_ms)
                level = _parse_db(params.get("level"), -42.0)
                segment = _generate_ambience_segment(label, seg_len, level_db=level)
                ambience_track = ambience_track.overlay(segment, position=start_ms)
            narration = narration.overlay(ambience_track)

    # 2) Overlay point cues (FOLEY, MUSIC) at paragraph positions.
    point_cues = [
        cue for cue in chapter_cues
        if str(cue.get("type", "")).lower() in ("foley", "music")
    ]
    for cue in point_cues:
        cue_type = str(cue.get("type", "")).lower()
        params = cue.get("params") or {}
        p_idx = int(cue.get("paragraph_index", 0) or 0)
        pos_ms = paragraph_offsets_ms.get(p_idx, 0)
        label = str(cue.get("label") or cue.get("value") or cue_type)
        if cue_type == "foley":
            effect = _generate_foley_effect(label, params)
        else:
            effect = _generate_music_sting(label, params)
        if effect:
            narration = narration.overlay(effect, position=max(0, min(pos_ms, timeline_len - 1)))
    return narration


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
    progress_callback=None,  # Optional[Callable[[int, int], None]] — called as cb(done, total)
    chapter_cues: Optional[list[dict]] = None,
) -> Optional[Path]:
    """
    Assemble all segment audio files for one chapter into a single MP3.
    Optionally mix in background music.
    Returns path to chapter MP3, or None on failure.
    """
    try:
        from pydub import AudioSegment
        from pydub.effects import normalize

        # Preserve explicit 0.0dB requests; only default when value is missing.
        music_volume_db = settings.MUSIC_VOLUME_DB if music_volume_db is None else music_volume_db
        speech_pause = AudioSegment.silent(duration=settings.SPEECH_PAUSE_MS)

        # ── 1. Build narration track ─────────────────────────────────────────
        narration = AudioSegment.empty()
        valid_segments = [s for s in segments if s.audio_path and Path(s.audio_path).exists()]
        paragraph_offsets_ms: dict[int, int] = {}

        if not valid_segments:
            logger.warning(f"Chapter {chapter_index}: no valid audio segments")
            return None

        total_valid = len(valid_segments)
        for seg_i, seg in enumerate(valid_segments):
            try:
                p_idx = int(_segment_attr(seg, "paragraph_index", 0) or 0)
                paragraph_offsets_ms.setdefault(p_idx, len(narration))
                audio = AudioSegment.from_file(seg.audio_path)
                # Add slight pause between dialogue turns
                narration += audio + speech_pause
                # Report mixing progress every 5 segments or at the end
                if progress_callback and (seg_i % 5 == 0 or seg_i == total_valid - 1):
                    try:
                        progress_callback(seg_i + 1, total_valid)
                    except Exception:
                        pass  # never let a callback crash the mixer
            except Exception as e:
                logger.warning(f"Skipping segment {seg.id}: {e}")
                continue

        if len(narration) == 0:
            return None

        narration = normalize(narration)

        # ── 2. Optionally add background music ──────────────────────────────
        if music_path and music_path.exists():
            narration = _mix_with_music(narration, music_path, music_volume_db)
        if chapter_cues:
            narration = _apply_radio_cues(
                narration,
                chapter_cues=chapter_cues,
                paragraph_offsets_ms=paragraph_offsets_ms,
            )

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
