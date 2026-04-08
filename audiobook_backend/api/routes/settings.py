"""
api/routes/settings.py — API key management + profile update endpoints
"""
from __future__ import annotations
import uuid
import logging
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse, parse_qs

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from pydantic import BaseModel

from config import settings
from models.database import db
from api.routes.auth import get_current_user
from services.auth_service import encrypt_key, decrypt_key, mask_key

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["Settings"])

SUPPORTED_SERVICES = {"elevenlabs", "mubert", "soundraw", "jamendo"}
SUPPORTED_SFX_CATEGORIES = ("ambience", "foley", "music")
ALLOWED_SFX_EXTENSIONS = {".wav", ".mp3", ".ogg", ".flac", ".m4a"}
MAX_SFX_ZIP_MB = 300
MAX_SFX_MEMBER_MB = 80
_SFX_CATEGORY_ALIASES = {
    "ambience": {"ambience", "ambiance", "ambient", "atmos", "atmosphere", "bg", "background"},
    "foley": {"foley", "sfx", "fx", "effects", "oneshot", "oneshots"},
    "music": {"music", "score", "stings", "sting", "bed", "beds"},
}
_SFX_KEYWORDS = {
    "ambience": {"rain", "wind", "city", "forest", "night", "room", "hall", "street", "station"},
    "foley": {"footstep", "door", "paper", "rustle", "glass", "cloth", "impact", "whoosh", "phone"},
    "music": {"tension", "cinematic", "drone", "pulse", "theme", "motif", "sad", "happy"},
}


class ApiKeyCreate(BaseModel):
    service: str
    label:   str = ""
    key:     str


class ProfileUpdate(BaseModel):
    username: str | None = None
    email:    str | None = None


def _safe_asset_stem(raw_name: str) -> str:
    stem = re.sub(r"[^a-z0-9]+", "_", (raw_name or "").lower()).strip("_")
    return stem or "asset"


def _infer_sfx_category(member_path: PurePosixPath) -> str:
    norm_parts = [
        re.sub(r"[^a-z0-9]+", "", p.lower())
        for p in member_path.parts
        if p and p not in {".", ".."}
    ]
    for part in norm_parts:
        for category, aliases in _SFX_CATEGORY_ALIASES.items():
            if part in aliases:
                return category

    label_text = "_".join(norm_parts)
    for category, keywords in _SFX_KEYWORDS.items():
        if any(k in label_text for k in keywords):
            return category
    return "foley"


