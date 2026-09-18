"""Root Telegram presentation router: /start, /cancel and keyboard dispatch.

/start priority contract: it outranks any active FSM, normalizes state to the
DB-consistent root (TG_UNREGISTERED or main keyboard) and re-renders the keyboard from
the persisted settings snapshot (AC-20.3). /cancel clears the current ephemeral
operation and returns to root or TG_UNREGISTERED.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from vk_topic_bridge.application.dto.settings import BridgeSettingsState
from vk_topic_bridge.presentation.telegram.keyboards import unregistered_keyboard

type SettingsReader = Callable[[], Awaitable[BridgeSettingsState | None]]

START_COMMAND = "start"
CANCEL_COMMAND = "cancel"

ONBOARDING_TEXT = (
    "Чат ещё не зарегистрирован.\n\n"
    "1. Добавьте бота в целевой чат.\n"
    "2. Выдайте боту права на публикацию сообщений (текст, фото, видео, документы).\n"
    "3. Отправьте команду /register внутри этого чата."
)

CANCELLED_TEXT = "Действие отменено."
UNKNOWN_TEXT_HINT = "Неизвестная команда. Воспользуйтесь кнопками меню."


async def render_root_state(message: Message, state: BridgeSettingsState | None) -> None:
    """Reply consistent with the persisted root state (shared by /start and /cancel)."""
    from vk_topic_bridge.presentation.telegram.keyboards import owner_main_keyboard

    if state is None or state.telegram_chat_id is None:
        await message.answer(ONBOARDING_TEXT, reply_markup=unregistered_keyboard())
        return
    title = state.telegram_chat_title or str(state.telegram_chat_id)
    await message.answer(
        f"Чат «{title}» зарегистрирован.",
        reply_markup=owner_main_keyboard(state),
    )


def build_root_router(settings_reader: SettingsReader) -> Router:
    """/start and /cancel handlers; menu-button dispatch lives in settings/destinations.

    This router is included after the feature routers so its catch-all hint only sees
    text that no feature button matched; /start and /cancel match command syntax that
    feature routers never claim, preserving /start priority over active FSMs.
    """
    router = Router(name="root")

    async def start(message: Message, state: FSMContext) -> None:
        await state.clear()
        await render_root_state(message, await settings_reader())

    async def cancel(message: Message, state: FSMContext) -> None:
        await state.clear()
        current = await settings_reader()
        if current is None or current.telegram_chat_id is None:
            await render_root_state(message, current)
            return
        from vk_topic_bridge.presentation.telegram.keyboards import owner_main_keyboard

        await message.answer(CANCELLED_TEXT, reply_markup=owner_main_keyboard(current))

    async def unknown(message: Message, state: FSMContext) -> None:
        if await state.get_state() is not None:
            return
        await message.answer(UNKNOWN_TEXT_HINT)

    router.message.register(start, Command(START_COMMAND))
    router.message.register(cancel, Command(CANCEL_COMMAND))
    router.message.register(unknown, F.text)
    return router
