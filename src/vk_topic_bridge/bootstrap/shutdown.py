"""Coordinated shutdown: one failing step never skips the remaining ones.

Order (plan §7): stop pollers, close the Bot API session, disconnect Telethon, dispose
the engine, then flush the logging pipeline.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from logger import flush_logging
from vk_topic_bridge.bootstrap.container import AppContainer
from vk_topic_bridge.infrastructure.db.engine import dispose_engine

logger = logging.getLogger(__name__)


@runtime_checkable
class _Disconnectable(Protocol):
    """A client that releases its connection on ``disconnect`` (Telethon shape)."""

    async def disconnect(self) -> None: ...


async def _run_step(
    name: str,
    action: Callable[[], Awaitable[None]] | None,
    failures: list[str],
) -> None:
    if action is None:
        return
    try:
        await action()
    except Exception:
        failures.append(name)
        logger.exception("shutdown step failed: %s", name)


async def shutdown(container: AppContainer) -> None:
    """Release every resource; guaranteed to attempt all steps."""
    failures: list[str] = []
    await _run_step("vk_polling_stop", container.vk_polling_stop, failures)
    await _run_step("polling_stop", container.polling_stop, failures)
    await _run_step("http_session_close", container.http_session.close, failures)
    await _run_step("bot_session", container.bot.session.close, failures)
    client = container.telethon_client
    if isinstance(client, _Disconnectable):
        await _run_step("telethon_disconnect", client.disconnect, failures)
    await _run_step("engine_dispose", lambda: dispose_engine(container.engine), failures)
    try:
        flush_logging()
    except Exception:
        failures.append("flush_logging")
        logger.exception("shutdown step failed: flush_logging")
    if failures:
        logger.warning("shutdown completed with failed steps: %s", ", ".join(failures))
