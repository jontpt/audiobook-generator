"""
services/auth_service.py — JWT-based authentication service
"""
from __future__ import annotations
import hashlib
import hmac
import time
import uuid
import logging
from datetime import datetime, timedelta
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)

SECRET = settings.SECRET_KEY.encode()
ALGORITHM = "HS256"

# ─────────────────────────────────────────────────────────────────────────────
# Password hashing (PBKDF2 — no extra deps needed)
# ─────────────────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = uuid.uuid4().hex
    key  = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"pbkdf2:sha256:260000${salt}${key.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    try:
        _, rest    = hashed.split("$", 1)
        salt, key  = rest.split("$", 1)
        candidate  = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
        return hmac.compare_digest(candidate.hex(), key)
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# JWT (manual implementation — no python-jose needed)
# ─────────────────────────────────────────────────────────────────────────────
import base64, json as _json

def _b64url_enc(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def _b64url_dec(s: str) -> bytes:
    pad = 4 - len(s) % 4
    return base64.urlsafe_b64decode(s + "=" * (pad % 4))


def create_access_token(user_id: str, username: str) -> str:
    header  = _b64url_enc(_json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url_enc(_json.dumps({
        "sub":      user_id,
        "username": username,
        "exp":      int(time.time()) + settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "iat":      int(time.time()),
    }).encode())
    sig = _b64url_enc(hmac.new(SECRET, f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def decode_token(token: str) -> dict:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Malformed token")
        header, payload, sig = parts
        expected_sig = _b64url_enc(
            hmac.new(SECRET, f"{header}.{payload}".encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(sig, expected_sig):
            raise ValueError("Invalid signature")
        data = _json.loads(_b64url_dec(payload))
        if data.get("exp", 0) < time.time():
            raise ValueError("Token expired")
        return data
    except Exception as exc:
        raise ValueError(f"Invalid token: {exc}") from exc


# ─────────────────────────────────────────────────────────────────────────────
# API-key encryption (simple XOR + hex — swap for Fernet in production)
# ─────────────────────────────────────────────────────────────────────────────

def _encryption_key() -> bytes:
    return hashlib.sha256(SECRET).digest()

def encrypt_key(plain: str) -> str:
    key   = _encryption_key()
    data  = plain.encode()
    xored = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    return xored.hex()

def decrypt_key(cipher: str) -> str:
    key   = _encryption_key()
    data  = bytes.fromhex(cipher)
    xored = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    return xored.decode()

def mask_key(key: str) -> str:
    """Return first4...last4 preview."""
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}...{key[-4:]}"
