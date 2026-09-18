"""``/start`` onboarding compatibility module.

The real /start handling moved to ``routers/root.py`` (FSM reset + keyboard rendering).
This module keeps the historically imported ``ONBOARDING_TEXT`` and ``handle_start``
entry points for acceptance tests and wiring convenience; it has no placeholder logic.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from vk_topic_bridge.application.dto.settings import BridgeSettingsState
from vk_topic_bridge.presentation.telegram.routers.root import (
    ONBOARDING_TEXT,
    render_root_state,
)

START_COMMAND = "start"

type SettingsReader = Callable[[], Awaitable[BridgeSettingsState | None]]

__all__ = [
    "ONBOARDING_TEXT",
    "START_COMMAND",
    "SettingsReader",
    "build_start_router",
    "handle_start",
]


async def handle_start(message: Message, settings_reader: SettingsReader) -> None:
    """Reply with onboarding steps or the registered-chat keyboard."""
    await render_root_state(message, await settings_reader())


def build_start_router(settings_reader: SettingsReader) -> Router:
    """Legacy /start router; prefer ``build_root_router`` (FSM reset + hints)."""
    router = Router(name="start")

    async def start(message: Message) -> None:
        await handle_start(message, settings_reader)

    router.message.register(start, Command(START_COMMAND))
    return router
