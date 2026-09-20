"""VK DM presentation handlers: Help, alias CRUD FSM, manual forwarding.

All handlers are thin: they normalize the raw DM event, drive the per-user session and
delegate persistence/publication decisions to application use cases. Community
conversation events NEVER reach this module (routing happens before the guard).
The reply transport is ``VkManualUiPort.send_user_message`` with keyboard JSON factories.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass

from vk_topic_bridge.application.errors import DomainError
from vk_topic_bridge.application.manual.aliasing import (
    AliasEntry,
    AliasManager,
    AliasResolution,
    ManualDestinationList,
    ManualForwarding,
)
from vk_topic_bridge.application.manual.publish_manual import (
    ManualPublicationRequest,
    PublishManualMessage,
)
from vk_topic_bridge.application.ports.vk_ex import VkManualUiPort
from vk_topic_bridge.domain.errors import InvalidAlias
from vk_topic_bridge.domain.value_objects import Author, Destination, SourceMessage
from vk_topic_bridge.presentation.vk.keyboards import (
    BTN_ADD,
    BTN_ALIASES,
    BTN_BACK,
    BTN_CANCEL,
    BTN_DELETE,
    BTN_EDIT,
    BTN_HELP,
    BTN_YES,
    alias_menu_keyboard_json,
    cancel_keyboard_json,
    confirm_keyboard_json,
    is_help_trigger,
    main_keyboard_json,
    wait_destination_keyboard_json,
)
from vk_topic_bridge.presentation.vk.states import VkSessionStore, VkUiState, VkUserSession

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "Как пользоваться ботом:\n\n"
    "1. Чтобы переслать одно сообщение, перешлите его боту и выберите номер топика.\n"  # noqa: RUF001
    "2. Отправьте номер топика из списка, чтобы выбрать направление.\n"
    "3. Можно ввести алиас топика вместо номера.\n"
    "4. Алиасы настраиваются кнопкой «Алиасы»: добавить, изменить, удалить.\n"
    "5. Отменить текущую операцию можно кнопкой «Отмена».\n"
    "6. Автоматически пересылаются сообщения с @all и/или хештегом, "  # noqa: RUF001
    "если эти функции включены."
)

UNKNOWN_ALIAS_TEXT = "Алиас неизвестен."
MULTI_MESSAGE_TEXT = (
    "Можно переслать только одно сообщение за одну операцию.\nОтправьте одно сообщение отдельно."  # noqa: RUF001
)
STALE_ALIAS_TEXT = "Топик выбранного алиаса больше недоступен."
CONFIG_ERROR_TEXT = (
    "Ручная пересылка пока недоступна: Telegram-чат не зарегистрирован "
    "или в нём нет доступных топиков."
)
NO_TOPICS_TEXT = "Нет доступных топиков для выбора."
ORDINAL_ONLY_TEXT = "Можно отправить только номер топика из списка."
TOPIC_NOT_FOUND_TEXT = "Номер не найден."
ALIAS_ADD_TOPIC_TEXT = "Введите номер топика, для которого хотите добавить алиас."
ALIAS_ADD_VALUE_TEXT = "Введите новый алиас."
ALIAS_EDIT_TOPIC_TEXT = "Введите номер топика, у которого хотите изменить алиас."  # noqa: RUF001
ALIAS_EDIT_VALUE_TEXT = "Введите новый алиас."
ALIAS_DELETE_TOPIC_TEXT = "Введите номер топика, у которого хотите удалить алиас."  # noqa: RUF001
NO_ALIAS_TEXT = "У этого топика нет алиаса."  # noqa: RUF001
PUBLISH_FAILED_TEXT = "Не удалось отправить сообщение. Попробуйте позже."  # noqa: RUF001
SENT_TEXT = "Сообщение отправлено."
CANCELLED_TEXT = "Отправка отменена."
STALE_TOPIC_TEXT = "Выбранный топик больше недоступен. Выберите другой топик."

SourceResolver = Callable[["VkUiMessage"], Awaitable[SourceMessage | None]]


@dataclass(frozen=True, slots=True)
class VkUiMessage:
    """Normalized VK user DM for the UI layer (extracted from the raw payload)."""

    from_id: int
    peer_id: int
    text: str
    fwd_count: int
    conversation_message_id: int | None
    author: Author | None = None
    raw: Mapping[str, object] | None = None


class VkUiDispatcher:
    """Routes one ``VkUiMessage`` according to the user's session state."""

    def __init__(
        self,
        sessions: VkSessionStore,
        send: VkManualUiPort,
        manual_forwarding: ManualForwarding,
        alias_manager: AliasManager,
        manual_publisher: PublishManualMessage,
        *,
        source_resolver: SourceResolver,
    ) -> None:
        self._sessions = sessions
        self._send = send
        self._manual_forwarding = manual_forwarding
        self._alias_manager = alias_manager
        self._manual_publisher = manual_publisher
        self._source_resolver = source_resolver

    async def handle_dm(self, update: Mapping[str, object]) -> bool:
        """``VkUiRouter`` entry point; returns True when the DM was consumed by the UI."""
        message = self.normalize(update)
        if message is None:
            logger.debug("vk UI message ignored: normalization failed")
            return False
        logger.debug(
            "vk UI message accepted",
            extra={
                "from_id": message.from_id,
                "peer_id": message.peer_id,
                "text_length": len(message.text),
                "message_count": message.fwd_count,
            },
        )
        await self.dispatch(message)
        logger.debug("vk UI message completed", extra={"from_id": message.from_id})
        return True

    def normalize(self, update: Mapping[str, object]) -> VkUiMessage | None:
        """Map one raw Long Poll ``message_new`` update into a UI message or None."""
        obj = update.get("object")
        if not isinstance(obj, Mapping):
            return None
        payload = obj.get("message")
        message = payload if isinstance(payload, Mapping) else obj
        from_id = message.get("from_id")
        peer_id = message.get("peer_id")
        if not isinstance(from_id, int) or isinstance(from_id, bool):
            return None
        if not isinstance(peer_id, int) or isinstance(peer_id, bool):
            return None
        raw_text = message.get("text")
        text = raw_text if isinstance(raw_text, str) else ""
        fwd_raw = message.get("fwd_messages")
        fwd_count = len(fwd_raw) if isinstance(fwd_raw, list) else 0
        cmid = message.get("conversation_message_id")
        return VkUiMessage(
            from_id=from_id,
            peer_id=peer_id,
            text=text,
            fwd_count=fwd_count,
            conversation_message_id=cmid if isinstance(cmid, int) else None,
            raw=message,
        )

    async def dispatch(self, message: VkUiMessage) -> None:
        session = self._sessions.get(message.from_id)
        state = session.state
        logger.debug(
            "vk UI FSM dispatch started",
            extra={"from_id": message.from_id, "state_before": state.value},
        )
        if state is VkUiState.WAIT_DESTINATION:
            await self._handle_wait_destination(message, session)
        elif state is VkUiState.ALIAS_MENU:
            await self._handle_alias_menu(message, session)
        elif state in (
            VkUiState.ALIAS_ADD_WAIT_TOPIC,
            VkUiState.ALIAS_EDIT_WAIT_TOPIC,
            VkUiState.ALIAS_DELETE_WAIT_TOPIC,
        ):
            await self._handle_alias_topic_input(message, session)
        elif state in (VkUiState.ALIAS_ADD_WAIT_VALUE, VkUiState.ALIAS_EDIT_WAIT_VALUE):
            await self._handle_alias_value_input(message, session)
        elif state is VkUiState.ALIAS_DELETE_CONFIRM:
            await self._handle_alias_delete_confirm(message, session)
        else:
            await self._handle_idle(message, session)
        logger.debug(
            "vk UI FSM dispatch completed",
            extra={
                "from_id": message.from_id,
                "state_before": state.value,
                "state_after": session.state.value,
            },
        )

    # --- IDLE ---------------------------------------------------------------

    async def _handle_idle(self, message: VkUiMessage, session: VkUserSession) -> None:
        text = message.text.strip()
        if message.fwd_count >= 2:
            logger.debug(
                "vk UI idle branch selected",
                extra={"from_id": message.from_id, "outcome": "multiple_forwards"},
            )
            await self._reply(message, MULTI_MESSAGE_TEXT)
            return
        if message.fwd_count == 1:
            logger.debug(
                "vk UI idle branch selected",
                extra={"from_id": message.from_id, "outcome": "forwarded_message"},
            )
            await self._handle_forwarded(message, session, text)
            return
        if is_help_trigger(text) or text == BTN_HELP:
            logger.debug(
                "vk UI idle branch selected",
                extra={"from_id": message.from_id, "outcome": "help"},
            )
            await self._reply(message, HELP_TEXT, main_keyboard_json())
            return
        if text == BTN_ALIASES:
            logger.debug(
                "vk UI idle branch selected",
                extra={"from_id": message.from_id, "outcome": "aliases"},
            )
            await self._open_alias_menu(message, session)
            return
        logger.debug(
            "vk UI idle branch selected",
            extra={"from_id": message.from_id, "outcome": "help_default"},
        )
        await self._reply(message, HELP_TEXT, main_keyboard_json())

    async def _handle_forwarded(
        self, message: VkUiMessage, session: VkUserSession, text: str
    ) -> None:
        listing = await self._manual_forwarding.destination_list(message.from_id)
        logger.debug(
            "vk manual destinations loaded",
            extra={
                "from_id": message.from_id,
                "outcome": "available" if listing.chat_registered else "unregistered",
                "message_count": len(listing.destinations),
            },
        )
        if not listing.chat_registered or not listing.destinations:
            await self._reply(message, CONFIG_ERROR_TEXT)
            return
        if text:
            resolution = await self._manual_forwarding.resolve_alias(message.from_id, text)
            if resolution.status is AliasResolution.Status.FOUND:
                await self._publish_manual(message, session, resolution, source=message)
                return
            if resolution.status is AliasResolution.Status.STALE:
                notice = (
                    f"{STALE_ALIAS_TEXT}\n\n{_destinations_text(listing)}\n"
                    "Выберите другой топик по номеру или настройте алиасы заново."
                )
            else:
                notice = (
                    f"{UNKNOWN_ALIAS_TEXT}\n\n{_destinations_text(listing)}\n\n{ORDINAL_ONLY_TEXT}"
                )
        else:
            notice = (
                f"Куда отправить сообщение?\n\n{_destinations_text(listing)}\n\n{ORDINAL_ONLY_TEXT}"
            )
        await self._reply(message, notice, wait_destination_keyboard_json())
        session.state = VkUiState.WAIT_DESTINATION
        session.pending_message = message
        self._sessions.set(message.from_id, session)
        logger.debug(
            "vk UI FSM transition",
            extra={
                "from_id": message.from_id,
                "state_before": VkUiState.IDLE.value,
                "state_after": VkUiState.WAIT_DESTINATION.value,
            },
        )

    # --- WAIT_DESTINATION ---------------------------------------------------

    async def _handle_wait_destination(self, message: VkUiMessage, session: VkUserSession) -> None:
        text = message.text.strip()
        if text == BTN_CANCEL:
            logger.info("vk manual forwarding cancelled", extra={"from_id": message.from_id})
            self._sessions.clear(message.from_id)
            await self._reply(message, CANCELLED_TEXT, main_keyboard_json())
            return
        listing = await self._manual_forwarding.destination_list(message.from_id)
        if not listing.chat_registered or not listing.destinations:
            self._sessions.clear(message.from_id)
            await self._reply(message, CONFIG_ERROR_TEXT)
            return
        ordinal = _parse_ordinal(text)
        if ordinal is None or not 1 <= ordinal <= len(listing.destinations):
            logger.debug(
                "vk manual destination rejected",
                extra={"from_id": message.from_id, "reason": "invalid_ordinal"},
            )
            await self._reply(
                message,
                f"{TOPIC_NOT_FOUND_TEXT}\n\n{_destinations_text(listing)}\n\n{ORDINAL_ONLY_TEXT}",
                wait_destination_keyboard_json(),
            )
            return
        offer = listing.destinations[ordinal - 1]
        if not offer.available:
            logger.debug(
                "vk manual destination rejected",
                extra={"from_id": message.from_id, "reason": "stale_topic"},
            )
            await self._reply(
                message,
                f"{STALE_TOPIC_TEXT}\n\n{_destinations_text(listing)}",
                wait_destination_keyboard_json(),
            )
            return
        pending = session.pending_message
        session.pending_message = None
        session.state = VkUiState.IDLE
        self._sessions.set(message.from_id, session)
        logger.debug(
            "vk UI FSM transition",
            extra={
                "from_id": message.from_id,
                "state_before": VkUiState.WAIT_DESTINATION.value,
                "state_after": VkUiState.IDLE.value,
            },
        )
        if not isinstance(pending, VkUiMessage):
            await self._reply(message, PUBLISH_FAILED_TEXT, main_keyboard_json())
            return
        resolution = AliasResolution(
            status=AliasResolution.Status.FOUND, topic=offer.topic, chat_id=listing.chat_id
        )
        await self._publish_manual(message, session, resolution, source=pending)

    # --- Alias menu ----------------------------------------------------------

    async def _open_alias_menu(self, message: VkUiMessage, session: VkUserSession) -> None:
        listing = await self._manual_forwarding.destination_list(message.from_id)
        if not listing.chat_registered or not listing.destinations:
            await self._reply(message, CONFIG_ERROR_TEXT)
            return
        session.state = VkUiState.ALIAS_MENU
        self._sessions.set(message.from_id, session)
        entries = await self._alias_manager.list_with_topics(message.from_id)
        await self._reply(message, _alias_menu_text(entries), alias_menu_keyboard_json())

    async def _handle_alias_menu(self, message: VkUiMessage, session: VkUserSession) -> None:
        text = message.text.strip()
        if text in (BTN_BACK, BTN_CANCEL):
            self._sessions.clear(message.from_id)
            await self._reply(message, HELP_TEXT, main_keyboard_json())
            return
        if text == BTN_ADD:
            session.state = VkUiState.ALIAS_ADD_WAIT_TOPIC
            session.pending_topic_id = None
            self._sessions.set(message.from_id, session)
            await self._reply(message, ALIAS_ADD_TOPIC_TEXT, cancel_keyboard_json())
            return
        if text == BTN_EDIT:
            session.state = VkUiState.ALIAS_EDIT_WAIT_TOPIC
            session.pending_topic_id = None
            self._sessions.set(message.from_id, session)
            await self._reply(message, ALIAS_EDIT_TOPIC_TEXT, cancel_keyboard_json())
            return
        if text == BTN_DELETE:
            session.state = VkUiState.ALIAS_DELETE_WAIT_TOPIC
            session.pending_topic_id = None
            self._sessions.set(message.from_id, session)
            await self._reply(message, ALIAS_DELETE_TOPIC_TEXT, cancel_keyboard_json())
            return
        entries = await self._alias_manager.list_with_topics(message.from_id)
        await self._reply(message, _alias_menu_text(entries), alias_menu_keyboard_json())

    # --- Alias FSM: topic number input --------------------------------------

    async def _handle_alias_topic_input(self, message: VkUiMessage, session: VkUserSession) -> None:
        text = message.text.strip()
        if text == BTN_CANCEL:
            await self._back_to_alias_menu(message, session)
            return
        listing = await self._manual_forwarding.destination_list(message.from_id)
        ordinal = _parse_ordinal(text)
        if ordinal is None or not 1 <= ordinal <= len(listing.destinations):
            await self._reply(
                message,
                f"{TOPIC_NOT_FOUND_TEXT}\n\n{_destinations_text(listing)}",
                cancel_keyboard_json(),
            )
            return
        offer = listing.destinations[ordinal - 1]
        if not offer.available:
            await self._reply(
                message,
                f"{STALE_TOPIC_TEXT}\n\n{_destinations_text(listing)}",
                cancel_keyboard_json(),
            )
            return
        session.pending_topic_id = offer.topic.topic_id
        state = session.state
        if state is VkUiState.ALIAS_ADD_WAIT_TOPIC:
            session.state = VkUiState.ALIAS_ADD_WAIT_VALUE
            self._sessions.set(message.from_id, session)
            await self._reply(message, ALIAS_ADD_VALUE_TEXT, cancel_keyboard_json())
            return
        if state is VkUiState.ALIAS_EDIT_WAIT_TOPIC:
            session.state = VkUiState.ALIAS_EDIT_WAIT_VALUE
            self._sessions.set(message.from_id, session)
            await self._reply(message, ALIAS_EDIT_VALUE_TEXT, cancel_keyboard_json())
            return
        entries = await self._alias_manager.list_with_topics(message.from_id)
        entry = _find_entry(entries, offer.topic.topic_id)
        if entry is None or entry.alias is None:
            self._sessions.set(message.from_id, session)
            await self._reply(message, NO_ALIAS_TEXT, cancel_keyboard_json())
            return
        session.context["topic_title"] = entry.topic_title
        session.state = VkUiState.ALIAS_DELETE_CONFIRM
        self._sessions.set(message.from_id, session)
        await self._reply(
            message,
            f'Удалить алиас "{entry.alias}" у топика "{entry.topic_title}"?',  # noqa: RUF001
            confirm_keyboard_json(),
        )

    # --- Alias FSM: value input ----------------------------------------------

    async def _handle_alias_value_input(self, message: VkUiMessage, session: VkUserSession) -> None:
        text = message.text.strip()
        if text == BTN_CANCEL:
            await self._back_to_alias_menu(message, session)
            return
        topic_id = session.pending_topic_id
        try:
            await self._alias_manager.upsert(message.from_id, topic_id, text)
        except InvalidAlias as error:
            await self._reply(message, f"Алиас не сохранён: {error}", cancel_keyboard_json())
            return
        session.state = VkUiState.ALIAS_MENU
        session.pending_topic_id = None
        session.context.clear()
        self._sessions.set(message.from_id, session)
        entries = await self._alias_manager.list_with_topics(message.from_id)
        title = _topic_title(entries, topic_id)
        await self._reply(
            message,
            f'Алиас "{text}" назначен топику "{title}".',
            alias_menu_keyboard_json(),
        )

    # --- Alias FSM: delete confirmation --------------------------------------

    async def _handle_alias_delete_confirm(
        self, message: VkUiMessage, session: VkUserSession
    ) -> None:
        if message.text.strip() != BTN_YES:
            await self._back_to_alias_menu(message, session)
            return
        await self._alias_manager.delete(message.from_id, session.pending_topic_id)
        session.state = VkUiState.ALIAS_MENU
        session.pending_topic_id = None
        session.context.clear()
        self._sessions.set(message.from_id, session)
        await self._reply(message, "Алиас удалён.", alias_menu_keyboard_json())

    # --- Publishing -----------------------------------------------------------

    async def _publish_manual(
        self,
        message: VkUiMessage,
        session: VkUserSession,
        resolution: AliasResolution,
        *,
        source: VkUiMessage,
    ) -> None:
        logger.debug(
            "vk manual publication started",
            extra={
                "from_id": message.from_id,
                "destination_topic_id": resolution.topic.topic_id if resolution.topic else None,
            },
        )
        chat_id = resolution.chat_id
        topic = resolution.topic
        if chat_id is None or topic is None:
            await self._reply(message, CONFIG_ERROR_TEXT)
            return
        source_message = await self._resolve_source(source)
        if source_message is None:
            self._sessions.clear(message.from_id)
            await self._reply(message, PUBLISH_FAILED_TEXT, main_keyboard_json())
            return
        request = ManualPublicationRequest(
            source=source_message,
            initiator=source.author
            or Author(user_id=source.from_id, first_name="", last_name="", screen_name=None),
            destination=Destination(chat_id=chat_id, message_thread_id=topic.topic_id),
        )
        try:
            await self._manual_publisher.execute(request)
        except DomainError as error:
            logger.warning("manual publication failed for user %s: %s", message.from_id, error)
            self._sessions.clear(message.from_id)
            await self._reply(message, _publication_error_text(error), main_keyboard_json())
            return
        self._sessions.clear(message.from_id)
        logger.info("vk manual publication completed", extra={"from_id": message.from_id})
        await self._reply(message, SENT_TEXT, main_keyboard_json())

    async def _resolve_source(self, message: VkUiMessage) -> SourceMessage | None:
        return await self._source_resolver(message)

    # --- Helpers --------------------------------------------------------------

    async def _back_to_alias_menu(self, message: VkUiMessage, session: VkUserSession) -> None:
        session.state = VkUiState.ALIAS_MENU
        session.pending_topic_id = None
        session.context.clear()
        self._sessions.set(message.from_id, session)
        entries = await self._alias_manager.list_with_topics(message.from_id)
        await self._reply(message, _alias_menu_text(entries), alias_menu_keyboard_json())

    async def _reply(self, message: VkUiMessage, text: str, keyboard: str | None = None) -> None:
        await self._send.send_user_message(message.from_id, text, keyboard)
        logger.debug(
            "vk UI reply sent",
            extra={"from_id": message.from_id, "text_length": len(text)},
        )


