"""
api/routes/auth.py — Registration, Login, Me, Change-password endpoints
"""
from __future__ import annotations
import uuid
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel

from models.database import db
from services.auth_service import (
    hash_password, verify_password, create_access_token, decode_token
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentication"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        payload = decode_token(token)
    except ValueError as exc:
        raise HTTPException(401, str(exc), headers={"WWW-Authenticate": "Bearer"})
    user = await db.get_by_id(db.users, payload["sub"])
    if not user or not user.get("is_active", True):
        raise HTTPException(401, "User not found or inactive")
    return user


@router.post("/register", status_code=201)
async def register(req: RegisterRequest):
    if len(req.username) < 3:
        raise HTTPException(422, "Username must be at least 3 characters")
    if "@" not in req.email:
        raise HTTPException(422, "Invalid email address")
    if len(req.password) < 8:
        raise HTTPException(422, "Password must be at least 8 characters")

    existing_users = await db.get_all(db.users)
    if any(u.get("username") == req.username for u in existing_users):
        raise HTTPException(409, "Username already taken")
    if any(u.get("email") == req.email for u in existing_users):
        raise HTTPException(409, "Email already registered")

    user = {
        "id":            str(uuid.uuid4()),
        "username":      req.username,
        "email":         req.email,
        "password_hash": hash_password(req.password),
        "is_active":     True,
        "created_at":    datetime.utcnow().isoformat(),
    }
    await db.insert(db.users, user)
    logger.info(f"New user registered: {req.username}")
    return {k: v for k, v in user.items() if k != "password_hash"}


@router.post("/login")
async def login(form: OAuth2PasswordRequestForm = Depends()):
    all_users = await db.get_all(db.users)
    user = next(
        (u for u in all_users
         if u.get("username") == form.username or u.get("email") == form.username),
        None
    )
    if not user or not verify_password(form.password, user.get("password_hash", "")):
        raise HTTPException(401, "Invalid credentials")
    if not user.get("is_active", True):
        raise HTTPException(403, "Account is disabled")

    token = create_access_token(user["id"], user["username"])
    logger.info(f"User logged in: {user['username']}")
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user)):
    return {k: v for k, v in current_user.items() if k != "password_hash"}


@router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    if not verify_password(req.current_password, current_user.get("password_hash", "")):
        raise HTTPException(400, "Current password is incorrect")
    if len(req.new_password) < 8:
        raise HTTPException(422, "New password must be at least 8 characters")
    await db.update_by_id(db.users, current_user["id"],
                          {"password_hash": hash_password(req.new_password)})
    return {"success": True, "message": "Password updated"}
