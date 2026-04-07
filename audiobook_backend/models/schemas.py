"""
models/schemas.py — Pydantic data models for the entire application
"""
from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime
import uuid


# ─────────────────────────────────────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────────────────────────────────────

class ProcessingStatus(str, Enum):
    PENDING    = "pending"
    EXTRACTING = "extracting"
    ANALYZING  = "analyzing"
    SYNTHESIZING = "synthesizing"
    MIXING     = "mixing"
    COMPLETED  = "completed"
    FAILED     = "failed"


class Gender(str, Enum):
    MALE    = "male"
    FEMALE  = "female"
    NEUTRAL = "neutral"


class EmotionTag(str, Enum):
    NEUTRAL    = "neutral"
    HAPPY      = "happy"
    SAD        = "sad"
    SUSPENSE   = "suspense"
    DRAMATIC   = "dramatic"
    ROMANTIC   = "romantic"
    ACTION     = "action"
    MYSTERIOUS = "mysterious"
    PEACEFUL   = "peaceful"


class SegmentType(str, Enum):
    NARRATION = "narration"
    DIALOGUE  = "dialogue"


class ExportFormat(str, Enum):
    MP3 = "mp3"
    M4B = "m4b"
    WAV = "wav"


# ─────────────────────────────────────────────────────────────────────────────
# Character Models
# ─────────────────────────────────────────────────────────────────────────────

class CharacterBase(BaseModel):
    name: str
    gender: Gender = Gender.NEUTRAL
    age_group: str = "adult"          # child | teen | adult | elderly
    accent: str = "american"
    voice_id: Optional[str] = None    # ElevenLabs voice ID
    traits: list[str] = Field(default_factory=list)


class Character(CharacterBase):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    book_id: str
    appearance_count: int = 0


class CharacterUpdate(BaseModel):
    gender: Optional[Gender] = None
    age_group: Optional[str] = None
    accent: Optional[str] = None
    voice_id: Optional[str] = None
    traits: Optional[list[str]] = None


# ─────────────────────────────────────────────────────────────────────────────
# Text Segment Models
# ─────────────────────────────────────────────────────────────────────────────

class TextSegment(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    book_id: str
    chapter_index: int
    paragraph_index: int
    segment_index: int = 0            # Monotonic position within chapter (for stable ordering)
    segment_type: SegmentType
    speaker: Optional[str] = None     # Character name for dialogue
    text: str
    emotion: EmotionTag = EmotionTag.NEUTRAL
    audio_path: Optional[str] = None  # Path to generated audio file
    duration_ms: Optional[int] = None


# ─────────────────────────────────────────────────────────────────────────────
# Chapter Model
# ─────────────────────────────────────────────────────────────────────────────

class Chapter(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    book_id: str
    index: int
    title: str
    dominant_emotion: EmotionTag = EmotionTag.NEUTRAL
    audio_path: Optional[str] = None
    duration_ms: Optional[int] = None
    segment_count: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# Book Models
# ─────────────────────────────────────────────────────────────────────────────

class BookCreate(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None


class Book(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: Optional[str] = None
    title: str = "Untitled Book"
    author: str = "Unknown Author"
    file_path: Optional[str] = None
    file_type: Optional[str] = None   # pdf | docx | epub | txt
    status: ProcessingStatus = ProcessingStatus.PENDING
    progress: float = 0.0             # 0.0 – 1.0
    error_message: Optional[str] = None

    chapter_count: int = 0
    character_count: int = 0
    segment_count: int = 0
    total_words: int = 0
    music_provider_preference: str = "auto"
    music_style_preset: str = "auto"
    character_voice_plan: dict[str, str] = Field(default_factory=dict)

    export_path: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class BookResponse(Book):
    characters: list[Character] = []
    chapters: list[Chapter] = []


# ─────────────────────────────────────────────────────────────────────────────
# Voice Models
# ─────────────────────────────────────────────────────────────────────────────

class VoiceInfo(BaseModel):
    voice_id: str
    name: str
    description: str = ""
    gender: Gender = Gender.NEUTRAL
    age_group: str = "adult"
    accent: str = "american"
    preview_url: Optional[str] = None


class VoiceAssignment(BaseModel):
    character_name: str
    voice_id: str


# ─────────────────────────────────────────────────────────────────────────────
# Processing & Pipeline Models
# ─────────────────────────────────────────────────────────────────────────────

class ProcessingOptions(BaseModel):
    add_background_music: bool = False
    export_format: ExportFormat = ExportFormat.MP3
    speech_rate: float = 1.0          # 0.7 – 1.3
    music_volume_db: float = -18.0
    music_type: str = "auto"          # auto | mubert | soundraw | jamendo
    music_style: str = "auto"         # auto | ambient | cinematic | orchestral | piano | electronic
    character_voice_overrides: dict[str, str] = Field(default_factory=dict)
    include_sfx: bool = False


class ProcessingProgress(BaseModel):
    book_id: str
    status: ProcessingStatus
    progress: float
    current_step: str = ""
    message: str = ""


class TTSRequest(BaseModel):
    text: str
    voice_id: str
    model_id: str = "eleven_multilingual_v2"
    stability: float = 0.5
    similarity_boost: float = 0.75
    style: float = 0.0
    use_speaker_boost: bool = True


# ─────────────────────────────────────────────────────────────────────────────
# API Response Models
# ─────────────────────────────────────────────────────────────────────────────

class APIResponse(BaseModel):
    success: bool = True
    message: str = ""
    data: Optional[dict] = None


class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    detail: Optional[str] = None
