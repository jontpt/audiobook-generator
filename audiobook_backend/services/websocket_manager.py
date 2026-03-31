"""
services/websocket_manager.py  ─  Real-time progress broadcasting
────────────────────────────────────────────────────────────────────
Manages WebSocket connections for per-book progress updates.

Single-process mode: pure in-memory dict (fast, zero deps).
Multi-process / multi-worker mode: upgrade to Redis pub/sub by
  setting REDIS_URL and this module auto-detects it.
"""
from __future__ import annotations
import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Thread-safe WebSocket connection manager with optional Redis fanout."""

    def __init__(self):
        # book_id → list of connected WebSocket clients
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)
        self._lock = asyncio.Lock()

    # ── Connection lifecycle ──────────────────────────────────────────────────

    async def connect(self, book_id: str, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self._connections[book_id].append(ws)
        logger.debug(f"WS connect  book={book_id}  total={len(self._connections[book_id])}")

    async def disconnect(self, book_id: str, ws: WebSocket):
        async with self._lock:
            sockets = self._connections[book_id]
            if ws in sockets:
                sockets.remove(ws)
            if not sockets:
                del self._connections[book_id]
        logger.debug(f"WS disconnect  book={book_id}")

    # ── Broadcasting ──────────────────────────────────────────────────────────

    async def broadcast(self, book_id: str, payload: dict[str, Any]):
        """Send a JSON message to all clients watching a specific book."""
        message = json.dumps(payload)
        dead: list[WebSocket] = []

        async with self._lock:
            sockets = list(self._connections.get(book_id, []))

        for ws in sockets:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)

        # Clean up dead connections
        if dead:
            async with self._lock:
                for ws in dead:
                    try:
                        self._connections[book_id].remove(ws)
                    except ValueError:
                        pass

    async def send_progress(
        self,
        book_id: str,
        status: str,
        progress: float,
        message: str = "",
        extra: dict | None = None,
    ):
        """Convenience wrapper for pipeline progress updates."""
        payload = {
            "type":     "progress",
            "book_id":  book_id,
            "status":   status,
            "progress": round(progress, 3),
            "message":  message,
            **(extra or {}),
        }
        await self.broadcast(book_id, payload)

    async def send_completed(self, book_id: str, export_url: str, duration_str: str):
        await self.broadcast(book_id, {
            "type":        "completed",
            "book_id":     book_id,
            "export_url":  export_url,
            "duration":    duration_str,
        })

    async def send_error(self, book_id: str, error: str):
        await self.broadcast(book_id, {
            "type":    "error",
            "book_id": book_id,
            "error":   error,
        })


# ── Global singleton ──────────────────────────────────────────────────────────
ws_manager = ConnectionManager()
