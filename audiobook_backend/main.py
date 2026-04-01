"""
main.py — FastAPI application entry point (v2.1)
"""
from __future__ import annotations
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from config import settings, BASE_DIR

logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%H:%M:%S", stream=sys.stdout,
)
logger = logging.getLogger("audiobook")


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Init async DB
    from models.database import db
    await db.init()

    # Seed demo user
    await _seed_demo_user()

    ev  = "✅" if settings.ELEVENLABS_API_KEY else "⚠️  NOT SET (mock mode)"
    cel = "✅ Celery + Redis" if settings.USE_CELERY else "⚠️  BackgroundTasks (dev)"
    logger.info(f"🎧 {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"   DB          : {settings.DATABASE_URL.split('@')[-1]}")
    logger.info(f"   ElevenLabs  : {ev}")
    logger.info(f"   Task queue  : {cel}")
    yield
    logger.info("Shutting down…")


async def _seed_demo_user():
    from models.database import db
    from services.auth_service import hash_password
    import uuid
    from datetime import datetime
    all_users = await db.get_all(db.users)
    if not any(u.get("username") == "demo" for u in all_users):
        await db.insert(db.users, {
            "id":            str(uuid.uuid4()),
            "username":      "demo",
            "email":         "demo@audiobook.ai",
            "password_hash": hash_password("demo1234"),
            "is_active":     True,
            "created_at":    datetime.utcnow().isoformat(),
        })
        logger.info("Demo user seeded: demo / demo1234")


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI Audiobook Generator — multi-voice TTS, emotion-aware narration.",
    docs_url="/docs", redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── System endpoints (registered FIRST so SPA catch-all doesn't shadow them) ─

@app.get("/health", tags=["System"])
async def health():
    from models.database import db
    books = await db.get_all(db.books)
    return {
        "status":                "healthy",
        "version":               settings.APP_VERSION,
        "books_in_db":           len(books),
        "elevenlabs_configured": bool(settings.ELEVENLABS_API_KEY),
        "celery_enabled":        settings.USE_CELERY,
        "mock_mode":             not bool(settings.ELEVENLABS_API_KEY),
    }

@app.get("/", tags=["System"], include_in_schema=False)
async def root():
    # Serve React SPA if frontend is built, otherwise return API info JSON
    _dist = BASE_DIR.parent / "audiobook_frontend" / "dist"
    _dist_docker = BASE_DIR / "frontend" / "dist"
    _frontend = _dist if _dist.exists() else (_dist_docker if _dist_docker.exists() else None)
    if _frontend:
        return FileResponse(str(_frontend / "index.html"))
    return {"name": settings.APP_NAME, "version": settings.APP_VERSION,
            "docs": "/docs", "status": "running"}


# ─── API Routers ──────────────────────────────────────────────────────────────

from api.routes.auth       import router as auth_router
from api.routes.settings   import router as settings_router
from api.routes.books      import router as books_router
from api.routes.characters import router as chars_router
from api.routes.tts        import router as tts_router
from api.routes.export     import router as export_router

app.include_router(auth_router,     prefix="/api/v1")
app.include_router(settings_router, prefix="/api/v1")
app.include_router(books_router,    prefix="/api/v1")
app.include_router(chars_router,    prefix="/api/v1")
app.include_router(tts_router,      prefix="/api/v1")
app.include_router(export_router,   prefix="/api/v1")

@app.get("/api/v1/stats", tags=["System"])
async def stats():
    from models.database import db
    books = await db.get_all(db.books)
    sc: dict = {}
    for b in books:
        s = b.get("status", "unknown")
        sc[s] = sc.get(s, 0) + 1
    return {
        "total_books":      len(books),
        "status_breakdown": sc,
        "total_characters": len(await db.get_all(db.characters)),
        "total_segments":   len(await db.get_all(db.segments)),
        "total_chapters":   len(await db.get_all(db.chapters)),
    }


# ─── Exception handlers ────────────────────────────────────────────────────────

@app.exception_handler(ValueError)
async def _val_err(request: Request, exc: ValueError):
    return JSONResponse(422, {"success": False, "error": str(exc)})

@app.exception_handler(Exception)
async def _generic(request: Request, exc: Exception):
    logger.error(f"Unhandled: {exc}", exc_info=True)
    return JSONResponse(500, {"success": False, "error": "Internal server error"})


# ─── Serve React frontend (LAST — SPA catch-all) ──────────────────────────────

# Check both sibling dir (dev) and /app/frontend (Docker)
_DIST = BASE_DIR.parent / "audiobook_frontend" / "dist"
_DIST_DOCKER = BASE_DIR / "frontend" / "dist"
_FRONTEND_DIST = _DIST if _DIST.exists() else (_DIST_DOCKER if _DIST_DOCKER.exists() else None)

if _FRONTEND_DIST:
    _ASSETS = _FRONTEND_DIST / "assets"
    if _ASSETS.exists():
        app.mount("/assets", StaticFiles(directory=str(_ASSETS)), name="assets")

    @app.get("/favicon.ico", include_in_schema=False)
    async def _fav():
        f = _FRONTEND_DIST / "favicon.ico"
        return FileResponse(str(f)) if f.exists() else JSONResponse({}, 204)

    # SPA catch-all — must be LAST
    @app.get("/{path:path}", include_in_schema=False)
    async def _spa(path: str):
        # Let API and system paths bubble up to their own handlers
        if path.startswith(("api/", "docs", "redoc", "openapi", "health")):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return FileResponse(str(_FRONTEND_DIST / "index.html"))

    logger.info(f"React app served from {_FRONTEND_DIST}")
else:
    logger.warning("Frontend dist/ not found — API-only mode")


# ─── Dev runner ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000,
                reload=settings.DEBUG, log_level="info")
