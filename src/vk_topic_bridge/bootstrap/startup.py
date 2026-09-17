"""Fatal startup sequence: every check must pass before any poller is allowed to run.

The sequence is deliberately linear and fail-closed: a failure raises
``FatalStartupError`` with the matching reason and the caller refuses to start polling.
Revalidation of a persisted chat is fatal, while a clean database without a registered
chat is a valid state — otherwise ``/register`` could never run.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Connection

from config import Settings
from logger import redact_secrets
from vk_topic_bridge.application.dto.readiness import ReadinessState
from vk_topic_bridge.bootstrap.container import AppContainer
from vk_topic_bridge.domain.errors import FatalStartupError, FatalStartupReason

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MIGRATIONS_DIR = _REPO_ROOT / "migrations"


def _secret_values(settings: Settings) -> tuple[str, ...]:
    """Secret values that may be embedded in a third-party exception message."""
    values = [
        settings.TELEGRAM_BOT_TOKEN.get_secret_value(),
        settings.TELEGRAM_API_HASH.get_secret_value(),
        settings.VK_GROUP_TOKEN.get_secret_value(),
    ]
    if settings.TELEGRAM_MTPROXY_SECRET is not None:
        values.append(settings.TELEGRAM_MTPROXY_SECRET.get_secret_value())
    return tuple(values)


def _safe_detail(container_or_settings: AppContainer | Settings, exc: BaseException) -> str:
    """Render an exception for ``FatalStartupError`` without leaking configured secrets."""
    settings = (
        container_or_settings.settings
        if isinstance(container_or_settings, AppContainer)
        else container_or_settings
    )
    return redact_secrets(str(exc), _secret_values(settings))


@runtime_checkable
class _Connectable(Protocol):
    """Telethon-shape client that must be connected before its first request."""

    async def connect(self) -> None: ...


@dataclass(frozen=True, slots=True)
class StartupDeps:
    """Settings plus the fully wired container the checks operate on."""

    settings: Settings
    container: AppContainer


def _alembic_config() -> Config:
    config = Config(str(_REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_MIGRATIONS_DIR))
    return config


def _read_single_head() -> str | None:
    heads = ScriptDirectory.from_config(_alembic_config()).get_heads()
    return heads[0] if len(heads) == 1 else None


def _read_db_revision(connection: Connection) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


async def ensure_database_ready(container: AppContainer) -> None:
    """Verify the schema is reachable and exactly at the single Alembic head."""
    try:
        async with container.session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        raise FatalStartupError(
            FatalStartupReason.DB_UNAVAILABLE, _safe_detail(container, exc)
        ) from exc

    try:
        async with container.engine.connect() as connection:
            current = await connection.run_sync(_read_db_revision)
        head = _read_single_head()
    except FatalStartupError:
        raise
    except Exception as exc:
        raise FatalStartupError(
            FatalStartupReason.MIGRATION_FAILED, _safe_detail(container, exc)
        ) from exc

    if head is None or current != head:
        raise FatalStartupError(
            FatalStartupReason.MIGRATION_FAILED,
            f"database revision {current!r} does not match single head {head!r}",
        )


async def _verify_bot_api(container: AppContainer) -> None:
    try:
        await container.admin_port.get_me()
    except Exception as exc:
        raise FatalStartupError(
            FatalStartupReason.BOT_API_UNREACHABLE, _safe_detail(container, exc)
        ) from exc


async def _verify_telethon(container: AppContainer) -> None:
    client = container.telethon_client
    if isinstance(client, _Connectable):
        try:
            await client.connect()
        except Exception as exc:
            raise FatalStartupError(
                FatalStartupReason.TELETHON_UNAUTHORIZED, _safe_detail(container, exc)
            ) from exc
    try:
        authorized = await container.telethon_adapter.is_authorized()
    except Exception as exc:
        raise FatalStartupError(
            FatalStartupReason.TELETHON_UNAUTHORIZED, _safe_detail(container, exc)
        ) from exc
    if not authorized:
        raise FatalStartupError(
            FatalStartupReason.TELETHON_UNAUTHORIZED, "session is not authorized"
        )
    try:
        await container.telethon_adapter.get_me()
    except Exception as exc:
        raise FatalStartupError(
            FatalStartupReason.TELETHON_UNAUTHORIZED, _safe_detail(container, exc)
        ) from exc


async def _verify_vk(container: AppContainer) -> None:
    try:
        await container.vk_gateway.get_community_id()
    except Exception as exc:
        raise FatalStartupError(
            FatalStartupReason.VK_IDENTITY, _safe_detail(container, exc)
        ) from exc
    try:
        long_poll = await container.vk_gateway.check_long_poll()
    except Exception as exc:
        raise FatalStartupError(
            FatalStartupReason.VK_LONGPOLL_DISABLED, _safe_detail(container, exc)
        ) from exc
    if not long_poll.enabled:
        raise FatalStartupError(
            FatalStartupReason.VK_LONGPOLL_DISABLED, "Long Poll is disabled for the community"
        )


async def _verify_persisted_chat(container: AppContainer) -> bool:
    """Revalidate the registered chat; return whether a chat is persisted and valid."""
    async with container.uow_factory() as uow:
        state = await uow.bridge_settings.get()
    if state is None or state.telegram_chat_id is None:
        return False

    chat_id = state.telegram_chat_id
    try:
        access = await container.telethon_adapter.verify_chat_access(chat_id)
    except Exception as exc:
        raise FatalStartupError(
            FatalStartupReason.TELETHON_CHAT_ACCESS, _safe_detail(container, exc)
        ) from exc
    if access.entity_id != chat_id or not access.is_forum:
        raise FatalStartupError(
            FatalStartupReason.TELETHON_CHAT_ACCESS,
            f"chat {chat_id} resolved to entity {access.entity_id} (forum={access.is_forum})",
        )

    try:
        topics = await container.telethon_adapter.list_topics(chat_id)
    except Exception as exc:
        raise FatalStartupError(
            FatalStartupReason.TOPICS_UNAVAILABLE, _safe_detail(container, exc)
        ) from exc
    if not topics:
        raise FatalStartupError(
            FatalStartupReason.TOPICS_UNAVAILABLE, f"chat {chat_id} returned no forum topics"
        )

    destination_id = state.telegram_messages_topic_id
    if destination_id is not None:
        destination = next((topic for topic in topics if topic.topic_id == destination_id), None)
        if destination is None:
            raise FatalStartupError(
                FatalStartupReason.TOPICS_UNAVAILABLE,
                f"persisted destination topic {destination_id} is missing from chat {chat_id}",
            )
        if destination.is_closed or destination.is_hidden:
            state_name = "closed" if destination.is_closed else "hidden"
            raise FatalStartupError(
                FatalStartupReason.TOPICS_UNAVAILABLE,
                f"persisted destination topic {destination_id} is {state_name}",
            )
        container.readiness.advance(ReadinessState.DESTINATION_CONFIRMED)
        container.readiness.advance(ReadinessState.FORWARDING_ENABLED)
    else:
        container.readiness.advance(ReadinessState.TOPICS_READY)
    return True


async def run_startup_checks(deps: StartupDeps) -> None:
    """Run every fatal check in order; never starts a poller."""
    container = deps.container
    await ensure_database_ready(container)
    container.readiness.advance(ReadinessState.CORE_READY)
    await _verify_bot_api(container)
    await _verify_telethon(container)
    await _verify_vk(container)
    await _verify_persisted_chat(container)