def _parse_ordinal(text: str) -> int | None:
    stripped = text.strip()
    return int(stripped) if stripped.isdigit() else None


def _destinations_text(listing: ManualDestinationList) -> str:
    if not listing.destinations:
        return NO_TOPICS_TEXT
    lines = ["Выберите топик:"]
    for index, offer in enumerate(listing.destinations, start=1):
        suffix = "" if offer.available else " (недоступна)"
        lines.append(f"{index}. {offer.topic.title}{suffix}")
    return "\n".join(lines)


def _alias_menu_text(entries: Sequence[AliasEntry]) -> str:
    if not entries:
        return "Telegram-топики:\n\n" + NO_TOPICS_TEXT
    lines = ["Telegram-топики:", ""]
    for index, entry in enumerate(entries, start=1):
        alias_text = f"алиас: {entry.alias}" if entry.alias else "алиас не задан"
        lines.append(f"{index}. {entry.topic_title} — {alias_text}")
    return "\n".join(lines)


def _find_entry(entries: Sequence[AliasEntry], topic_id: int | None) -> AliasEntry | None:
    return next((entry for entry in entries if entry.topic_id == topic_id), None)


def _topic_title(entries: Sequence[AliasEntry], topic_id: int | None) -> str:
    entry = _find_entry(entries, topic_id)
    if entry is not None and entry.topic_title:
        return entry.topic_title
    return "General" if topic_id is None else str(topic_id)


def _publication_error_text(error: DomainError) -> str:
    from vk_topic_bridge.application.errors import ProvisioningError

    if isinstance(error, ProvisioningError):
        return f"{PUBLISH_FAILED_TEXT}\n{error}"
    return PUBLISH_FAILED_TEXT
