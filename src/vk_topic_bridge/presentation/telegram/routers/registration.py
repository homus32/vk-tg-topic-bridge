"""Registration master: private /start gating + group /register consumption.

Contract (frozen draft): private owner /start opens ``RegistrationMaster.pending``
under ``FSMStrategy.GLOBAL_USER``; group ``/register`` (bare or @-directed) is accepted
only from the same owner with an active master, in group/supergroup context; only then
the existing ``RegisterChat`` use case runs. Successful registration cannot repeat.
Unauthorized/other contexts are silently ignored (middleware drops outsiders first).

Command-menu hints are best-effort UX: the group ``ChatMember`` scope is applied when
the group becomes known during an active master and cleared after success.
"""

from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from vk_topic_bridge.application.admin.register_chat import (
    MissingCapabilitiesError,
    RegisterChat,
    RegisterChatResult,
)
from vk_topic_bridge.application.errors import ProvisioningError
from vk_topic_bridge.presentation.telegram.commands import REGISTER_COMMAND
from vk_topic_bridge.presentation.telegram.filters import (
    DirectedAtThisBotFilter,
    GroupChatFilter,
    PrivateChatFilter,
)
from vk_topic_bridge.presentation.telegram.keyboards import (
    owner_main_keyboard,
    unregistered_keyboard,
)
from vk_topic_bridge.presentation.telegram.routers.register import (
    MISSING_CAPABILITY_LABELS,
    _is_registerable_chat,
)
from vk_topic_bridge.presentation.telegram.routers.root import ONBOARDING_TEXT, SettingsReader
from vk_topic_bridge.presentation.telegram.states import RegistrationMaster

START_COMMAND = "start"

MASTER_ACTIVE_TEXT = (
    "Режим регистрации активен.\n"
    "Отправьте /register в целевом чате, чтобы зарегистрировать его."  # noqa: RUF001
)
CAPABILITY_ERROR_TEXT = (
    "Бот не может публиковать в этом чате: не хватает прав.\n"
    "{missing}\n"
    "Настройка не завершена: выдайте все права и повторите /register."
)


def _capability_label(name: str) -> str:
    return MISSING_CAPABILITY_LABELS.get(name, name)


def build_registration_router(
    register_chat: RegisterChat,
    settings_reader: SettingsReader,
    bot: Bot,
    *,
    menu_sync: object | None = None,
) -> Router:
    """Wire the registration master; ``menu_sync`` is the optional CommandMenuSynchronizer."""
    router = Router(name="registration")
    directed = DirectedAtThisBotFilter(bot)

    async def private_start(message: Message, state: FSMContext) -> None:
        """Private owner /start: open the master when no chat is registered yet."""
        await state.clear()
        current = await settings_reader()
        if current is not None and current.telegram_chat_id is not None:
            title = current.telegram_chat_title or str(current.telegram_chat_id)
            await message.answer(
                f"Чат «{title}» зарегистрирован.",
                reply_markup=owner_main_keyboard(current),
            )
            return
        await state.set_state(RegistrationMaster.pending)
        await message.answer(
            f"{ONBOARDING_TEXT}\n\n{MASTER_ACTIVE_TEXT}",
            reply_markup=unregistered_keyboard(),
        )

    async def group_register(message: Message, state: FSMContext) -> None:
        """Group /register: accepted only for the pending owner in a group context."""
        if not _is_registerable_chat(getattr(message.chat, "type", "")):
            return
        if await state.get_state() != RegistrationMaster.pending.state:
            return

        owner_id = getattr(getattr(message, "from_user", None), "id", None)
        if owner_id is None:
            return
        chat_id = message.chat.id

        current = await settings_reader()
        if current is not None and current.telegram_chat_id is not None:
            # Repeat /register in an already registered chat: silently normalize state.
            await _clear_group_scope(menu_sync, chat_id, owner_id)
            await state.clear()
            return

        # The group becomes known here: expose the /register hint for this owner while
        # the master is active (best-effort; success below clears it).
        await _apply_group_scope(menu_sync, chat_id, owner_id)

        chat_title = getattr(message.chat, "title", None)
        try:
            result = await register_chat.execute(chat_id, chat_title)
        except MissingCapabilitiesError as error:
            missing = "\n".join(f"— {_capability_label(name)}" for name in error.missing)
            await message.answer(CAPABILITY_ERROR_TEXT.format(missing=missing))
            return
        except ProvisioningError as error:
            await message.answer(
                f"Не удалось подготовить чат: {error}\n"  # noqa: RUF001
                "Чат не зарегистрирован. Исправьте причину и повторите /register."
            )
            return

        await _clear_group_scope(menu_sync, chat_id, owner_id)
        await state.clear()
        await _send_owner_private(bot, owner_id, result, settings_reader)

    router.message.register(private_start, Command(START_COMMAND), PrivateChatFilter(), directed)
    router.message.register(group_register, Command(REGISTER_COMMAND), GroupChatFilter(), directed)
    return router


async def _apply_group_scope(menu_sync: object | None, chat_id: int, owner_id: int) -> None:
    if menu_sync is None:
        return
    method = getattr(menu_sync, "apply_registration_group", None)
    if method is not None:
        await method(chat_id, owner_id)


async def _clear_group_scope(menu_sync: object | None, chat_id: int, owner_id: int) -> None:
    if menu_sync is None:
        return
    method = getattr(menu_sync, "clear_registration_group", None)
    if method is not None:
        await method(chat_id, owner_id)


async def _send_owner_private(
    bot: Bot,
    owner_id: int,
    result: RegisterChatResult,
    settings_reader: SettingsReader,
) -> None:
    """DM the owner the fresh main keyboard after a successful registration."""
    if not result.ready:
        return
    fresh = await settings_reader()
    if fresh is None or fresh.telegram_chat_id is None:
        return
    await bot.send_message(
        chat_id=owner_id,
        text="Чат зарегистрирован. Клавиатура управления обновлена.",
        reply_markup=owner_main_keyboard(fresh),
    )
