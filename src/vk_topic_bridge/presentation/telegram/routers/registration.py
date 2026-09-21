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

import logging

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
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
from vk_topic_bridge.presentation.telegram.registration_session import RegistrationCoordinator
from vk_topic_bridge.presentation.telegram.routers.register import (
    MISSING_CAPABILITY_LABELS,
    _is_registerable_chat,
)
from vk_topic_bridge.presentation.telegram.routers.root import (
    ONBOARDING_TEXT,
    SettingsReader,
    render_root_state,
)
from vk_topic_bridge.presentation.telegram.states import RegistrationMaster

START_COMMAND = "start"
logger = logging.getLogger(__name__)

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
    registration: RegistrationCoordinator | None = None,
) -> Router:
    """Wire the registration master; ``menu_sync`` is the optional CommandMenuSynchronizer."""
    router = Router(name="registration")
    directed = DirectedAtThisBotFilter(bot)
    coordinator = registration or RegistrationCoordinator()

    async def private_start(message: Message, state: FSMContext) -> None:
        """Private owner /start: open the master when no chat is registered yet."""
        owner_id = getattr(getattr(message, "from_user", None), "id", None)
        if owner_id is None:
            logger.debug("telegram registration start ignored: missing owner")
            return
        logger.debug("telegram registration start received", extra={"owner_id": owner_id})

        old_group_chat_id = coordinator.release(owner_id)
        if old_group_chat_id is not None:
            logger.debug(
                "telegram registration previous session released",
                extra={"owner_id": owner_id, "chat_id": old_group_chat_id},
            )
            await _clear_group_scope(menu_sync, old_group_chat_id, owner_id)

        current = await settings_reader()
        if current is not None and current.telegram_chat_id is not None:
            await state.clear()
            await render_root_state(message, current)
            logger.debug(
                "telegram registration start rendered registered state",
                extra={"owner_id": owner_id, "chat_id": current.telegram_chat_id},
            )
            return

        if not coordinator.acquire(owner_id):
            logger.debug(
                "telegram registration start ignored: another owner is active",
                extra={"owner_id": owner_id, "active_owner_id": coordinator.active_owner_id},
            )
            return

        await state.clear()
        await state.set_state(RegistrationMaster.pending)
        logger.debug(
            "telegram registration FSM transition",
            extra={
                "owner_id": owner_id,
                "state_before": None,
                "state_after": RegistrationMaster.pending.state,
            },
        )
        await message.answer(
            f"{ONBOARDING_TEXT}\n\n{MASTER_ACTIVE_TEXT}",
            reply_markup=unregistered_keyboard(),
        )
        logger.info(
            "telegram registration started",
            extra={
                "owner_id": owner_id,
                "state_before": None,
                "state_after": RegistrationMaster.pending.state,
            },
        )

    async def group_register(message: Message, state: FSMContext) -> None:
        """Group /register: accepted only for the pending owner in a group context."""
        chat_id = getattr(getattr(message, "chat", None), "id", None)
        logger.debug(
            "telegram registration command received",
            extra={"chat_id": chat_id, "owner_id": getattr(message.from_user, "id", None)},
        )
        if not _is_registerable_chat(getattr(message.chat, "type", "")):
            logger.debug(
                "telegram registration rejected: unsupported chat context",
                extra={"chat_id": chat_id, "reason": "unsupported_chat"},
            )
            return

        owner_id = getattr(getattr(message, "from_user", None), "id", None)
        if owner_id is None:
            logger.debug(
                "telegram registration rejected: missing owner",
                extra={"chat_id": chat_id, "reason": "missing_owner"},
            )
            return
        if not coordinator.owns(owner_id):
            logger.debug(
                "telegram registration rejected: owner does not own active session",
                extra={"owner_id": owner_id, "active_owner_id": coordinator.active_owner_id},
            )
            return
        if await state.get_state() != RegistrationMaster.pending.state:
            logger.debug(
                "telegram registration rejected: master is not pending",
                extra={"owner_id": owner_id},
            )
            return
        chat_id = message.chat.id

        current = await settings_reader()
        retrying_partial_registration = (
            current is not None
            and current.telegram_chat_id is not None
            and coordinator.group_chat_id == chat_id
        )
        if (
            current is not None
            and current.telegram_chat_id is not None
            and not retrying_partial_registration
        ):
            # Repeat /register in an already registered chat: silently normalize state.
            await _clear_group_scope(menu_sync, chat_id, owner_id)
            coordinator.release(owner_id)
            await state.clear()
            logger.debug(
                "telegram registration ignored: chat is already registered",
                extra={"owner_id": owner_id, "chat_id": chat_id},
            )
            return

        # The group becomes known here: expose the /register hint for this owner while
        # the master is active (best-effort; success below clears it).
        coordinator.bind_group(chat_id)
        await _apply_group_scope(menu_sync, chat_id, owner_id)
        logger.debug(
            "telegram registration accepted",
            extra={"owner_id": owner_id, "chat_id": chat_id},
        )

        chat_title = getattr(message.chat, "title", None)
        logger.debug(
            "telegram registration use case started",
            extra={"owner_id": owner_id, "chat_id": chat_id},
        )
        try:
            result = await register_chat.execute(chat_id, chat_title)
        except MissingCapabilitiesError as error:
            missing = "\n".join(f"— {_capability_label(name)}" for name in error.missing)
            await _send_owner_feedback(
                bot,
                owner_id,
                CAPABILITY_ERROR_TEXT.format(missing=missing),
                reason="missing_capabilities",
            )
            logger.info(
                "telegram registration blocked by capabilities",
                extra={"owner_id": owner_id, "chat_id": chat_id, "missing": error.missing},
            )
            return
        except ProvisioningError as error:
            await _send_owner_feedback(
                bot,
                owner_id,
                f"Не удалось подготовить чат: {error}\n"  # noqa: RUF001
                "Чат не зарегистрирован. Исправьте причину и повторите /register.",
                reason="provisioning_error",
            )
            logger.warning(
                "telegram registration recoverable provisioning failure",
                extra={"owner_id": owner_id, "chat_id": chat_id},
            )
            return
        except TelegramAPIError:
            await _send_owner_feedback(
                bot,
                owner_id,
                "Временная ошибка Telegram. Исправьте причину и повторите /register.",
                reason="telegram_api_error",
            )
            logger.warning(
                "telegram registration recoverable Telegram API failure",
                extra={"owner_id": owner_id, "chat_id": chat_id},
                exc_info=True,
            )
            return
        except Exception:
            logger.exception(
                "telegram registration fatal failure",
                extra={"owner_id": owner_id, "chat_id": chat_id},
            )
            raise

        logger.debug(
            "telegram registration use case completed",
            extra={
                "owner_id": owner_id,
                "chat_id": chat_id,
                "topic_count": len(result.topics),
                "outcome": "ready" if result.ready else "pending",
            },
        )

        if not result.ready:
            await _send_owner_feedback(
                bot,
                owner_id,
                "Чат сохранён, но список тем получить не удалось: подготовка не завершена.\n"
                "Повторите /register, чтобы завершить настройку.",
                reason="topics_not_ready",
            )
            logger.info(
                "telegram registration remains pending after partial provisioning",
                extra={
                    "owner_id": owner_id,
                    "chat_id": chat_id,
                    "state_before": RegistrationMaster.pending.state,
                    "state_after": RegistrationMaster.pending.state,
                },
            )
            return

        await _clear_group_scope(menu_sync, chat_id, owner_id)
        coordinator.release(owner_id)
        await state.clear()
        await _send_owner_private(bot, owner_id, result, settings_reader)
        logger.info(
            "telegram registration succeeded",
            extra={
                "owner_id": owner_id,
                "chat_id": chat_id,
                "topic_count": len(result.topics),
                "state_before": RegistrationMaster.pending.state,
                "state_after": None,
            },
        )

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
    try:
        await bot.send_message(
            chat_id=owner_id,
            text="Чат зарегистрирован. Клавиатура управления обновлена.",
            reply_markup=owner_main_keyboard(fresh),
        )
        logger.debug(
            "telegram registration feedback sent",
            extra={"owner_id": owner_id, "channel": "private", "reason": "success"},
        )
    except TelegramAPIError:
        logger.warning(
            "telegram registration success feedback failed",
            extra={"owner_id": owner_id},
            exc_info=True,
        )


async def _send_owner_feedback(bot: Bot, owner_id: int, text: str, *, reason: str) -> None:
    try:
        await bot.send_message(chat_id=owner_id, text=text)
        logger.debug(
            "telegram registration feedback sent",
            extra={"owner_id": owner_id, "channel": "private", "reason": reason},
        )
    except TelegramAPIError:
        logger.warning(
            "telegram registration feedback failed",
            extra={"owner_id": owner_id, "reason": reason},
            exc_info=True,
        )
