"""Root Telegram presentation router: /start, /cancel and keyboard dispatch.

/start priority contract: it outranks any active FSM, normalizes state to the
DB-consistent root (TG_UNREGISTERED or main keyboard) and re-renders the keyboard from
the persisted settings snapshot (AC-20.3). /cancel clears the current ephemeral
operation and returns to root or TG_UNREGISTERED.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from vk_topic_bridge.application.dto.settings import BridgeSettingsState
from vk_topic_bridge.presentation.telegram.filters import PrivateChatFilter
from vk_topic_bridge.presentation.telegram.keyboards import unregistered_keyboard
from vk_topic_bridge.presentation.telegram.registration_session import RegistrationCoordinator

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
REGISTRATION_CANCELLED_TEXT = "Регистрация Telegram-чата отменена."
logger = logging.getLogger(__name__)
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


def build_root_router(
    settings_reader: SettingsReader,
    *,
    registration: RegistrationCoordinator | None = None,
    menu_sync: object | None = None,
) -> Router:
    """/start and /cancel handlers; menu-button dispatch lives in settings/destinations.

    This router is included after the feature routers so its catch-all hint only sees
    text that no feature button matched; /start and /cancel match command syntax that
    feature routers never claim, preserving /start priority over active FSMs.
    """
    router = Router(name="root")
    coordinator = registration or RegistrationCoordinator()

    async def start(message: Message, state: FSMContext) -> None:
        logger.debug(
            "telegram root start received",
            extra={"owner_id": getattr(getattr(message, "from_user", None), "id", None)},
        )
        await state.clear()
        await render_root_state(message, await settings_reader())

    async def cancel(message: Message, state: FSMContext) -> None:
        owner_id = getattr(getattr(message, "from_user", None), "id", None)
        logger.debug("telegram cancel received", extra={"owner_id": owner_id})
        registration_cancelled = owner_id is not None and coordinator.owns(owner_id)
        group_chat_id: int | None = None
        if owner_id is not None:
            group_chat_id = coordinator.release(owner_id)
        if registration_cancelled and owner_id is not None:
            if group_chat_id is not None:
                await _clear_registration_scope(menu_sync, group_chat_id, owner_id)
            logger.info(
                "telegram registration cancelled",
                extra={
                    "owner_id": owner_id,
                    "chat_id": group_chat_id,
                    "state_before": "RegistrationMaster:pending",
                    "state_after": None,
                },
            )
        await state.clear()
        current = await settings_reader()
        if current is None or current.telegram_chat_id is None:
            if registration_cancelled:
                await message.answer(
                    REGISTRATION_CANCELLED_TEXT, reply_markup=unregistered_keyboard()
                )
                return
            await render_root_state(message, current)
            return
        from vk_topic_bridge.presentation.telegram.keyboards import owner_main_keyboard

        text = REGISTRATION_CANCELLED_TEXT if registration_cancelled else CANCELLED_TEXT
        await message.answer(text, reply_markup=owner_main_keyboard(current))

    async def unknown(message: Message, state: FSMContext) -> None:
        if await state.get_state() is not None:
            logger.debug(
                "telegram unknown text ignored: FSM is active",
                extra={"owner_id": getattr(getattr(message, "from_user", None), "id", None)},
            )
            return
        logger.debug(
            "telegram unknown private text handled",
            extra={"owner_id": getattr(getattr(message, "from_user", None), "id", None)},
        )
        await message.answer(UNKNOWN_TEXT_HINT)

    router.message.register(start, Command(START_COMMAND))
    router.message.register(cancel, Command(CANCEL_COMMAND))
    router.message.register(unknown, F.text, PrivateChatFilter())
    return router


async def _clear_registration_scope(menu_sync: object | None, chat_id: int, owner_id: int) -> None:
    if menu_sync is None:
        return
    method = getattr(menu_sync, "clear_registration_group", None)
    if method is not None:
        await method(chat_id, owner_id)
