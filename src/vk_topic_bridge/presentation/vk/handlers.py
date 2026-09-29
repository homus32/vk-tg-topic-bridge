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
from typing import cast

from vkbottle.tools.formatting import Formatter, bold
from vkbottle.tools.keyboard import EMPTY_KEYBOARD
from vkbottle_types.events.bot_events import MessageEvent
from vkbottle_types.events.objects.group_event_objects import MessageEventObject

from vk_topic_bridge.application.errors import TELEGRAM_TOPIC_NOT_FOUND_CODE, DomainError
from vk_topic_bridge.application.manual.aliasing import (
    AliasEntry,
    AliasManager,
    AliasResolution,
    ManualDestinationList,
    ManualDestinationOffer,
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
    BTN_ALIASES,
    BTN_BACK,
    BTN_CANCEL,
    BTN_DELETE,
    BTN_EDIT,
    BTN_HELP,
    alias_menu_keyboard_json,
    cancel_keyboard_json,
    is_help_trigger,
    main_keyboard_json,
    topic_selection_keyboard,
)
from vk_topic_bridge.presentation.vk.states import VkSessionStore, VkUiState, VkUserSession

logger = logging.getLogger(__name__)


def _format_notice(title: str, body: str = "") -> Formatter:
    if not body:
        return Formatter("{title}").format(title=bold(title))
    return Formatter("{title}\n\n{body}").format(title=bold(title), body=body)


HELP_TEXT = Formatter(
    "{title}\n\n"
    "{manual_heading}\n"
    "1. Перешли боту ровно одно сообщение из VK.\n"
    "2. В подписи к пересылке можно ничего не писать или написать алиас — "
    "тогда сообщение сразу уйдёт в его топик.\n"
    "3. Если алиас не написан, бот предложит выбрать топик кнопкой.\n\n"
    "{alias_heading}\n"
    "Алиас — короткое имя, которое вы даёте топику Telegram.\n"
    "Вместо выбора кнопкой просто напишите алиас в подписи к пересылке.\n"
    "Пример: пишете «новости» — сообщение уйдёт в топик «Новости».\n"
    "Управление алиасами — кнопка «🏷 Алиасы» в главном меню.\n\n"
    "{auto_heading}\n"
    "Если включены настройки, бот пересылает сообщения из VK сам:\n"
    "• сообщения с @all;\n"
    "• сообщения с любым #хештегом.\n\n"
    "{wall_heading}\n"
    "Посты стены VK пересылаются автоматически, если включена пересылка стены.\n"
    "В таких постах есть ссылка на оригинал и метка #изстенывк.\n\n"
    "{tags_heading}\n"
    "Бот добавляет метки сам, писать их не нужно.\n"
    "#извк — у каждой пересылки сообщений VK.\n"
    "#извкважно — у автоматических публикаций с @all.\n"
    "У ручных пересылок метка только #извк, даже если в сообщении есть @all.\n\n"
    "{important_heading}\n"
    "⚠️ За одну ручную операцию пересылается только одно сообщение.\n"
    "⬅️ Для отмены текущего действия используй кнопку «✖ Отмена».\n"
    "По всем вопросам, предложениям или при неисправностях пишите в ТГ или ВК\n"
    "TG: https://t.me/homus32\n"
    "VK: @kamasutra2281337\n\n"
    "{important}",
).format(
    title=bold("🤖 Как пользоваться ботом"),
    manual_heading=bold("📨 Ручная пересылка"),
    alias_heading=bold("🏷 Алиасы"),
    auto_heading=bold("🔄 Автоматическая пересылка"),
    wall_heading=bold("🧱 Стена VK"),
    tags_heading=bold("📌 Метки публикаций"),
    important_heading=bold("⚠️ Важно"),
    important=bold("⚠️ Важно: бот является инициативой студента, не администрации колледжа Хекслет"),
)

