"""
models/database.py  ─  Universal database layer
─────────────────────────────────────────────────
• SQLite  (default, zero-config)  DATABASE_URL=sqlite+aiosqlite:///./storage/db.sqlite
• PostgreSQL (production)         DATABASE_URL=postgresql+asyncpg://user:pass@host/db

Uses SQLAlchemy 2.0 async with a JSON/JSONB "document" column per table so the
rest of the app doesn't need to change from the original TinyDB-based API.
"""
from __future__ import annotations
import json, logging
from datetime import datetime, date
from typing import Any

from sqlalchemy import (
    Column, String, Text, DateTime,
    create_engine, text, select, update, delete, insert
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base, mapped_column, Mapped

from config import settings

logger = logging.getLogger(__name__)

# ─── Choose engine from DATABASE_URL ──────────────────────────────────────────
_RAW_URL = settings.DATABASE_URL

# Convert sync URL to async dialect
def _async_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):          # Railway uses this
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    return url

_ASYNC_URL = _async_url(_RAW_URL)
_is_sqlite = "sqlite" in _ASYNC_URL

engine = create_async_engine(
    _ASYNC_URL,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

Base = declarative_base()

# ─── Generic JSON-document table ──────────────────────────────────────────────

def _make_table(name: str):
    """Dynamically create a SQLAlchemy model whose payload is a JSON blob."""
    attrs = {
        "__tablename__": name,
        "__table_args__": {"extend_existing": True},
        "id":         Column(String(64),  primary_key=True, index=True),
        "payload":    Column(Text,         nullable=False),
        "created_at": Column(DateTime,     default=datetime.utcnow),
    }
    return type(name.capitalize(), (Base,), attrs)

BooksTable      = _make_table("books")
CharactersTable = _make_table("characters")
ChaptersTable   = _make_table("chapters")
SegmentsTable   = _make_table("segments")
UsersTable      = _make_table("users")
ApiKeysTable    = _make_table("api_keys")


# ─── Serialisation helpers ────────────────────────────────────────────────────

def _to_json(obj: Any) -> str:
    def _default(o):
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        if hasattr(o, "value"):
            return o.value          # Enums
        raise TypeError(f"Not serialisable: {type(o)}")
    return json.dumps(obj, default=_default)

def _from_json(text: str) -> dict:
    return json.loads(text) if text else {}


# ─── Database class (same public API as the old TinyDB version) ───────────────

class Database:
    """
    Async-first database wrapper.
    Every method is a coroutine; call with `await db.insert(...)`.

    Fallback sync wrappers (insert_sync / get_by_id_sync / …) are provided
    for Celery workers that can't easily run an event loop.
    """

    # Reference "tables" so call-sites can do db.books, db.users, etc.
    books      = BooksTable
    characters = CharactersTable
    chapters   = ChaptersTable
    segments   = SegmentsTable
    users      = UsersTable
    api_keys   = ApiKeysTable

    async def init(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info(f"Database ready: {_ASYNC_URL.split('@')[-1]}")  # hide credentials

    # ── Async CRUD ─────────────────────────────────────────────────────────────

    async def insert(self, table, record: dict) -> str:
        rec_id = record.get("id", "")
        async with AsyncSessionLocal() as session:
            session.add(table(id=rec_id, payload=_to_json(record)))
            await session.commit()
        return rec_id

    async def get_by_id(self, table, record_id: str) -> dict | None:
        async with AsyncSessionLocal() as session:
            row = await session.get(table, record_id)
            return _from_json(row.payload) if row else None

    async def get_all(self, table) -> list[dict]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(table))
            return [_from_json(r.payload) for r in result.scalars().all()]

    async def update_by_id(self, table, record_id: str, updates: dict):
        async with AsyncSessionLocal() as session:
            row = await session.get(table, record_id)
            if row:
                current = _from_json(row.payload)
                current.update(updates)
                row.payload = _to_json(current)
                await session.commit()

    async def delete_by_id(self, table, record_id: str):
        async with AsyncSessionLocal() as session:
            row = await session.get(table, record_id)
            if row:
                await session.delete(row)
                await session.commit()

    async def search(self, table, field: str, value) -> list[dict]:
        """
        Filter rows where payload JSON contains field == value.
        Works on both SQLite (JSON_EXTRACT) and PostgreSQL (JSON ->> 'key').
        """
        async with AsyncSessionLocal() as session:
            if _is_sqlite:
                stmt = select(table).where(
                    text(f"json_extract(payload, '$.{field}') = :v")
                ).params(v=value)
            else:
                stmt = select(table).where(
                    text(f"payload->>'{field}' = :v")
                ).params(v=str(value))
            result = await session.execute(stmt)
            return [_from_json(r.payload) for r in result.scalars().all()]

    # ── Sync wrappers (for Celery tasks) ──────────────────────────────────────

    def _run(self, coro):
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(asyncio.run, coro)
                    return future.result()
            return loop.run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)

    def insert_sync(self, table, record: dict) -> str:
        return self._run(self.insert(table, record))

    def get_by_id_sync(self, table, record_id: str) -> dict | None:
        return self._run(self.get_by_id(table, record_id))

    def get_all_sync(self, table) -> list[dict]:
        return self._run(self.get_all(table))

    def update_by_id_sync(self, table, record_id: str, updates: dict):
        self._run(self.update_by_id(table, record_id, updates))

    def delete_by_id_sync(self, table, record_id: str):
        self._run(self.delete_by_id(table, record_id))

    def search_sync(self, table, field: str, value) -> list[dict]:
        return self._run(self.search(table, field, value))

    def close(self):
        pass   # Engine lifecycle is managed by FastAPI lifespan


# Singleton instance
db = Database()
