"""Shared temp-file SQLite fixtures for DB integration tests (docs 05 §19.3).

Every test gets a real on-disk database under ``tmp_path`` seeded by the Alembic
migration, so repositories are exercised against the migrated schema rather than
``metadata.create_all()``.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from vk_topic_bridge.infrastructure.db.engine import create_async_engine, create_session_factory

REPO_ROOT = Path(__file__).resolve().parents[3]
SessionFactory = async_sessionmaker[AsyncSession]


@pytest.fixture
def database_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    url = f"sqlite+aiosqlite:///{tmp_path / 'integration.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    command.upgrade(config, "head")
    return url


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    db_engine = create_async_engine(database_url)
    try:
        yield db_engine
    finally:
        await db_engine.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> SessionFactory:
    return create_session_factory(engine)


@pytest.fixture
async def session(session_factory: SessionFactory) -> AsyncIterator[AsyncSession]:
    async with session_factory() as db_session:
        yield db_session