UNKNOWN_ALIAS_TEXT = "Алиас неизвестен."
MULTI_MESSAGE_TEXT = (
    "Можно переслать только одно сообщение за одну операцию.\nОтправьте одно сообщение отдельно."
)
STALE_ALIAS_TEXT = "Топик выбранного алиаса больше недоступен."
CONFIG_ERROR_TEXT = _format_notice(
    "Ручная пересылка пока недоступна",
    "Telegram-чат не зарегистрирован или в нём нет доступных топиков.",
)
NO_TOPICS_TEXT = "Нет доступных топиков для выбора."
TOPIC_NOT_FOUND_TEXT = "Номер не найден."
MAIN_MENU_TEXT = _format_notice("Главное меню.")
UNKNOWN_ACTION_TEXT = "Выберите действие из меню."
ALIAS_ADD_EDIT_TOPIC_TEXT = "Выберите топик для добавления/изменения"
ALIAS_ADD_VALUE_TEXT = "Введите новый алиас."
ALIAS_DELETE_TOPIC_TEXT = "Выберите топик для удаления"
NO_ALIAS_TEXT = "У этого топика нет алиаса."
NO_ALIAS_TOPICS_TEXT = "Нет топиков с алиасами для удаления."
PUBLISH_FAILED_TEXT = _format_notice("Не удалось отправить сообщение.", "Попробуйте позже.")
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
        self._handled_event_ids: set[str] = set()

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

    async def handle_message_event(self, update: Mapping[str, object]) -> bool:
        raw_object = update.get("object")
        if not isinstance(raw_object, Mapping):
            return False
        raw_user_id = raw_object.get("user_id")
        raw_peer_id = raw_object.get("peer_id")
        raw_event_id = raw_object.get("event_id")
        raw_payload = raw_object.get("payload")
        raw_cmid = raw_object.get("conversation_message_id")
        if (
            not isinstance(raw_user_id, int)
            or isinstance(raw_user_id, bool)
            or not isinstance(raw_peer_id, int)
            or isinstance(raw_peer_id, bool)
            or not isinstance(raw_event_id, str)
            or (raw_payload is not None and not isinstance(raw_payload, dict))
            or (raw_cmid is not None and not isinstance(raw_cmid, int))
        ):
            return False
        user_id = cast(int, raw_user_id)
        peer_id = cast(int, raw_peer_id)
        event_id = cast(str, raw_event_id)
        payload = cast("dict[str, object] | None", raw_payload)
        conversation_message_id = cast("int | None", raw_cmid)
        try:
            event_object = MessageEventObject(
                user_id=user_id,
                peer_id=peer_id,
                event_id=event_id,
                payload=payload,
                conversation_message_id=conversation_message_id,
            )
            MessageEvent(object=event_object)
        except TypeError, ValueError:
            return False
        if peer_id != user_id:
            return False
        if event_id in self._handled_event_ids:
            return True
        self._handled_event_ids.add(event_id)
        if payload is None or not isinstance(payload.get("action"), str):
            await self._answer_event(user_id, event_id, "Кнопка устарела.")
            return True
        message = VkUiMessage(
            from_id=user_id,
            peer_id=peer_id,
            text="",
            fwd_count=0,
            conversation_message_id=conversation_message_id,
            raw={"message_event": payload},
        )
        session = self._sessions.peek(message.from_id)
        if session is None:
            return False
        action = cast(str, payload["action"])
        if action == "cancel" and session.manual_pending_message is not None:
            await self._answer_event(message.from_id, event_id, "Отмена")
            session.manual_pending_message = None
            self._sessions.set(message.from_id, session)
            await self._edit_event_message(
                message,
                "Отмена",
                _reply_keyboard_json(session.state),
            )
            return True
        if action == "help" and session.state is VkUiState.IDLE:
            await self._answer_event(message.from_id, event_id, "Помощь.")
            await self._reply(message, HELP_TEXT, main_keyboard_json())
            return True
        if action == "alias_menu" and session.state is VkUiState.IDLE:
            await self._answer_event(message.from_id, event_id, "Алиасы.")
            await self._open_alias_menu(message, session)
            return True
        if action == "alias_back" and session.state is VkUiState.ALIAS_MENU:
            await self._answer_event(message.from_id, event_id, "Главное меню.")
            self._sessions.clear(message.from_id)
            await self._reply(message, MAIN_MENU_TEXT, main_keyboard_json())
            return True
        if action in {"alias_edit", "alias_delete"} and session.state is VkUiState.ALIAS_MENU:
            prompt = (
                ALIAS_ADD_EDIT_TOPIC_TEXT if action == "alias_edit" else ALIAS_DELETE_TOPIC_TEXT
            )
            await self._answer_event(message.from_id, event_id, "Выберите топик для алиаса.")
            await self._start_alias_topic_input(message, session, action, prompt)
            return True
        if action == "cancel" and session.state is not VkUiState.IDLE:
            await self._answer_event(message.from_id, event_id, "Отмена")
            if session.pending_alias_action is not None or session.state in (
                VkUiState.ALIAS_ADD_WAIT_TOPIC,
                VkUiState.ALIAS_DELETE_WAIT_TOPIC,
            ):
                session.state = VkUiState.ALIAS_MENU
                session.pending_alias_action = None
                session.pending_topic_id = None
                session.context.clear()
                self._sessions.set(message.from_id, session)
                keyboard_json = alias_menu_keyboard_json()
            else:
                self._sessions.clear(message.from_id)
                keyboard_json = main_keyboard_json()
            await self._edit_event_message(message, "Отмена", keyboard_json)
            return True
        if action == "topic" and "topic_id" in payload:
            topic_id = payload["topic_id"]
            if topic_id is not None and (
                not isinstance(topic_id, int) or isinstance(topic_id, bool)
            ):
                await self._answer_event(message.from_id, event_id, "Кнопка устарела.")
                return True
            if session.manual_pending_message is not None:
                await self._handle_manual_topic_callback(message, session, topic_id, event_id)
            else:
                await self._handle_topic_callback(message, session, topic_id, event_id)
            return True
        await self._answer_event(message.from_id, event_id, "Кнопка устарела.")
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
        if message.fwd_count == 1:
            await self._handle_forwarded(message, session, message.text.strip())
        elif session.manual_pending_message is not None:
            pass
        elif state is VkUiState.WAIT_DESTINATION:
            await self._handle_wait_destination(message, session)
        elif state is VkUiState.ALIAS_MENU:
            await self._handle_alias_menu(message, session)
        elif state in (
            VkUiState.ALIAS_ADD_WAIT_TOPIC,
            VkUiState.ALIAS_DELETE_WAIT_TOPIC,
        ):
            await self._handle_alias_topic_input(message, session)
        elif state is VkUiState.ALIAS_ADD_WAIT_VALUE:
            await self._handle_alias_value_input(message, session)
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
            extra={"from_id": message.from_id, "outcome": "unknown_action"},
        )
        await self._reply(message, UNKNOWN_ACTION_TEXT, main_keyboard_json())

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
            session.manual_pending_message = None
            self._sessions.set(message.from_id, session)
            await self._reply(message, CONFIG_ERROR_TEXT)
            return
        session.manual_pending_message = None
        self._sessions.set(message.from_id, session)
        if text:
            resolution = await self._manual_forwarding.resolve_alias(message.from_id, text)
            if resolution.status is AliasResolution.Status.FOUND:
                await self._publish_manual(message, session, resolution, source=message)
                return
            if resolution.status is AliasResolution.Status.STALE:
                notice = (
                    f"{STALE_ALIAS_TEXT}\n\n{_destinations_text(listing)}\n"
                    "Выберите другой топик кнопкой или настройте алиасы заново."
                )
            else:
                notice = f"{UNKNOWN_ALIAS_TEXT}\n\n{_destinations_text(listing)}"
        else:
            notice = f"Куда отправить сообщение?\n\n{_destinations_text(listing)}"
        session.manual_pending_message = message
        await self._reply(
            message,
            notice,
            topic_selection_keyboard(_available_topic_rows(listing)),
        )
        self._sessions.set(message.from_id, session)

    # --- WAIT_DESTINATION ---------------------------------------------------

    async def _handle_wait_destination(
        self, _message: VkUiMessage, _session: VkUserSession
    ) -> None:
        return

    # --- Alias menu ----------------------------------------------------------

    async def _open_alias_menu(self, message: VkUiMessage, session: VkUserSession) -> None:
        listing = await self._manual_forwarding.destination_list(message.from_id)
        if not listing.chat_registered or not listing.destinations:
            await self._reply(message, CONFIG_ERROR_TEXT)
            return
        session.state = VkUiState.ALIAS_MENU
        session.pending_alias_action = None
        self._sessions.set(message.from_id, session)
        entries = await self._alias_manager.list_with_topics(message.from_id)
        await self._reply(message, _alias_menu_text(entries), alias_menu_keyboard_json())

    async def _start_alias_topic_input(
        self,
        message: VkUiMessage,
        session: VkUserSession,
        action: str,
        prompt: str,
    ) -> None:
        listing = await self._manual_forwarding.destination_list(message.from_id)
        if not listing.chat_registered or not listing.destinations:
            self._sessions.clear(message.from_id)
            await self._reply(message, CONFIG_ERROR_TEXT, main_keyboard_json())
            return
        topic_rows = _available_topic_rows(listing)
        if action == "alias_delete":
            entries = await self._alias_manager.list_with_topics(message.from_id)
            topic_rows = _available_alias_topic_rows(listing, entries)
            if not topic_rows:
                session.state = VkUiState.ALIAS_MENU
                session.pending_alias_action = None
                session.pending_topic_id = None
                session.context.clear()
                self._sessions.set(message.from_id, session)
                await self._reply(message, NO_ALIAS_TOPICS_TEXT, alias_menu_keyboard_json())
                return
        session.state = VkUiState.ALIAS_MENU
        session.pending_alias_action = action
        session.pending_topic_id = None
        self._sessions.set(message.from_id, session)
        await self._reply(
            message,
            prompt,
            topic_selection_keyboard(topic_rows),
        )

    async def _handle_alias_menu(self, message: VkUiMessage, session: VkUserSession) -> None:
        text = message.text.strip()
        if text in (BTN_BACK, BTN_CANCEL):
            session.pending_alias_action = None
            session.pending_topic_id = None
            session.context.clear()
            self._sessions.clear(message.from_id)
            await self._reply(message, MAIN_MENU_TEXT, main_keyboard_json())
            return
        if session.pending_alias_action is not None:
            return
        if text == BTN_EDIT:
            await self._start_alias_topic_input(
                message,
                session,
                "alias_edit",
                ALIAS_ADD_EDIT_TOPIC_TEXT,
            )
            return
        if text == BTN_DELETE:
            await self._start_alias_topic_input(
                message,
                session,
                "alias_delete",
                ALIAS_DELETE_TOPIC_TEXT,
            )
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
                topic_selection_keyboard(_available_topic_rows(listing)),
            )
            return
        offer = listing.destinations[ordinal - 1]
        if not offer.available:
            await self._reply(
                message,
                f"{STALE_TOPIC_TEXT}\n\n{_destinations_text(listing)}",
                topic_selection_keyboard(_available_topic_rows(listing)),
            )
            return
        session.pending_topic_id = offer.topic.topic_id
        state = session.state
        if state is VkUiState.ALIAS_ADD_WAIT_TOPIC:
            session.state = VkUiState.ALIAS_ADD_WAIT_VALUE
            self._sessions.set(message.from_id, session)
            await self._reply(message, ALIAS_ADD_VALUE_TEXT, cancel_keyboard_json())
            return
        entries = await self._alias_manager.list_with_topics(message.from_id)
        entry = _find_entry(entries, offer.topic.topic_id)
        if entry is None or entry.alias is None:
            self._sessions.set(message.from_id, session)
            await self._reply(
                message,
                NO_ALIAS_TEXT,
                cancel_keyboard_json(),
            )
            return
        if state is VkUiState.ALIAS_DELETE_WAIT_TOPIC:
            await self._alias_manager.delete(message.from_id, offer.topic.topic_id)
            session.state = VkUiState.ALIAS_MENU
            session.pending_topic_id = None
            session.context.clear()
            self._sessions.set(message.from_id, session)
            entries = await self._alias_manager.list_with_topics(message.from_id)
            await self._reply(
                message,
                f"Алиас удалён.\n\n{_alias_menu_text(entries)}",
                alias_menu_keyboard_json(),
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
            f'Алиас "{text}" назначен топику "{title}".\n\n{_alias_menu_text(entries)}',
            alias_menu_keyboard_json(),
        )

    # --- Publishing -----------------------------------------------------------

    async def _publish_manual(
        self,
        message: VkUiMessage,
        session: VkUserSession,
        resolution: AliasResolution,
        *,
        source: VkUiMessage,
        callback_message: VkUiMessage | None = None,
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
            await self._manual_failure(
                message, session, CONFIG_ERROR_TEXT, callback_message=callback_message
            )
            return
        source_message = await self._resolve_source(source)
        if source_message is None:
            await self._manual_failure(
                message, session, PUBLISH_FAILED_TEXT, callback_message=callback_message
            )
            return
        request = ManualPublicationRequest(
            source=source_message,
            initiator=message.author
            or Author(user_id=message.from_id, first_name="", last_name="", screen_name=None),
            destination=Destination(chat_id=chat_id, message_thread_id=topic.topic_id),
        )
        try:
            result = await self._manual_publisher.execute(request)
        except DomainError as error:
            logger.warning("manual publication failed for user %s: %s", message.from_id, error)
            await self._manual_failure(
                message,
                session,
                _publication_error_text(error),
                callback_message=callback_message,
            )
            return
        if not result.published:
            logger.warning(
                "vk manual publication completed with failure",
                extra={"from_id": message.from_id, "reason": result.error},
            )
            if result.error == TELEGRAM_TOPIC_NOT_FOUND_CODE:
                await self._keep_manual_destination_open(
                    message,
                    session,
                    source,
                    topic.topic_id,
                    result.error,
                    callback_message=callback_message,
                )
                return
            await self._manual_failure(
                message,
                session,
                _manual_result_error_text(result.error),
                callback_message=callback_message,
            )
            return
        session.manual_pending_message = None
        self._sessions.set(message.from_id, session)
        logger.info("vk manual publication completed", extra={"from_id": message.from_id})
        if callback_message is not None:
            await self._edit_event_message(
                callback_message,
                _manual_success_text(topic.title),
                _reply_keyboard_json(session.state),
            )
        else:
            await self._reply(
                message,
                _manual_success_text(topic.title),
                _reply_keyboard_json(session.state),
            )

    async def _keep_manual_destination_open(
        self,
        message: VkUiMessage,
        session: VkUserSession,
        source: VkUiMessage,
        failed_topic_id: int | None,
        error_code: str,
        *,
        callback_message: VkUiMessage | None = None,
    ) -> None:
        listing = await self._manual_forwarding.destination_list(message.from_id)
        if not listing.chat_registered or not listing.destinations:
            await self._manual_failure(
                message, session, CONFIG_ERROR_TEXT, callback_message=callback_message
            )
            return
        destinations = tuple(
            ManualDestinationOffer(
                topic=offer.topic,
                available=offer.available and offer.topic.topic_id != failed_topic_id,
            )
            for offer in listing.destinations
        )
        session.manual_pending_message = source
        self._sessions.set(message.from_id, session)
        retry_listing = ManualDestinationList(
            chat_registered=listing.chat_registered,
            destinations=destinations,
            chat_id=listing.chat_id,
        )
        logger.debug(
            "vk manual destination retry offered",
            extra={
                "from_id": message.from_id,
                "state_after": session.state.value,
                "reason": error_code,
                "message_count": len(destinations),
            },
        )
        retry_text = (
            f"{_manual_result_error_text(error_code)}\n\n{_destinations_text(retry_listing)}"
        )
        retry_keyboard = topic_selection_keyboard(_available_topic_rows(retry_listing))
        if callback_message is not None:
            await self._edit_event_message(callback_message, retry_text, retry_keyboard)
        else:
            await self._reply(message, retry_text, retry_keyboard)

    async def _resolve_source(self, message: VkUiMessage) -> SourceMessage | None:
        return await self._source_resolver(message)

    # --- Helpers --------------------------------------------------------------

    async def _back_to_alias_menu(self, message: VkUiMessage, session: VkUserSession) -> None:
        session.state = VkUiState.ALIAS_MENU
        session.pending_alias_action = None
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

    async def _answer_event(self, user_id: int, event_id: str, text: str) -> None:
        await self._send.answer_message_event(user_id, event_id, text)

    async def _edit_event_message(
        self, message: VkUiMessage, text: str, keyboard_json: str
    ) -> bool:
        conversation_message_id = message.conversation_message_id
        if conversation_message_id is None:
            return False
        await self._send.edit_user_message(
            message.peer_id,
            conversation_message_id,
            text,
            keyboard_json,
        )
        return True

    async def _manual_failure(
        self,
        message: VkUiMessage,
        session: VkUserSession,
        text: str,
        *,
        callback_message: VkUiMessage | None = None,
    ) -> None:
        session.manual_pending_message = None
        self._sessions.set(message.from_id, session)
        keyboard_json = _reply_keyboard_json(session.state)
        if callback_message is not None and await self._edit_event_message(
            callback_message, text, keyboard_json
        ):
            return
        await self._reply(message, text, keyboard_json)

    async def _handle_manual_topic_callback(
        self,
        message: VkUiMessage,
        session: VkUserSession,
        topic_id: int | None,
        event_id: str,
    ) -> None:
        listing = await self._manual_forwarding.destination_list(message.from_id)
        offer = next(
            (
                candidate
                for candidate in listing.destinations
                if candidate.topic.topic_id == topic_id
            ),
            None,
        )
        if offer is None or not offer.available:
            await self._answer_event(message.from_id, event_id, STALE_TOPIC_TEXT)
            retry_text = f"{STALE_TOPIC_TEXT}\n\n{_destinations_text(listing)}"
            retry_keyboard = topic_selection_keyboard(_available_topic_rows(listing))
            if not await self._edit_event_message(message, retry_text, retry_keyboard):
                await self._reply(message, retry_text, retry_keyboard)
            return
        await self._answer_event(message.from_id, event_id, "Топик выбран.")
        pending = session.manual_pending_message
        if not isinstance(pending, VkUiMessage):
            await self._manual_failure(message, session, PUBLISH_FAILED_TEXT)
            return
        resolution = AliasResolution(
            status=AliasResolution.Status.FOUND,
            topic=offer.topic,
            chat_id=listing.chat_id,
        )
        await self._publish_manual(
            message,
            session,
            resolution,
            source=pending,
            callback_message=message,
        )

    async def _finish_delete_topic_error(
        self, message: VkUiMessage, session: VkUserSession, text: str
    ) -> None:
        session.state = VkUiState.ALIAS_MENU
        session.pending_alias_action = None
        session.pending_topic_id = None
        session.context.clear()
        self._sessions.set(message.from_id, session)
        await self._edit_event_message(message, text, alias_menu_keyboard_json())

    @staticmethod
    def _is_delete_topic_selection(session: VkUserSession) -> bool:
        return (
            session.pending_alias_action == "alias_delete"
            or session.state is VkUiState.ALIAS_DELETE_WAIT_TOPIC
        )

    async def _handle_topic_callback(
        self,
        message: VkUiMessage,
        session: VkUserSession,
        topic_id: int | None,
        event_id: str,
    ) -> None:
        listing = await self._manual_forwarding.destination_list(message.from_id)
        offer = next(
            (
                candidate
                for candidate in listing.destinations
                if candidate.topic.topic_id == topic_id
            ),
            None,
        )
        if offer is None or not offer.available:
            await self._answer_event(message.from_id, event_id, STALE_TOPIC_TEXT)
            if self._is_delete_topic_selection(session):
                await self._finish_delete_topic_error(message, session, STALE_TOPIC_TEXT)
                return
            await self._reply(
                message,
                f"{STALE_TOPIC_TEXT}\n\n{_destinations_text(listing)}",
                topic_selection_keyboard(_available_topic_rows(listing)),
            )
            return
        if session.state is VkUiState.WAIT_DESTINATION:
            await self._answer_event(message.from_id, event_id, "Топик выбран.")
            resolution = AliasResolution(
                status=AliasResolution.Status.FOUND,
                topic=offer.topic,
                chat_id=listing.chat_id,
            )
            pending = session.pending_message
            if not isinstance(pending, VkUiMessage):
                await self._manual_failure(message, session, PUBLISH_FAILED_TEXT)
                return
            await self._publish_manual(
                message,
                session,
                resolution,
                source=pending,
                callback_message=message,
            )
            return
        alias_action = session.pending_alias_action
        if alias_action is None and session.state is VkUiState.ALIAS_ADD_WAIT_TOPIC:
            alias_action = "alias_edit"
        if alias_action is None and session.state is VkUiState.ALIAS_DELETE_WAIT_TOPIC:
            alias_action = "alias_delete"
        entries: list[AliasEntry] = []
        if alias_action == "alias_delete":
            entries = await self._alias_manager.list_with_topics(message.from_id)
            entry = _find_entry(entries, offer.topic.topic_id)
            if entry is None or entry.alias is None:
                await self._answer_event(message.from_id, event_id, NO_ALIAS_TEXT)
                await self._finish_delete_topic_error(message, session, NO_ALIAS_TEXT)
                return
        await self._answer_event(message.from_id, event_id, "Топик выбран.")
        session.pending_topic_id = offer.topic.topic_id
        if alias_action == "alias_edit":
            await self._edit_event_message(
                message,
                f"Топик выбран: {offer.topic.title}",
                EMPTY_KEYBOARD,
            )
            session.pending_alias_action = None
            session.state = VkUiState.ALIAS_ADD_WAIT_VALUE
            self._sessions.set(message.from_id, session)
            await self._reply(message, ALIAS_ADD_VALUE_TEXT, cancel_keyboard_json())
            return
        if alias_action != "alias_delete":
            await self._answer_event(message.from_id, event_id, "Кнопка устарела.")
            return
        await self._alias_manager.delete(message.from_id, offer.topic.topic_id)
        session.state = VkUiState.ALIAS_MENU
        session.pending_alias_action = None
        session.pending_topic_id = None
        session.context.clear()
        self._sessions.set(message.from_id, session)
        entries = await self._alias_manager.list_with_topics(message.from_id)
        alias_root = f"Алиас удалён.\n\n{_alias_menu_text(entries)}"
        if not await self._edit_event_message(message, alias_root, alias_menu_keyboard_json()):
            await self._reply(message, alias_root, alias_menu_keyboard_json())


def _reply_keyboard_json(state: VkUiState) -> str:
    if state is VkUiState.ALIAS_ADD_WAIT_VALUE:
        return cancel_keyboard_json()
    if state in (
        VkUiState.ALIAS_MENU,
        VkUiState.ALIAS_ADD_WAIT_TOPIC,
        VkUiState.ALIAS_DELETE_WAIT_TOPIC,
    ):
        return alias_menu_keyboard_json()
    return main_keyboard_json()


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
    return Formatter("{heading}\n{body}").format(
        heading=bold(lines[0]),
        body="\n".join(lines[1:]),
    )


def _available_topic_rows(listing: ManualDestinationList) -> list[tuple[int | None, str]]:
    return [
        (offer.topic.topic_id, offer.topic.title)
        for offer in listing.destinations
        if offer.available
    ]


def _available_alias_topic_rows(
    listing: ManualDestinationList, entries: Sequence[AliasEntry]
) -> list[tuple[int | None, str]]:
    aliased_topic_ids = {entry.topic_id for entry in entries if entry.alias is not None}
    return [
        (offer.topic.topic_id, offer.topic.title)
        for offer in listing.destinations
        if offer.available and offer.topic.topic_id in aliased_topic_ids
    ]


def _alias_menu_text(entries: Sequence[AliasEntry]) -> str:
    if not entries:
        return "Telegram-топики:\n\n" + NO_TOPICS_TEXT
    lines = ["Telegram-топики:", ""]
    for index, entry in enumerate(entries, start=1):
        alias_text = f"алиас: {entry.alias}" if entry.alias else "алиас не задан"
        lines.append(f"{index}. {entry.topic_title} — {alias_text}")
    return Formatter("{heading}\n\n{body}").format(
        heading=bold(lines[0]),
        body="\n".join(lines[2:]),
    )


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


def _manual_result_error_text(error_code: str | None) -> str:
    if error_code == TELEGRAM_TOPIC_NOT_FOUND_CODE:
        return (
            "Выбранный Telegram-топик удалён или закрыт. "
            "Сообщение не отправлено. Выберите другой топик."
        )
    if error_code == "publication_ambiguous":
        return "Telegram не подтвердил отправку. Сообщение не отправлено. Попробуйте позже."
    return PUBLISH_FAILED_TEXT


def _manual_success_text(topic_title: str) -> Formatter:
    return _format_notice(
        "✅ Сообщение отправлено",
        f"Telegram → топик «{topic_title}».",
    )
