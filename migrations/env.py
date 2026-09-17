"""Alembic environment: async engine, DATABASE_URL from the environment, batch mode."""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from config import DEFAULT_DATABASE_URL
from vk_topic_bridge.infrastructure.db import models  # noqa: F401  (registers metadata)
from vk_topic_bridge.infrastructure.db.base import Base


class _DatabaseSettings(BaseSettings):
    """Reads DATABASE_URL from the same `.env` as the app without demanding its secrets."""

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_ignore_empty=True, case_sensitive=False
    )

    DATABASE_URL: str = DEFAULT_DATABASE_URL


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return url
    return _DatabaseSettings().DATABASE_URL


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting to a database."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    config.set_main_option("sqlalchemy.url", _database_url().replace("%", "%%"))
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
