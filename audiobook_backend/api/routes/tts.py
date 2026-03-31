"""
api/routes/tts.py
Direct TTS endpoints for testing and standalone synthesis:
  POST /tts/synthesize          — synthesize a single text snippet
  POST /tts/synthesize-segment  — re-synthesize a specific segment
  GET  /tts/audio/{book_id}/{filename} — stream/download audio file
"""
from __future__ import annotations
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from models.schemas import TTSRequest
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tts", tags=["TTS"])


@router.post("/synthesize", response_model=dict)
async def synthesize_text(request: TTSRequest):
    """
    Directly synthesize any text to audio.
    Useful for testing voices and previewing results.
    """
    if not request.text.strip():
        raise HTTPException(status_code=422, detail="Text cannot be empty")
    if len(request.text) > 5000:
        raise HTTPException(status_code=422, detail="Text too long (max 5000 chars)")

    synth_id = f"direct_{uuid.uuid4().hex[:8]}"

    try:
        from services.tts_service import synthesize_segment
        audio_path = synthesize_segment(
            text=request.text,
            voice_id=request.voice_id,
            book_id="direct",
            segment_id=synth_id,
            emotion="neutral",
            model_id=request.model_id,
        )
        from services.audio_mixer import get_audio_stats
        stats = get_audio_stats(audio_path)
        return {
            "success": True,
            "segment_id": synth_id,
            "audio_path": str(audio_path),
            "duration_ms": stats.get("duration_ms"),
            "file_size_mb": stats.get("file_size_mb"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/synthesize-segment/{segment_id}", response_model=dict)
async def resynthesize_segment(segment_id: str, voice_id: str = None):
    """Re-synthesize a specific book segment (e.g. after user changes voice)."""
    from models.database import db
    seg = db.get_by_id(db.segments, segment_id)
    if not seg:
        raise HTTPException(status_code=404, detail="Segment not found")

    # Use provided voice_id or fall back to assigned one
    if not voice_id:
        book_id = seg["book_id"]
        speaker = seg.get("speaker")
        if speaker:
            chars = [c for c in db.search(db.characters, "book_id", book_id)
                     if c.get("name") == speaker]
            voice_id = chars[0]["voice_id"] if chars else settings.DEFAULT_NARRATOR_VOICE_ID
        else:
            voice_id = settings.DEFAULT_NARRATOR_VOICE_ID

    try:
        from services.tts_service import synthesize_segment
        audio_path = synthesize_segment(
            text=seg["text"],
            voice_id=voice_id,
            book_id=seg["book_id"],
            segment_id=segment_id,
            emotion=seg.get("emotion", "neutral"),
        )
        db.update_by_id(db.segments, segment_id, {"audio_path": str(audio_path)})
        return {
            "success": True,
            "segment_id": segment_id,
            "audio_path": str(audio_path),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/audio/{book_id}/{filename}")
async def stream_audio(book_id: str, filename: str):
    """Stream or download a generated audio file."""
    # Sanitize
    safe_filename = Path(filename).name
    audio_path = settings.AUDIO_DIR / book_id / safe_filename
    if not audio_path.exists():
        # Also check export dir
        audio_path = settings.EXPORT_DIR / book_id / safe_filename
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")

    suffix = audio_path.suffix.lower()
    media_types = {
        ".mp3": "audio/mpeg",
        ".m4b": "audio/mp4",
        ".wav": "audio/wav",
    }
    media_type = media_types.get(suffix, "audio/mpeg")
    return FileResponse(
        path=str(audio_path),
        media_type=media_type,
        filename=safe_filename,
    )


@router.get("/export/{book_id}/{filename}")
async def download_export(book_id: str, filename: str):
    """Download a final exported audiobook file."""
    safe_filename = Path(filename).name
    export_path = settings.EXPORT_DIR / book_id / safe_filename
    if not export_path.exists():
        raise HTTPException(status_code=404, detail="Export file not found")
    suffix = export_path.suffix.lower()
    media_type = "audio/mp4" if suffix == ".m4b" else "audio/mpeg"
    return FileResponse(
        path=str(export_path),
        media_type=media_type,
        filename=safe_filename,
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )
