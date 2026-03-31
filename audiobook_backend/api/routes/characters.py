"""
api/routes/characters.py — Character & voice management
"""
from __future__ import annotations
import logging
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from models.schemas import CharacterUpdate, VoiceAssignment
from models.database import db
from services.voice_manager import get_all_voices, get_voice_info
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Characters & Voices"])


@router.get("/books/{book_id}/characters", response_model=list)
async def list_characters(book_id: str):
    if not await db.get_by_id(db.books, book_id):
        raise HTTPException(404, "Book not found")
    characters = await db.search(db.characters, "book_id", book_id)
    enriched = []
    for char in sorted(characters, key=lambda c: -c.get("appearance_count", 0)):
        vi = get_voice_info(char.get("voice_id")) if char.get("voice_id") else None
        enriched.append({
            **char,
            "voice_name":        vi.name if vi else None,
            "voice_description": vi.description if vi else None,
        })
    return enriched


@router.patch("/books/{book_id}/characters/{character_id}", response_model=dict)
async def update_character(book_id: str, character_id: str, update: CharacterUpdate):
    char = await db.get_by_id(db.characters, character_id)
    if not char or char.get("book_id") != book_id:
        raise HTTPException(404, "Character not found")
    updates = {k: v for k, v in update.model_dump().items() if v is not None}
    if updates:
        await db.update_by_id(db.characters, character_id, updates)
    return {"success": True, "character": await db.get_by_id(db.characters, character_id)}


@router.post("/books/{book_id}/characters/assign-voices", response_model=dict)
async def bulk_assign_voices(book_id: str, assignments: list[VoiceAssignment]):
    if not await db.get_by_id(db.books, book_id):
        raise HTTPException(404, "Book not found")
    updated = 0
    for a in assignments:
        chars = [c for c in await db.search(db.characters, "book_id", book_id)
                 if c.get("name") == a.character_name]
        for c in chars:
            await db.update_by_id(db.characters, c["id"], {"voice_id": a.voice_id})
            updated += 1
    return {"success": True, "message": f"Updated {updated} assignments"}


@router.post("/books/{book_id}/characters/preview-voice", response_model=dict)
async def preview_voice(book_id: str, voice_id: str,
                        text: str = "Hello! I am a character in this story."):
    vi = get_voice_info(voice_id)
    if not vi:
        raise HTTPException(404, f"Voice '{voice_id}' not found")
    preview_id = f"preview_{voice_id}_{uuid.uuid4().hex[:6]}"
    try:
        from services.tts_service import synthesize_segment
        audio_path = synthesize_segment(text, voice_id, "previews", preview_id, "neutral")
        return {"success": True, "voice_id": voice_id, "voice_name": vi.name,
                "audio_path": str(audio_path), "preview_text": text}
    except Exception as e:
        raise HTTPException(500, f"Preview failed: {e}")


@router.get("/voices", response_model=list)
async def list_voices(gender: str = None, accent: str = None):
    voices = get_all_voices()
    if gender: voices = [v for v in voices if v.gender.value == gender.lower()]
    if accent: voices = [v for v in voices if accent.lower() in v.accent.lower()]
    return [v.model_dump() for v in voices]


@router.get("/voices/{voice_id}", response_model=dict)
async def get_voice(voice_id: str):
    v = get_voice_info(voice_id)
    if not v: raise HTTPException(404, f"Voice '{voice_id}' not found")
    return v.model_dump()
