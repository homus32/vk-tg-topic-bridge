"""Destination wizards (messages/wall) with General as an explicit selectable destination.

Named topics are proof-gated (real Bot API send into the thread, then persist); General
uses the same proof-send with no thread id, then persists as the explicit configured state
(configured=True, topic_id=NULL). Unavailable topics (closed/hidden) are shown but never
selectable.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Literal, Protocol, cast
from uuid import uuid4

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from vk_topic_bridge.application.admin.destination_admin import (
    DestinationConfirmationResult,
    SelectDestinationV2,
)
from vk_topic_bridge.application.dto.settings import BridgeSettingsState
from vk_topic_bridge.application.errors import (
    ProvisioningError,
    PublicationAmbiguousError,
    PublicationRejectedError,
    is_stale_topic_rejection,
)
from vk_topic_bridge.domain.value_objects import TopicInfo
from vk_topic_bridge.presentation.telegram import filters as btn
from vk_topic_bridge.presentation.telegram.keyboards import (
    DestinationCallback,
    back_keyboard,
    destination_keyboard,
    ordinal_choice_keyboard,
    owner_main_keyboard,
    unregistered_keyboard,
)
from vk_topic_bridge.presentation.telegram.states import (
    MessagesDestinationWizard,
    WallDestinationWizard,
)

type SettingsReader = Callable[[], Awaitable[BridgeSettingsState | None]]
type TopicsReader = Callable[[int], Awaitable[list[TopicInfo]]]
type RunIdFactory = Callable[[], str]

logger = logging.getLogger(__name__)


class RefreshUseCase(Protocol):
    async def refresh(self, chat_id: int) -> list[TopicInfo]: ...


def default_run_id() -> str:
    """Unique per-invocation id correlating the proof send with owner evidence."""
    return f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid4().hex[:8]}"


UNREGISTERED_TEXT = "Telegram-чат ещё не зарегистрирован."
EMPTY_TOPICS_TEXT = "Темы не найдены. Обновите список тем в настройках."
EXPECTED_ORDINAL_TEXT = "Отправьте номер темы из списка."
UNAVAILABLE_TOPIC_TEXT = "Эта тема недоступна и не может быть темой назначения."


def _topic_available(topic: TopicInfo) -> bool:
    return not topic.is_closed and not topic.is_hidden


def _destination_rows(topics: list[TopicInfo]) -> list[tuple[TopicInfo, str]]:
    """General first, then persisted topics by ordinal; unavailable marked but listed."""
    ordered = sorted(topics, key=lambda topic: (not topic.is_general, topic.topic_id or 0))
    rows: list[tuple[TopicInfo, str]] = []
    for index, topic in enumerate(ordered, start=1):
        suffix = "" if _topic_available(topic) else " (недоступна)"
        rows.append((topic, f"{index}. {topic.title}{suffix}"))
    return rows


def _render_destination_list(rows: list[tuple[TopicInfo, str]], current_topic_id: int = -2) -> str:
    labels = [
        f"{label} (текущий)" if topic.topic_id == current_topic_id else label
        for topic, label in rows
    ]
    body = "\n".join(labels)
    return f"Выберите топик:\n\n{body}"


def _topic_version(topics: list[TopicInfo]) -> int:
    return hash(
        tuple((topic.topic_id, topic.title, topic.is_closed, topic.is_hidden) for topic in topics)
    )


def _current_topic_id(state: BridgeSettingsState, kind: str) -> int:
    configured = (
        state.telegram_messages_topic_configured
        if kind == "messages"
        else state.telegram_wall_topic_configured
    )
    topic_id = (
        state.telegram_messages_topic_id if kind == "messages" else state.telegram_wall_topic_id
    )
    if not configured:
        return -2
    return -1 if topic_id is None else topic_id


def _parse_ordinal(text: str | None, count: int) -> int | None:
    if text is None:
        return None
    stripped = text.strip()
    if not stripped.isdigit():
        return None
    value = int(stripped)
    return value if 1 <= value <= count else None


def _confirmation_text(kind: str, topic: TopicInfo, result: DestinationConfirmationResult) -> str:
    role = "сообщений VK" if kind == "messages" else "постов стены VK"
    if result.general_selected:
        return f"Топик назначения для автоматической пересылки {role} изменён на:\nGeneral"
    return f"Топик назначения для автоматической пересылки {role} изменён на:\n{topic.title}"


def _wizard_state(kind: str) -> State:
    return (
        MessagesDestinationWizard.wait_ordinal
        if kind == "messages"
        else WallDestinationWizard.wait_ordinal
    )


def _in_wizard(fsm_state: str | None, kind: str) -> bool:
    return fsm_state == _wizard_state(kind).state


def build_destinations_router(
    select_destination: SelectDestinationV2,
    settings_reader: SettingsReader,
    topics_reader: TopicsReader,
    *,
    run_id_factory: Callable[[], str],
    refresh_use_case: RefreshUseCase,
    owner_ids: frozenset[int] | None = None,
) -> Router:
    """Wire both destination wizards; General is selectable, unavailable topics are not."""
    router = Router(name="destinations")

    async def _open(message: Message, state: FSMContext, kind: Literal["messages", "wall"]) -> None:
        current = await settings_reader()
        if current is None or current.telegram_chat_id is None:
            await message.answer(UNREGISTERED_TEXT, reply_markup=unregistered_keyboard())
            return
        chat_id = current.telegram_chat_id
        topics = await topics_reader(chat_id)
        if not topics:
            await message.answer(EMPTY_TOPICS_TEXT, reply_markup=back_keyboard())
            return
        version = _topic_version(topics)
        rows = _destination_rows(topics)
        await state.set_state(_wizard_state(kind))
        await state.update_data(destination_version=version)
        await message.answer(
            _render_destination_list(rows, _current_topic_id(current, kind)),
            reply_markup=destination_keyboard(
                [(topic.topic_id, topic.title, _topic_available(topic)) for topic, _ in rows],
                cast("Literal['messages', 'wall']", kind),
                version,
                _current_topic_id(current, kind),
            ),
        )

    async def messages_destination(message: Message, state: FSMContext) -> None:
        await _open(message, state, "messages")

    async def wall_destination(message: Message, state: FSMContext) -> None:
        await _open(message, state, "wall")

    async def _pick(message: Message, state: FSMContext, kind: str) -> None:
        current = await settings_reader()
        if current is None or current.telegram_chat_id is None:
            await message.answer(UNREGISTERED_TEXT, reply_markup=unregistered_keyboard())
            return
        chat_id = current.telegram_chat_id
        topics = await topics_reader(chat_id)
        rows = _destination_rows(topics)
        ordinal = _parse_ordinal(message.text, len(rows))
        if ordinal is None:
            await message.answer(
                f"Неверный номер. {EXPECTED_ORDINAL_TEXT}\n\n{_render_destination_list(rows)}",
                reply_markup=ordinal_choice_keyboard(),
            )
            return
        topic, _ = rows[ordinal - 1]
        if not _topic_available(topic):
            await message.answer(
                f"{UNAVAILABLE_TOPIC_TEXT}\n\n{_render_destination_list(rows)}",
                reply_markup=ordinal_choice_keyboard(),
            )
            return
        await _apply_topic(message, state, kind, topic, chat_id)

    async def _apply_topic(
        message: Message,
        state: FSMContext,
        kind: str,
        topic: TopicInfo,
        chat_id: int,
        edit_message: bool = False,
    ) -> None:
        try:
            result = await select_destination.execute(chat_id, topic, kind, run_id_factory())
        except PublicationRejectedError as error:
            if is_stale_topic_rejection(error):
                await _recover_stale_topic(message, chat_id, topic, refresh_use_case)
                return
            logger.warning(
                "telegram destination proof rejected",
                extra={
                    "chat_id": chat_id,
                    "destination_topic_id": topic.topic_id,
                    "reason": error.code,
                },
            )
            await message.answer(
                f"Не удалось подтвердить топик «{topic.title}». "  # noqa: RUF001
                "Ничего не сохранено. Повторите попытку."
            )
            return
        except PublicationAmbiguousError as error:
            logger.warning(
                "telegram destination proof became ambiguous",
                extra={
                    "chat_id": chat_id,
                    "destination_topic_id": topic.topic_id,
                    "reason": error.code,
                },
            )
            await message.answer(
                f"Не удалось подтвердить топик «{topic.title}»: "  # noqa: RUF001
                "Telegram не подтвердил результат. Ничего не сохранено. Повторите попытку."
            )
            return
        except ProvisioningError as error:
            await message.answer(
                f"Не удалось подтвердить топик «{topic.title}»: {error}\n"  # noqa: RUF001
                "Ничего не сохранено. Повторите попытку."
            )
            return
        except Exception:
            logger.exception(
                "telegram destination proof failed unexpectedly",
                extra={
                    "chat_id": chat_id,
                    "destination_topic_id": topic.topic_id,
                },
            )
            await message.answer(
                f"Не удалось подтвердить топик «{topic.title}». "  # noqa: RUF001
                "Ничего не сохранено. Повторите попытку."
            )
            return
        else:
            await state.clear()
            confirmation = _confirmation_text(kind, topic, result)
            if edit_message:
                await message.edit_text(
                    confirmation,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[]),
                )
                return
            fresh = await settings_reader()
            markup = owner_main_keyboard(fresh) if fresh is not None else ordinal_choice_keyboard()
            await message.answer(confirmation, reply_markup=markup)

    async def _callback_pick(
        callback: CallbackQuery,
        state: FSMContext,
        callback_data: DestinationCallback,
        kind: str,
    ) -> None:
        owner_id = getattr(getattr(callback, "from_user", None), "id", None)
        if owner_ids is not None and owner_id not in owner_ids:
            return
        message = callback.message
        if message is None:
            await callback.answer("Кнопка устарела.")
            return
        if not callable(getattr(message, "edit_text", None)):
            await callback.answer("Кнопка устарела.")
            return
        message = cast(Message, message)
        if await state.get_state() != _wizard_state(kind).state:
            await callback.answer("Кнопка устарела.")
            return
        data = await state.get_data()
        if data.get("destination_version") != callback_data.version:
            await callback.answer("Список топиков устарел.")
            return
        if callback_data.action in {"cancel", "back"}:
            await callback.answer("Действие отменено.")
            await _cancel(message, state, kind)
            return
        current = await settings_reader()
        if current is None or current.telegram_chat_id is None:
            await callback.answer("Чат не зарегистрирован.")
            return
        topics = await topics_reader(current.telegram_chat_id)
        topic_id = None if callback_data.topic_id == -1 else callback_data.topic_id
        topic = next((candidate for candidate in topics if candidate.topic_id == topic_id), None)
        if topic is None or not _topic_available(topic):
            await callback.answer("Топик больше недоступен.")
            return
        await callback.answer("Топик выбран.")
        await _apply_topic(message, state, kind, topic, current.telegram_chat_id, edit_message=True)

    async def _recover_stale_topic(
        message: Message,
        chat_id: int,
        topic: TopicInfo,
        refresh_use_case: RefreshUseCase,
    ) -> None:
        try:
            topics = await refresh_use_case.refresh(chat_id)
        except Exception:
            logger.exception(
                "telegram stale destination refresh failed",
                extra={"chat_id": chat_id, "destination_topic_id": topic.topic_id},
            )
            cached_topics = await topics_reader(chat_id)
            await message.answer(
                f"Топик «{topic.title}» больше недоступен, но список не удалось "
                "обновить. Повторите попытку и выберите destination снова.\n\n"
                f"{_render_destination_list(_destination_rows(cached_topics))}",
                reply_markup=ordinal_choice_keyboard(),
            )
            return
        logger.info(
            "telegram stale destination recovered",
            extra={
                "chat_id": chat_id,
                "destination_topic_id": topic.topic_id,
                "topic_count": len(topics),
            },
        )
        await message.answer(
            f"Топик «{topic.title}» больше недоступен. Список destinations обновлён.\n\n"
            f"{_render_destination_list(_destination_rows(topics))}",
            reply_markup=ordinal_choice_keyboard(),
        )

    async def messages_pick(message: Message, state: FSMContext) -> None:
        if not _in_wizard(await state.get_state(), "messages"):
            raise SkipHandler
        await _pick(message, state, "messages")

    async def wall_pick(message: Message, state: FSMContext) -> None:
        if not _in_wizard(await state.get_state(), "wall"):
            raise SkipHandler
        await _pick(message, state, "wall")

    async def _cancel(message: Message, state: FSMContext, kind: str) -> None:
        if not _in_wizard(await state.get_state(), kind):
            raise SkipHandler
        await state.clear()
        current = await settings_reader()
        if current is None or current.telegram_chat_id is None:
            await message.answer(UNREGISTERED_TEXT, reply_markup=unregistered_keyboard())
            return
        await message.answer("Действие отменено.", reply_markup=owner_main_keyboard(current))

    async def wizard_cancel(message: Message, state: FSMContext) -> None:
        fsm_state = await state.get_state()
        if _in_wizard(fsm_state, "messages"):
            await _cancel(message, state, "messages")
        elif _in_wizard(fsm_state, "wall"):
            await _cancel(message, state, "wall")
        else:
            raise SkipHandler

    async def wizard_back(message: Message, state: FSMContext) -> None:
        await wizard_cancel(message, state)

    router.message.register(messages_destination, F.text == btn.MENU_MESSAGES_DESTINATION)
    router.message.register(wall_destination, F.text == btn.MENU_WALL_DESTINATION)
    router.message.register(messages_pick, F.text.regexp(r"^\d+$"))
    router.message.register(wall_pick, F.text.regexp(r"^\d+$"))
    router.message.register(wizard_cancel, F.text == btn.BTN_CANCEL)
    router.message.register(wizard_back, F.text == btn.BTN_BACK)

    async def messages_callback(
        callback: CallbackQuery, state: FSMContext, callback_data: DestinationCallback
    ) -> None:
        await _callback_pick(callback, state, callback_data, "messages")

    async def wall_callback(
        callback: CallbackQuery, state: FSMContext, callback_data: DestinationCallback
    ) -> None:
        await _callback_pick(callback, state, callback_data, "wall")

    router.callback_query.register(
        messages_callback,
        DestinationCallback.filter(F.kind == "messages"),
    )
    router.callback_query.register(
        wall_callback,
        DestinationCallback.filter(F.kind == "wall"),
    )
    return router
