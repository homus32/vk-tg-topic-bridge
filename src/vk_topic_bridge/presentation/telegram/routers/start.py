"""``/start`` onboarding: instruct until a chat is registered, confirm afterwards.

The handler only reads the persisted settings snapshot through an injected reader and
replies; provisioning stays in the ``/register`` use case (US-02 AC-02.1).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from vk_topic_bridge.application.dto.settings import BridgeSettingsState
from vk_topic_bridge.presentation.telegram.keyboards import owner_main_keyboard

START_COMMAND = "start"

# TODO(stage-7): /start only prints onboarding steps until the Admin UI wizard exists;
# Stage 7 replaces this text-only reply with the permanent owner keyboard (US-02 AC-02.3).

type SettingsReader = Callable[[], Awaitable[BridgeSettingsState | None]]

ONBOARDING_TEXT = (
    "Чат ещё не зарегистрирован.\n\n"
    "1. Добавьте бота в целевой чат.\n"
    "2. Выдайте боту права на публикацию сообщений (текст, фото, видео, документы).\n"
    "3. Отправьте команду /register внутри этого чата."
)


async def handle_start(message: Message, settings_reader: SettingsReader) -> None:
    """Reply with onboarding steps or confirm the registered chat."""
    state = await settings_reader()
    if state is None or state.telegram_chat_id is None:
        await message.answer(ONBOARDING_TEXT)
        return

    title = state.telegram_chat_title or str(state.telegram_chat_id)
    await message.answer(
        f"Чат «{title}» зарегистрирован.",
        reply_markup=owner_main_keyboard(),
    )


def build_start_router(settings_reader: SettingsReader) -> Router:
    """Build the router for ``/start``; the reader is bound as a handler dependency."""
    router = Router(name="start")

    async def start(message: Message) -> None:
        await handle_start(message, settings_reader)

    router.message.register(start, Command(START_COMMAND))
    return router
