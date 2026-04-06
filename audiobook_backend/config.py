"""
config.py  ─  Application settings via environment variables / .env file
"""
from pydantic_settings import BaseSettings
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────────────────────────────
    APP_NAME:    str = "AudioBook Generator API"
    APP_VERSION: str = "2.0.0"
    DEBUG:       bool = False

    # ── Storage ───────────────────────────────────────────────────────────────
    UPLOAD_DIR: Path = BASE_DIR / "storage" / "uploads"
    AUDIO_DIR:  Path = BASE_DIR / "storage" / "audio"
    EXPORT_DIR: Path = BASE_DIR / "storage" / "exports"

    # ── Database ──────────────────────────────────────────────────────────────
    # SQLite (default)  or  PostgreSQL for production
    # Railway / Render inject DATABASE_URL automatically for Postgres add-ons
    DATABASE_URL: str = f"sqlite:///{BASE_DIR}/storage/db.sqlite"

    # ── Redis / Celery ────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    USE_CELERY: bool = False   # Set True when Redis + worker are available

    # ── ElevenLabs TTS ────────────────────────────────────────────────────────
    ELEVENLABS_API_KEY:  str = ""
    ELEVENLABS_MODEL_ID: str = "eleven_multilingual_v2"

    DEFAULT_NARRATOR_VOICE_ID: str = "pNInz6obpgDQGcFmaJgB"   # Adam
    DEFAULT_MALE_VOICE_ID:     str = "VR6AewLTigWG4xSOukaG"   # Arnold
    DEFAULT_FEMALE_VOICE_ID:   str = "EXAVITQu4vr4xnSDxMaL"   # Bella
    DEFAULT_NEUTRAL_VOICE_ID:  str = "pNInz6obpgDQGcFmaJgB"   # Adam

    # ── Music APIs ────────────────────────────────────────────────────────────
    MUBERT_API_KEY:   str = ""
    SOUNDRAW_API_KEY: str = ""
    JAMENDO_CLIENT_ID: str = ""

    # ── Audio ─────────────────────────────────────────────────────────────────
    AUDIO_FORMAT:     str   = "mp3"
    MUSIC_VOLUME_DB:  float = -18.0
    MUSIC_VOLUME_MIN_DB: float = -30.0
    MUSIC_VOLUME_MAX_DB: float = -6.0
    SPEECH_PAUSE_MS:  int   = 350
    CHAPTER_PAUSE_MS: int   = 2000

    # ── Security ──────────────────────────────────────────────────────────────
    SECRET_KEY:                  str = "changeme-in-production-use-long-random-string"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Comma-separated list of allowed origins, or "*" for all
    CORS_ORIGINS: str = "*"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def cors_origins_list(self) -> list[str]:
        if self.CORS_ORIGINS == "*":
            return ["*"]
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()

# Ensure storage directories exist
for _d in (settings.UPLOAD_DIR, settings.AUDIO_DIR, settings.EXPORT_DIR):
    _d.mkdir(parents=True, exist_ok=True)
