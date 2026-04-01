"""
api/routes/settings.py — API key management + profile update endpoints
"""
from __future__ import annotations
import uuid
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from models.database import db
from api.routes.auth import get_current_user
from services.auth_service import encrypt_key, decrypt_key, mask_key

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["Settings"])

SUPPORTED_SERVICES = {"elevenlabs", "mubert", "soundraw"}


class ApiKeyCreate(BaseModel):
    service: str
    label:   str = ""
    key:     str


class ProfileUpdate(BaseModel):
    username: str | None = None
    email:    str | None = None


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
    if not req.key.strip():
        raise HTTPException(422, "API key cannot be empty")

    record = {
        "id":            str(uuid.uuid4()),
        "user_id":       current_user["id"],
        "service":       req.service,
        "label":         req.label or req.service.capitalize(),
        "key_encrypted": encrypt_key(req.key.strip()),
        "key_preview":   mask_key(req.key.strip()),
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
    """Validate API key by testing a lightweight service call."""
    try:
        import httpx
        if service == "elevenlabs":
            # Use /v1/models (no user_read permission required)
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    "https://api.elevenlabs.io/v1/models",
                    headers={"xi-api-key": key}
                )
                return r.status_code == 200
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
