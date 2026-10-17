import os
from pathlib import Path
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import event, text
from synctohdd.db.models import Base
from synctohdd.utils.logger import logger

_engine = None
_session_factory = None

def get_database_url(db_path: str = "./data/synctohdd.db") -> str:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    abs_path = path.resolve()
    # Replace backslashes on Windows for SQLite URI
    posix_path = abs_path.as_posix()
    return f"sqlite+aiosqlite:///{posix_path}"

def get_engine(db_path: str = "./data/synctohdd.db"):
    global _engine, _session_factory
    if _engine is None:
        db_url = get_database_url(db_path)
        _engine = create_async_engine(
            db_url,
            echo=False,
            future=True,
            connect_args={"check_same_thread": False},
        )
        _session_factory = async_sessionmaker(
            bind=_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _engine

def get_session_factory(db_path: str = "./data/synctohdd.db") -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        get_engine(db_path)
    return _session_factory

async def init_db(db_path: str = "./data/synctohdd.db") -> None:
    """Initialize database tables and enable WAL mode."""
    engine = get_engine(db_path)
    async with engine.begin() as conn:
        # Enable WAL mode and foreign keys in SQLite
        await conn.execute(text("PRAGMA journal_mode = WAL;"))
        await conn.execute(text("PRAGMA foreign_keys = ON;"))
        await conn.run_sync(Base.metadata.create_all)
    logger.info(f"Database initialized at {db_path}")

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for FastAPI route handlers."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        finally:
            await session.close()