def _ensure_unique_dest(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    counter = 2
    while True:
        candidate = path.with_name(f"{stem}_{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _build_sfx_inventory(asset_root: Path, sample_limit: int = 8) -> dict:
    categories: dict[str, dict] = {}
    total_files = 0

    for category in SUPPORTED_SFX_CATEGORIES:
        cat_dir = asset_root / category
        if not cat_dir.exists():
            cat_dir.mkdir(parents=True, exist_ok=True)
        files = sorted(
            [
                p for p in cat_dir.iterdir()
                if p.is_file() and p.suffix.lower() in ALLOWED_SFX_EXTENSIONS
            ],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        total_files += len(files)
        categories[category] = {
            "count": len(files),
            "files": [p.name for p in files[:sample_limit]],
        }

    return {
        "root": str(asset_root),
        "total_files": total_files,
        "categories": categories,
    }


def _import_sfx_zip(zip_path: Path, asset_root: Path) -> dict:
    imported_by_category = {k: 0 for k in SUPPORTED_SFX_CATEGORIES}
    skipped_non_audio = 0
    skipped_too_large = 0
    imported_count = 0
    skipped_bad_entries = 0

    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            member = PurePosixPath(info.filename)
            ext = member.suffix.lower()
            if ext not in ALLOWED_SFX_EXTENSIONS:
                skipped_non_audio += 1
                continue
            if info.file_size > MAX_SFX_MEMBER_MB * 1024 * 1024:
                skipped_too_large += 1
                continue

            category = _infer_sfx_category(member)
            out_dir = asset_root / category
            out_dir.mkdir(parents=True, exist_ok=True)

            raw_stem = "_".join(member.with_suffix("").parts[-2:]) if len(member.parts) >= 2 else member.stem
            safe_name = f"{_safe_asset_stem(raw_stem)}{ext}"
            out_path = _ensure_unique_dest(out_dir / safe_name)
            try:
                with archive.open(info, "r") as src, out_path.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
            except Exception:
                skipped_bad_entries += 1
                continue

            imported_by_category[category] += 1
            imported_count += 1

    return {
        "imported_count": imported_count,
        "imported_by_category": imported_by_category,
        "skipped_non_audio": skipped_non_audio,
        "skipped_too_large": skipped_too_large,
        "skipped_bad_entries": skipped_bad_entries,
    }


def _normalize_jamendo_client_id(raw: str) -> str:
    """
    Accept common copy/paste formats and extract the actual Jamendo client_id.
    Supported inputs:
      - plain client_id
      - client_id=XXXX
      - full URL/query string containing client_id=XXXX
      - client_id:client_secret  (keeps left side)
    """
    value = (raw or "").strip()
    if not value:
        return value

    # Full URL with query params
    if "://" in value and "client_id=" in value:
        parsed = urlparse(value)
        candidate = (parse_qs(parsed.query).get("client_id") or [None])[0]
        if candidate:
            return candidate.strip()

    # Raw query fragment style
    if value.startswith("client_id="):
        return value.split("=", 1)[1].strip()

    # client_id:client_secret
    if ":" in value and " " not in value:
        left = value.split(":", 1)[0].strip()
        if left:
            return left

    return value


@router.get("/api-keys", response_model=list)
async def list_api_keys(current_user: dict = Depends(get_current_user)):
    keys = await db.search(db.api_keys, "user_id", current_user["id"])
    return [
        {
            "id":          k["id"],
            "service":     k["service"],
            "label":       k.get("label", ""),
            "key_preview": k.get("key_preview", "****"),
            "is_valid":    k.get("is_valid"),
            "created_at":  k.get("created_at"),
        }
        for k in keys
    ]


@router.post("/api-keys", status_code=201, response_model=dict)
async def add_api_key(req: ApiKeyCreate, current_user: dict = Depends(get_current_user)):
    if req.service not in SUPPORTED_SERVICES:
        raise HTTPException(422, f"Unsupported service. Choose from: {SUPPORTED_SERVICES}")
    key_value = req.key.strip()
    if req.service == "jamendo":
        key_value = _normalize_jamendo_client_id(key_value)
    if not key_value:
        raise HTTPException(422, "API key cannot be empty")

    record = {
        "id":            str(uuid.uuid4()),
        "user_id":       current_user["id"],
        "service":       req.service,
        "label":         req.label or req.service.capitalize(),
        "key_encrypted": encrypt_key(key_value),
        "key_preview":   mask_key(key_value),
        "is_valid":      None,
        "created_at":    datetime.utcnow().isoformat(),
    }
    await db.insert(db.api_keys, record)
    return {k: v for k, v in record.items() if k not in ("key_encrypted", "user_id")}


@router.delete("/api-keys/{key_id}", response_model=dict)
async def delete_api_key(key_id: str, current_user: dict = Depends(get_current_user)):
    key = await db.get_by_id(db.api_keys, key_id)
    if not key or key.get("user_id") != current_user["id"]:
        raise HTTPException(404, "API key not found")
    await db.delete_by_id(db.api_keys, key_id)
    return {"success": True}


@router.post("/api-keys/{key_id}/validate", response_model=dict)
async def validate_api_key(key_id: str, current_user: dict = Depends(get_current_user)):
    key = await db.get_by_id(db.api_keys, key_id)
    if not key or key.get("user_id") != current_user["id"]:
        raise HTTPException(404, "API key not found")
    plain = decrypt_key(key["key_encrypted"])
    is_valid = await _validate(key["service"], plain)
    await db.update_by_id(db.api_keys, key_id, {"is_valid": is_valid})
    return {"valid": is_valid, "service": key["service"]}


async def _validate(service: str, key: str) -> bool:
    """Validate API key using a lightweight TTS streaming call."""
    try:
        import httpx
        if service == "elevenlabs":
            # Use /v1/text-to-speech/{voice_id}/stream — works with tts-only scope keys
            # Only request 1 character to minimise credit usage
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    "https://api.elevenlabs.io/v1/text-to-speech/pNInz6obpgDQGcFmaJgB/stream",
                    headers={"xi-api-key": key, "Content-Type": "application/json"},
                    json={"text": ".", "model_id": "eleven_multilingual_v2"}
                )
                # 200 = valid key with TTS access; 401/403 = invalid
                return r.status_code == 200
        if service == "jamendo":
            # Jamendo uses client_id; lightweight probe against tracks endpoint.
            client_id = _normalize_jamendo_client_id(key)
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    "https://api.jamendo.com/v3.0/tracks/",
                    params={"client_id": client_id, "format": "json", "limit": 1},
                )
                if r.status_code != 200:
                    return False
                data = r.json()
                headers = data.get("headers") or {}
                status = str(headers.get("status", "")).lower()
                code = int(headers.get("code", -1))
                # code=5 is Jamendo's invalid credential error.
                if code == 5:
                    return False
                # Treat other non-auth API statuses as potentially transient to avoid false negatives.
                return status == "success" or code != 5
        return bool(key)
    except Exception:
        return False


def get_user_api_key(user_id: str, service: str) -> str | None:
    """Sync helper for pipeline — returns decrypted key or None."""
    import asyncio
    try:
        keys = asyncio.run(db.search(db.api_keys, "user_id", user_id))
    except RuntimeError:
        keys = db.search_sync(db.api_keys, "user_id", user_id)
    matches = [k for k in keys if k["service"] == service]
    if not matches:
        return None
    return decrypt_key(matches[-1]["key_encrypted"])


@router.patch("/profile", response_model=dict)
async def update_profile(req: ProfileUpdate, current_user: dict = Depends(get_current_user)):
    updates = {}
    if req.username and req.username != current_user["username"]:
        if len(req.username) < 3:
            raise HTTPException(422, "Username too short")
        all_users = await db.get_all(db.users)
        if any(u["username"] == req.username for u in all_users):
            raise HTTPException(409, "Username already taken")
        updates["username"] = req.username
    if req.email and req.email != current_user["email"]:
        if "@" not in req.email:
            raise HTTPException(422, "Invalid email")
        updates["email"] = req.email
    if updates:
        await db.update_by_id(db.users, current_user["id"], updates)
    return {**{k: v for k, v in current_user.items() if k != "password_hash"}, **updates}


@router.get("/sfx-library", response_model=dict)
async def get_sfx_library_inventory(current_user: dict = Depends(get_current_user)):
    _ = current_user
    return {"success": True, **_build_sfx_inventory(settings.RADIO_CUE_ASSETS_DIR)}


@router.post("/sfx-library/upload", response_model=dict, status_code=201)
async def upload_sfx_library(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    _ = current_user
    ext = Path(file.filename or "").suffix.lower()
    if ext != ".zip":
        raise HTTPException(415, "Please upload a .zip archive")

    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb <= 0:
        raise HTTPException(400, "Uploaded archive is empty")
    if size_mb > MAX_SFX_ZIP_MB:
        raise HTTPException(413, f"SFX library too large ({size_mb:.1f} MB). Max: {MAX_SFX_ZIP_MB} MB")

    temp_zip = settings.UPLOAD_DIR / f"sfx_import_{uuid.uuid4().hex}.zip"
    temp_zip.write_bytes(content)
    try:
        try:
            import_report = _import_sfx_zip(temp_zip, settings.RADIO_CUE_ASSETS_DIR)
        except zipfile.BadZipFile as exc:
            raise HTTPException(422, "Invalid ZIP archive") from exc
    finally:
        temp_zip.unlink(missing_ok=True)

    inventory = _build_sfx_inventory(settings.RADIO_CUE_ASSETS_DIR)
    return {
        "success": True,
        "message": "SFX library imported",
        "import_report": import_report,
        "inventory": inventory,
    }
