"""
services/voice_manager.py
Manages voice assignment for narrators and characters.
Provides a curated voice catalogue and auto-assignment logic.
"""
from __future__ import annotations
import logging
from models.schemas import Character, Gender, VoiceInfo
from config import settings

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Built-in voice catalogue (ElevenLabs public voices)
# ─────────────────────────────────────────────────────────────────────────────

VOICE_CATALOGUE: list[VoiceInfo] = [
    # Narrators
    VoiceInfo(voice_id="pNInz6obpgDQGcFmaJgB", name="Adam",
              description="Deep, authoritative narrator — American male",
              gender=Gender.MALE, age_group="adult", accent="american"),
    VoiceInfo(voice_id="21m00Tcm4TlvDq8ikWAM", name="Rachel",
              description="Calm, clear narrator — American female",
              gender=Gender.FEMALE, age_group="adult", accent="american"),
    VoiceInfo(voice_id="AZnzlk1XvdvUeBnXmlld", name="Domi",
              description="Energetic, expressive female narrator",
              gender=Gender.FEMALE, age_group="adult", accent="american"),

    # Male characters
    VoiceInfo(voice_id="VR6AewLTigWG4xSOukaG", name="Arnold",
              description="Confident, strong male — American",
              gender=Gender.MALE, age_group="adult", accent="american"),
    VoiceInfo(voice_id="yoZ06aMxZJJ28mfd3POQ", name="Sam",
              description="Young, friendly male — American",
              gender=Gender.MALE, age_group="young_adult", accent="american"),
    VoiceInfo(voice_id="GBv7mTt0atIp3Br8iCZE", name="Thomas",
              description="Refined, articulate male — British",
              gender=Gender.MALE, age_group="adult", accent="british"),
    VoiceInfo(voice_id="TxGEqnHWrfWFTfGW9XjX", name="Josh",
              description="Deep, intense male — American",
              gender=Gender.MALE, age_group="adult", accent="american"),
    VoiceInfo(voice_id="bVMeCyTHy58xNoL34h3p", name="Jeremy",
              description="Older, experienced male — British",
              gender=Gender.MALE, age_group="elderly", accent="british"),

    # Female characters
    VoiceInfo(voice_id="EXAVITQu4vr4xnSDxMaL", name="Bella",
              description="Young, expressive female — American",
              gender=Gender.FEMALE, age_group="young_adult", accent="american"),
    VoiceInfo(voice_id="MF3mGyEYCl7XYWbV9V6O", name="Elli",
              description="Bright, warm female — American",
              gender=Gender.FEMALE, age_group="adult", accent="american"),
    VoiceInfo(voice_id="jsCqWAovK2LkecY7zXl4", name="Dorothy",
              description="Warm, mature female — British",
              gender=Gender.FEMALE, age_group="adult", accent="british"),
    VoiceInfo(voice_id="XB0fDUnXU5powFXDhCwa", name="Charlotte",
              description="Sophisticated, elegant female — British",
              gender=Gender.FEMALE, age_group="adult", accent="british"),
]

# Lookup by voice_id
_VOICE_MAP: dict[str, VoiceInfo] = {v.voice_id: v for v in VOICE_CATALOGUE}

# ─────────────────────────────────────────────────────────────────────────────
# Auto-assignment logic
# ─────────────────────────────────────────────────────────────────────────────

NARRATOR_VOICE_ID = settings.DEFAULT_NARRATOR_VOICE_ID  # Adam


def _filter_voices(
    gender: Gender,
    age_group: str,
    exclude_ids: set[str] | None = None,
) -> list[VoiceInfo]:
    """Find suitable voices matching gender + age group."""
    candidates = [
        v for v in VOICE_CATALOGUE
        if (gender == Gender.NEUTRAL or v.gender == gender or v.gender == Gender.NEUTRAL)
        and (age_group == "any" or v.age_group == age_group)
        and v.voice_id != NARRATOR_VOICE_ID
    ]
    if exclude_ids:
        candidates = [v for v in candidates if v.voice_id not in exclude_ids]
    return candidates


def _char_attr(char, attr: str, default=None):
    """Get attribute from either a Character object or a dict."""
    if isinstance(char, dict):
        return char.get(attr, default)
    return getattr(char, attr, default)


def assign_voices(characters) -> dict[str, str]:
    """
    Auto-assign a unique ElevenLabs voice_id to each character.
    Accepts list[Character] OR list[dict] (from process_chapters).
    Returns dict: {character_name: voice_id}
    """
    assignment: dict[str, str] = {"narrator": NARRATOR_VOICE_ID}
    used_voice_ids: set[str] = {NARRATOR_VOICE_ID}

    sorted_chars = sorted(characters, key=lambda c: -(_char_attr(c, "appearance_count") or 0))

    for char in sorted_chars:
        name      = _char_attr(char, "name", "")
        gender    = _char_attr(char, "gender", Gender.NEUTRAL)
        age_group = _char_attr(char, "age_group", "adult")

        if not name or name.lower() == "narrator":
            continue

        candidates = _filter_voices(gender, age_group, used_voice_ids)
        if not candidates:
            candidates = _filter_voices(gender, "any", used_voice_ids)
        if not candidates:
            candidates = _filter_voices(Gender.NEUTRAL, "any", used_voice_ids)
        if not candidates:
            candidates = _filter_voices(Gender.NEUTRAL, "any", None)

        voice = candidates[0] if candidates else VOICE_CATALOGUE[0]
        assignment[name] = voice.voice_id
        used_voice_ids.add(voice.voice_id)
        logger.debug(f"Assigned voice '{voice.name}' → character '{name}'")

    return assignment


def get_voice_info(voice_id: str) -> VoiceInfo | None:
    return _VOICE_MAP.get(voice_id)


def get_all_voices() -> list[VoiceInfo]:
    return VOICE_CATALOGUE


def get_voice_for_speaker(
    speaker: str | None,
    voice_assignment: dict[str, str],
) -> str:
    """Return voice_id for a given speaker name (or narrator if None/unknown)."""
    if not speaker:
        return voice_assignment.get("narrator", NARRATOR_VOICE_ID)
    return voice_assignment.get(speaker, voice_assignment.get("narrator", NARRATOR_VOICE_ID))
