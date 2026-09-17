"""Integration tests for per-connection SQLite PRAGMAs applied by the async engine."""

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from vk_topic_bridge.infrastructure.db.engine import create_async_engine

EXPECTED_PRAGMAS = {
    "foreign_keys": 1,
    "journal_mode": "wal",
    "busy_timeout": 5000,
}


def _async_url(db_path: Path) -> str:
    return f"sqlite+aiosqlite:///{db_path}"


async def _read_pragmas(engine: AsyncEngine) -> dict[str, int | str]:
    async with engine.connect() as connection:
        observed: dict[str, int | str] = {}
        for pragma in EXPECTED_PRAGMAS:
            value = (await connection.execute(text(f"PRAGMA {pragma}"))).scalar()
            observed[pragma] = value.lower() if isinstance(value, str) else value
        return observed


async def test_pragmas_are_applied_to_a_real_connection(tmp_path: Path) -> None:
    engine = create_async_engine(_async_url(tmp_path / "pragmas.db"))

    observed = await _read_pragmas(engine)

    await engine.dispose()
    print(" ".join(f"{name}={value}" for name, value in observed.items()))
    assert observed == EXPECTED_PRAGMAS


async def test_pragmas_are_applied_to_each_fresh_physical_connection(tmp_path: Path) -> None:
    engine = create_async_engine(_async_url(tmp_path / "pragmas-fresh.db"))

    first = await _read_pragmas(engine)
    # Disposing closes the pool, so the next connect is a brand-new DBAPI connection.
    await engine.dispose()
    second = await _read_pragmas(engine)
    await engine.dispose()

    assert first == EXPECTED_PRAGMAS
    assert second == EXPECTED_PRAGMAS
