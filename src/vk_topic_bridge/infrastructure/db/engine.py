"""Async SQLAlchemy engine factory with per-connection SQLite PRAGMAs (plan §5, docs 05 §9)."""

from sqlalchemy import event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.ext.asyncio import (
    create_async_engine as _create_async_engine,
)
from sqlalchemy.pool import ConnectionPoolEntry

SQLITE_PRAGMAS: tuple[str, ...] = (
    "PRAGMA foreign_keys=ON",
    "PRAGMA journal_mode=WAL",
    "PRAGMA busy_timeout=5000",
)


def _apply_sqlite_pragmas(
    dbapi_connection: DBAPIConnection,
    _connection_record: ConnectionPoolEntry,
) -> None:
    """Apply PRAGMAs to every physical connection, not once per engine/pool."""
    cursor = dbapi_connection.cursor()
    try:
        for pragma in SQLITE_PRAGMAS:
            cursor.execute(pragma)
    finally:
        cursor.close()


def create_async_engine(database_url: str) -> AsyncEngine:
    """Create an async engine and install the SQLite PRAGMA listener before first use."""
    engine = _create_async_engine(database_url)
    event.listens_for(engine.sync_engine, "connect")(_apply_sqlite_pragmas)
    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Session factory; `expire_on_commit=False` keeps loaded attributes usable after commit."""
    return async_sessionmaker(engine, expire_on_commit=False)


async def dispose_engine(engine: AsyncEngine) -> None:
    """Release the connection pool; last step of the shutdown order (plan §7)."""
    await engine.dispose()
