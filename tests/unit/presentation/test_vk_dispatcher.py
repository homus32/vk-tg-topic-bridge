"""VK UI dispatcher tests: Help, alias FSM, manual forwarding, no-reaction invariant."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, cast

from vkbottle.tools.formatting import Formatter

from tests.acceptance._fakes import (
    FakeSettingsRepository,
    FakeTopicsRepository,
    make_test_source_resolver,
)
from tests.acceptance._ledger import DeliveryLedger
from vk_topic_bridge.application.errors import ProvisioningError
from vk_topic_bridge.application.manual.aliasing import AliasManager, ManualForwarding
from vk_topic_bridge.application.manual.publish_manual import (
    ManualPublicationRequest,
    ManualPublicationResult,
    PublishManualMessage,
)
from vk_topic_bridge.application.ports.unit_of_work import UnitOfWork
from vk_topic_bridge.domain.enums import SourceType
from vk_topic_bridge.domain.value_objects import Author, SourceMessage, TopicInfo
from vk_topic_bridge.presentation.vk.handlers import VkUiDispatcher, VkUiMessage
from vk_topic_bridge.presentation.vk.keyboards import (
    BTN_ALIASES,
    BTN_BACK,
    BTN_CANCEL,
    BTN_DELETE,
    BTN_EDIT,
    BTN_HELP,
)
from vk_topic_bridge.presentation.vk.states import VkSessionStore, VkUiState

CHAT_ID = -1001234567890
USER_ID = 555
PEER_ID = USER_ID
GENERAL = TopicInfo(
    topic_id=None, title="General", is_general=True, is_closed=False, is_hidden=False
)
NEWS = TopicInfo(topic_id=7, title="Новости", is_general=False, is_closed=False, is_hidden=False)
STALE = TopicInfo(topic_id=9, title="Старое", is_general=False, is_closed=True, is_hidden=False)


class FakeSend:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, str | None]] = []
        self.callback_answers: list[tuple[int, str, str]] = []
        self.edited_messages: list[tuple[int, int, str, str]] = []

    async def send_user_message(self, user_id: int, text: str, keyboard_json: str | None) -> int:
        self.messages.append((user_id, text, keyboard_json))
        return len(self.messages)

    async def answer_message_event(self, user_id: int, event_id: str, text: str) -> None:
        self.callback_answers.append((user_id, event_id, text))

    async def edit_user_message(
        self, peer_id: int, conversation_message_id: int, text: str, keyboard_json: str
    ) -> None:
        self.edited_messages.append((peer_id, conversation_message_id, text, keyboard_json))

    @property
    def last_text(self) -> str:
        return self.messages[-1][1]

    @property
    def last_keyboard(self) -> str | None:
        return self.messages[-1][2]


class FakeAliases:
    def __init__(self) -> None:
        self.rows: dict[int, dict[int | None, str]] = {}

    async def list_for_user(self, vk_user_id: int) -> list[tuple[int | None, str]]:
        return [(topic_id, alias) for topic_id, alias in self.rows.get(vk_user_id, {}).items()]

    async def upsert(
        self, vk_user_id: int, topic_id: int | None, _alias: str, alias_normalized: str
    ) -> None:
        self.rows.setdefault(vk_user_id, {})[topic_id] = alias_normalized

    async def delete(self, vk_user_id: int, topic_id: int | None) -> None:
        self.rows.get(vk_user_id, {}).pop(topic_id, None)

    async def delete_all(self) -> int:
        count = sum(len(rows) for rows in self.rows.values())
        self.rows.clear()
        return count


class FakeUow:
    def __init__(self) -> None:
        self.bridge_settings = FakeSettingsRepository()
        self.telegram_topics = FakeTopicsRepository()
        self.vk_aliases = FakeAliases()
        self.deliveries = DeliveryLedger()

    async def __aenter__(self) -> FakeUow:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


@dataclass(slots=True)
class FakeManualPublisher:
    error: Exception | None = None
    result: ManualPublicationResult | None = None
    calls: list[ManualPublicationRequest] = field(default_factory=list)

    async def execute(self, request: ManualPublicationRequest) -> ManualPublicationResult:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        if self.result is not None:
            return self.result
        return ManualPublicationResult(published=True, message_ids=(1,), delivery_id=1)


@dataclass(slots=True)
class Harness:
    dispatcher: VkUiDispatcher
    send: FakeSend
    publisher: FakeManualPublisher
    uow: FakeUow
    sessions: VkSessionStore


def _msg(text: str, *, fwd: int = 0, author: Author | None = None) -> VkUiMessage:
    return VkUiMessage(
        from_id=USER_ID,
        peer_id=PEER_ID,
        text=text,
        fwd_count=fwd,
        conversation_message_id=333,
        author=author,
        raw={"text": text, "conversation_message_id": 333, "peer_id": PEER_ID},
    )


def _callback(
    payload: dict[str, object],
    *,
    user_id: int = USER_ID,
    peer_id: int = PEER_ID,
    event_id: str = "event-1",
) -> dict[str, object]:
    return {
        "type": "message_event",
        "group_id": 1,
        "object": {
            "user_id": user_id,
            "peer_id": peer_id,
            "event_id": event_id,
            "payload": payload,
            "conversation_message_id": 444,
        },
    }


def _harness(
    *,
    chat_id: int | None = CHAT_ID,
    topics: Sequence[TopicInfo] = (GENERAL, NEWS),
    publisher: FakeManualPublisher | None = None,
    source_resolver: Callable[[VkUiMessage], Awaitable[SourceMessage | None]] | None = None,
) -> Harness:
    uow = FakeUow()
    if chat_id is not None:
        uow.bridge_settings.state = replace(uow.bridge_settings.state, telegram_chat_id=chat_id)
        uow.telegram_topics.by_chat[chat_id] = list(topics)
    send = FakeSend()
    factory = cast("Callable[[], UnitOfWork]", lambda: uow)
    manual_forwarding = ManualForwarding(factory)
    alias_manager = AliasManager(factory)
    real_publisher = publisher or FakeManualPublisher()
    dispatcher = VkUiDispatcher(
        VkSessionStore(),
        send,
        manual_forwarding,
        alias_manager,
        cast(PublishManualMessage, real_publisher),
        source_resolver=cast(Any, source_resolver or make_test_source_resolver()),
    )
    return Harness(dispatcher, send, real_publisher, uow, dispatcher._sessions)


# --- Help ------------------------------------------------------------------


async def test_help_triggers_all_open_same_help() -> None:
    h = _harness()
    for trigger in ("Начать", "Помощь", "Помоги", "Help", "help", " ПОМОГИ "):
        await h.dispatcher.dispatch(_msg(trigger))
    texts = {text for _, text, _ in h.send.messages}
    assert len(texts) == 1
    assert "одно сообщение" in h.send.last_text
    assert "ничего не писать" in h.send.last_text
    assert "@all" in h.send.last_text
    assert "#изстенывк" in h.send.last_text
    assert h.send.last_keyboard is not None


async def test_help_button_text_opens_help() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg(BTN_HELP))
    assert "Перешли боту ровно одно сообщение" in h.send.last_text


# --- Alias menu ------------------------------------------------------------


async def test_aliases_button_opens_menu_with_topics() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))
    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_MENU
    assert "General" in h.send.last_text
    assert "Новости" in h.send.last_text
    assert h.send.last_keyboard is not None


async def test_alias_root_uses_text_buttons() -> None:
    h = _harness()

    await h.dispatcher.dispatch(_msg(BTN_ALIASES))

    keyboard = json.loads(h.send.last_keyboard or "{}")
    assert keyboard["inline"] is False
    actions = [button["action"] for row in keyboard["buttons"] for button in row]
    assert [action["type"] for action in actions] == ["text", "text", "text"]
    assert [action["label"] for action in actions] == [
        "➕ Добавить / изменить",  # noqa: RUF001
        "🗑 Удалить",
        "⬅️ Назад",
    ]
    assert [button["color"] for row in keyboard["buttons"] for button in row] == [
        "positive",
        "negative",
        "secondary",
    ]


async def test_main_menu_uses_text_buttons() -> None:
    h = _harness()

    await h.dispatcher.dispatch(_msg(BTN_HELP))

    keyboard = json.loads(h.send.last_keyboard or "{}")
    assert keyboard["inline"] is False
    actions = [button["action"] for row in keyboard["buttons"] for button in row]
    assert [action["type"] for action in actions] == ["text", "text"]
    assert [action["label"] for action in actions] == [BTN_ALIASES, BTN_HELP]


async def test_vk_alias_template_uses_native_formatter() -> None:
    h = _harness()

    await h.dispatcher.dispatch(_msg(BTN_ALIASES))

    assert isinstance(h.send.messages[-1][1], Formatter)
    assert any(item["type"] == "bold" for item in h.send.messages[-1][1].format_data["items"])


async def test_aliases_blocked_when_chat_unregistered() -> None:
    h = _harness(chat_id=None)
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))
    assert "недоступна" in h.send.last_text
    assert h.sessions.get(USER_ID).state is VkUiState.IDLE


async def test_aliases_menu_opens_without_snapshot_topics() -> None:
    h = _harness(topics=())
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))
    assert "недоступна" not in h.send.last_text
    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_MENU


async def test_alias_menu_has_one_add_edit_action_without_add_button() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))

    assert h.send.last_keyboard is not None
    buttons = json.loads(h.send.last_keyboard)["buttons"]
    labels = [button["action"]["label"] for row in buttons for button in row]
    assert labels == ["➕ Добавить / изменить", "🗑 Удалить", "⬅️ Назад"]  # noqa: RUF001


async def test_combined_add_edit_prompt_lists_topics() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))
    await h.dispatcher.dispatch(_msg(BTN_EDIT))

    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_MENU
    assert h.sessions.get(USER_ID).pending_alias_action == "alias_edit"
    assert h.send.last_text == "Выберите топик для добавления/изменения"
    keyboard = json.loads(h.send.last_keyboard or "{}")
    assert keyboard["inline"] is True
    labels = [button["action"]["label"] for row in keyboard["buttons"] for button in row]
    assert labels == ["General", "Новости", BTN_CANCEL]


async def test_alias_topic_picker_does_not_wait_for_text_number() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))
    await h.dispatcher.dispatch(_msg(BTN_EDIT))
    message_count = len(h.send.messages)

    await h.dispatcher.dispatch(_msg("2"))

    assert len(h.send.messages) == message_count
    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_MENU
    assert h.sessions.get(USER_ID).pending_alias_action == "alias_edit"


async def test_alias_add_topic_back_returns_to_main_menu() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))
    await h.dispatcher.dispatch(_msg(BTN_EDIT))

    await h.dispatcher.dispatch(_msg(BTN_BACK))

    assert h.sessions.get(USER_ID).state is VkUiState.IDLE
    assert h.sessions.get(USER_ID).pending_alias_action is None
    assert h.send.last_text == "Главное меню."
    assert "Номер не найден" not in h.send.last_text


async def test_alias_delete_topic_back_returns_to_main_menu() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))
    await h.dispatcher.dispatch(_msg(BTN_DELETE))

    await h.dispatcher.dispatch(_msg(BTN_BACK))

    assert h.sessions.get(USER_ID).state is VkUiState.IDLE
    assert h.sessions.get(USER_ID).pending_alias_action is None
    assert h.send.last_text == "Главное меню."


async def test_vk_callback_selects_topic_by_internal_id() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))

    consumed = await h.dispatcher.handle_message_event(_callback({"action": "alias_edit"}))
    assert consumed is True
    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_MENU
    assert h.sessions.get(USER_ID).pending_alias_action == "alias_edit"

    consumed = await h.dispatcher.handle_message_event(
        _callback({"action": "topic", "topic_id": 7}, event_id="event-2")
    )
    assert consumed is True
    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_ADD_WAIT_VALUE
    assert h.sessions.get(USER_ID).pending_topic_id == 7
    assert h.send.callback_answers == [
        (USER_ID, "event-1", "Выберите топик для алиаса."),
        (USER_ID, "event-2", "Топик выбран."),
    ]


async def test_vk_alias_topic_selection_removes_inline_and_shows_reply_cancel() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))
    await h.dispatcher.dispatch(_msg(BTN_EDIT))

    await h.dispatcher.handle_message_event(
        _callback({"action": "topic", "topic_id": 7}, event_id="event-2")
    )

    assert len(h.send.edited_messages) == 1
    peer_id, conversation_message_id, _, edited_keyboard = h.send.edited_messages[0]
    assert (peer_id, conversation_message_id) == (USER_ID, 444)
    assert json.loads(edited_keyboard)["buttons"] == []
    assert h.send.last_text == "Введите новый алиас."
    reply_keyboard = json.loads(h.send.last_keyboard or "{}")
    assert reply_keyboard["inline"] is False
    assert [button["action"]["label"] for row in reply_keyboard["buttons"] for button in row] == [
        BTN_CANCEL
    ]


async def test_vk_cancel_callback_edits_inline_message_to_cancelled_text() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg("", fwd=1))

    consumed = await h.dispatcher.handle_message_event(
        _callback({"action": "cancel"}, event_id="cancel-1")
    )

    assert consumed is True
    assert h.sessions.get(USER_ID).state is VkUiState.IDLE
    assert len(h.send.messages) == 1
    assert len(h.send.edited_messages) == 1
    peer_id, conversation_message_id, text, keyboard_json = h.send.edited_messages[0]
    assert (peer_id, conversation_message_id, text) == (USER_ID, 444, "Отмена")
    keyboard = json.loads(keyboard_json)
    assert keyboard["inline"] is False
    assert [button["action"]["label"] for row in keyboard["buttons"] for button in row] == [
        BTN_ALIASES,
        BTN_HELP,
    ]


async def test_vk_alias_topic_cancel_keeps_alias_menu_reply_keyboard() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))
    await h.dispatcher.dispatch(_msg(BTN_EDIT))

    consumed = await h.dispatcher.handle_message_event(
        _callback({"action": "cancel"}, event_id="cancel-alias")
    )

    assert consumed is True
    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_MENU
    assert len(h.send.edited_messages) == 1
    _, _, text, keyboard_json = h.send.edited_messages[0]
    assert text == "Отмена"
    keyboard = json.loads(keyboard_json)
    assert keyboard["inline"] is False
    assert [button["action"]["label"] for row in keyboard["buttons"] for button in row] == [
        BTN_EDIT,
        BTN_DELETE,
        BTN_BACK,
    ]


async def test_vk_stale_callback_is_safe_and_does_not_mutate_aliases() -> None:
    h = _harness(topics=(GENERAL, STALE))
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))
    await h.dispatcher.handle_message_event(_callback({"action": "alias_edit"}))

    consumed = await h.dispatcher.handle_message_event(
        _callback({"action": "topic", "topic_id": 9}, event_id="event-2")
    )

    assert consumed is True
    assert h.uow.vk_aliases.rows.get(USER_ID, {}) == {}
    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_MENU
    assert h.sessions.get(USER_ID).pending_alias_action == "alias_edit"
    assert "недоступен" in h.send.callback_answers[-1][2]


async def test_vk_duplicate_callback_event_is_idempotent() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))
    callback = _callback({"action": "alias_edit"})

    await h.dispatcher.handle_message_event(callback)
    message_count = len(h.send.messages)
    await h.dispatcher.handle_message_event(callback)

    assert len(h.send.messages) == message_count
    assert len(h.send.callback_answers) == 1


async def test_vk_callback_from_other_user_is_ignored() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))

    consumed = await h.dispatcher.handle_message_event(
        _callback({"action": "alias_edit"}, user_id=999, peer_id=999)
    )

    assert consumed is False
    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_MENU
    assert h.send.callback_answers == []


async def test_delete_prompt_lists_topics_without_confirmation_keyboard() -> None:
    h = _harness()
    h.uow.vk_aliases.rows[USER_ID] = {7: "важное"}
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))
    await h.dispatcher.dispatch(_msg(BTN_DELETE))

    assert h.send.last_text == "Выберите топик для удаления"
    labels = [
        button["action"]["label"]
        for row in json.loads(h.send.last_keyboard or "{}")["buttons"]
        for button in row
    ]
    assert "Да" not in labels
    assert labels == ["Новости", BTN_CANCEL]
    assert BTN_CANCEL in labels


async def test_delete_prompt_without_aliases_has_no_inline_keyboard() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))
    await h.dispatcher.dispatch(_msg(BTN_DELETE))

    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_MENU
    assert h.sessions.get(USER_ID).pending_alias_action is None
    assert "Нет топиков с алиасами" in h.send.last_text  # noqa: RUF001
    assert json.loads(h.send.last_keyboard or "{}")["inline"] is False


async def test_delete_stale_topic_edits_original_message_and_clears_inline() -> None:
    h = _harness()
    h.uow.vk_aliases.rows[USER_ID] = {7: "важное"}
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))
    await h.dispatcher.dispatch(_msg(BTN_DELETE))
    h.uow.vk_aliases.rows[USER_ID].clear()
    message_count = len(h.send.messages)

    await h.dispatcher.handle_message_event(
        _callback({"action": "topic", "topic_id": 7}, event_id="stale-delete")
    )

    assert len(h.send.messages) == message_count
    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_MENU
    assert h.sessions.get(USER_ID).pending_alias_action is None
    assert "нет алиаса" in h.send.edited_messages[-1][2]
    assert json.loads(h.send.edited_messages[-1][3])["inline"] is False


async def test_delete_removed_topic_edits_original_message_without_new_reply() -> None:
    h = _harness()
    h.uow.vk_aliases.rows[USER_ID] = {7: "важное"}
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))
    await h.dispatcher.dispatch(_msg(BTN_DELETE))
    h.uow.telegram_topics.by_chat[CHAT_ID] = [GENERAL]
    message_count = len(h.send.messages)

    await h.dispatcher.handle_message_event(
        _callback({"action": "topic", "topic_id": 7}, event_id="removed-delete")
    )

    assert len(h.send.messages) == message_count
    assert "недоступен" in h.send.edited_messages[-1][2]
    assert json.loads(h.send.edited_messages[-1][3])["inline"] is False


async def test_alias_add_flow_persists_alias() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))
    await h.dispatcher.dispatch(_msg(BTN_EDIT))
    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_MENU
    await h.dispatcher.handle_message_event(
        _callback({"action": "topic", "topic_id": 7}, event_id="alias-topic")
    )
    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_ADD_WAIT_VALUE
    await h.dispatcher.dispatch(_msg("важное"))
    assert "назначен" in h.send.last_text
    assert "Telegram-топики:" in h.send.last_text
    assert "важное" in h.send.last_text
    assert h.uow.vk_aliases.rows[USER_ID][7] == "важное"
    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_MENU


async def test_alias_add_rejects_alias_with_space() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))
    await h.dispatcher.dispatch(_msg(BTN_EDIT))
    await h.dispatcher.handle_message_event(
        _callback({"action": "topic", "topic_id": None}, event_id="alias-topic")
    )
    await h.dispatcher.dispatch(_msg("два слова"))
    assert "не сохранён" in h.send.last_text
    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_ADD_WAIT_VALUE


async def test_alias_delete_returns_updated_alias_root() -> None:
    h = _harness()
    h.uow.vk_aliases.rows[USER_ID] = {7: "важное"}
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))
    await h.dispatcher.dispatch(_msg(BTN_DELETE))
    await h.dispatcher.handle_message_event(
        _callback({"action": "topic", "topic_id": 7}, event_id="alias-topic")
    )
    assert h.uow.vk_aliases.rows[USER_ID] == {}
    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_MENU
    assert "удалён" in h.send.edited_messages[-1][2]
    assert "Telegram-топики:" in h.send.edited_messages[-1][2]
    assert "алиас не задан" in h.send.edited_messages[-1][2]


async def test_alias_edit_returns_updated_alias_root() -> None:
    h = _harness()
    h.uow.vk_aliases.rows[USER_ID] = {7: "старое"}

    await h.dispatcher.dispatch(_msg(BTN_ALIASES))
    await h.dispatcher.dispatch(_msg(BTN_EDIT))
    await h.dispatcher.handle_message_event(
        _callback({"action": "topic", "topic_id": 7}, event_id="alias-topic")
    )
    await h.dispatcher.dispatch(_msg("новости"))

    assert h.uow.vk_aliases.rows[USER_ID][7] == "новости"
    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_MENU
    assert "Telegram-топики:" in h.send.last_text
    assert "новости" in h.send.last_text


async def test_alias_back_returns_to_main_menu() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))
    await h.dispatcher.dispatch(_msg(BTN_BACK))
    assert h.sessions.get(USER_ID).state is VkUiState.IDLE
    assert h.send.last_text == "Главное меню."


async def test_unknown_idle_text_does_not_open_help() -> None:
    h = _harness()

    await h.dispatcher.dispatch(_msg("неизвестное действие"))

    assert "Как пользоваться ботом" not in h.send.last_text


# --- Manual forwarding ------------------------------------------------------


async def test_single_forward_interrupts_alias_menu_with_inline_picker() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))

    await h.dispatcher.dispatch(_msg("", fwd=1))

    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_MENU
    assert h.sessions.get(USER_ID).manual_pending_message is not None
    assert json.loads(h.send.last_keyboard or "{}")["inline"] is True
    assert h.publisher.calls == []


async def test_single_forward_interrupts_alias_value_input_with_inline_picker() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))
    await h.dispatcher.dispatch(_msg(BTN_EDIT))
    await h.dispatcher.handle_message_event(
        _callback({"action": "topic", "topic_id": 7}, event_id="alias-topic")
    )
    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_ADD_WAIT_VALUE

    await h.dispatcher.dispatch(_msg("", fwd=1))

    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_ADD_WAIT_VALUE
    assert h.sessions.get(USER_ID).pending_topic_id == 7
    assert json.loads(h.send.last_keyboard or "{}")["inline"] is True
    assert h.uow.vk_aliases.rows.get(USER_ID, {}) == {}


async def test_manual_topic_selection_preserves_alias_value_fsm() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))
    await h.dispatcher.dispatch(_msg(BTN_EDIT))
    await h.dispatcher.handle_message_event(
        _callback({"action": "topic", "topic_id": 7}, event_id="alias-topic")
    )
    await h.dispatcher.dispatch(_msg("", fwd=1))

    message_count = len(h.send.messages)
    await h.dispatcher.handle_message_event(
        _callback({"action": "topic", "topic_id": 7}, event_id="manual-topic")
    )

    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_ADD_WAIT_VALUE
    assert h.sessions.get(USER_ID).manual_pending_message is None
    assert len(h.send.messages) == message_count
    assert "✅ Сообщение отправлено" in h.send.edited_messages[-1][2]
    assert "Telegram → топик «Новости»." in h.send.edited_messages[-1][2]
    assert json.loads(h.send.edited_messages[-1][3])["inline"] is False

    await h.dispatcher.dispatch(_msg("новый"))

    assert h.uow.vk_aliases.rows[USER_ID][7] == "новый"
    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_MENU


async def test_two_forwarded_messages_error_and_no_fsm() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg("", fwd=2))
    assert "только одно сообщение" in h.send.last_text
    assert h.sessions.get(USER_ID).state is VkUiState.IDLE
    assert h.publisher.calls == []


async def test_one_forward_without_text_shows_destination_list() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg("", fwd=1))
    assert "Куда отправить" in h.send.last_text
    assert "1. General" in h.send.last_text
    assert "2. Новости" in h.send.last_text
    assert json.loads(h.send.last_keyboard or "{}")["inline"] is True
    assert h.sessions.get(USER_ID).state is VkUiState.IDLE
    assert h.sessions.get(USER_ID).manual_pending_message is not None


async def test_manual_topic_number_is_ignored_after_inline_picker() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg("", fwd=1))
    message_count = len(h.send.messages)
    picker_text = h.send.last_text
    await h.dispatcher.dispatch(_msg("2"))
    assert len(h.send.messages) == message_count
    assert h.send.last_text == picker_text
    assert h.publisher.calls == []
    assert h.sessions.get(USER_ID).state is VkUiState.IDLE
    assert h.sessions.get(USER_ID).manual_pending_message is not None


async def test_manual_publication_keeps_original_author_and_uses_current_initiator() -> None:
    original = Author(user_id=777, first_name="Автор", last_name="VK", screen_name=None)
    initiator = Author(user_id=USER_ID, first_name="Инициатор", last_name="VK", screen_name=None)

    async def resolve(_message: VkUiMessage) -> SourceMessage:
        return SourceMessage(
            source_type=SourceType.VK_MESSAGE,
            source_key="manual:555:333",
            group_id=0,
            peer_id=PEER_ID,
            conversation_message_id=333,
            author=original,
            text="оригинал",
            has_all=False,
            has_hashtag=False,
            attachments=(),
        )

    h = _harness(source_resolver=resolve)
    await h.dispatcher.dispatch(_msg("", fwd=1, author=original))
    await h.dispatcher.handle_message_event(
        _callback({"action": "topic", "topic_id": 7}, event_id="manual-topic")
    )

    request = h.publisher.calls[0]
    assert request.source.author == original
    assert request.initiator.user_id == initiator.user_id


async def test_forwarded_text_does_not_bypass_inline_topic_picker() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg("неттакого", fwd=1))
    assert "Алиас неизвестен" in h.send.last_text
    assert json.loads(h.send.last_keyboard or "{}")["inline"] is True
    assert h.sessions.get(USER_ID).state is VkUiState.IDLE
    assert h.sessions.get(USER_ID).manual_pending_message is not None
    assert h.publisher.calls == []


async def test_forwarded_alias_text_publishes_without_replacing_fsm() -> None:
    h = _harness()
    h.uow.vk_aliases.rows[USER_ID] = {7: "важное"}
    await h.dispatcher.dispatch(_msg("важное", fwd=1))
    assert len(h.publisher.calls) == 1
    assert h.publisher.calls[0].destination.message_thread_id == 7
    assert h.sessions.get(USER_ID).state is VkUiState.IDLE
    assert h.sessions.get(USER_ID).manual_pending_message is None
    assert len(h.send.messages) == 1
    assert "Сообщение отправлено" in h.send.last_text
    assert "Telegram" in h.send.last_text
    assert "Новости" in h.send.last_text
    assert json.loads(h.send.last_keyboard or "{}")["inline"] is False


async def test_forwarded_alias_shortcut_preserves_active_alias_fsm() -> None:
    h = _harness()
    h.uow.vk_aliases.rows[USER_ID] = {7: "важное"}
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))

    await h.dispatcher.dispatch(_msg("важное", fwd=1))

    assert len(h.publisher.calls) == 1
    assert h.publisher.calls[0].destination.message_thread_id == 7
    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_MENU
    assert h.sessions.get(USER_ID).manual_pending_message is None


async def test_forwarded_stale_alias_text_does_not_publish_without_topic_callback() -> None:
    h = _harness(topics=(GENERAL, STALE))
    h.uow.vk_aliases.rows[USER_ID] = {9: "старое"}
    await h.dispatcher.dispatch(_msg("старое", fwd=1))
    assert h.publisher.calls == []
    assert h.sessions.get(USER_ID).state is VkUiState.IDLE
    assert json.loads(h.send.last_keyboard or "{}")["inline"] is True


async def test_multi_message_never_starts_fsm_when_alias_present() -> None:
    h = _harness()
    h.uow.vk_aliases.rows[USER_ID] = {7: "важное"}
    await h.dispatcher.dispatch(_msg("важное", fwd=3))
    assert h.publisher.calls == []
    assert h.sessions.get(USER_ID).state is VkUiState.IDLE


async def test_cancel_in_wait_destination_returns_idle() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg("", fwd=1))
    await h.dispatcher.handle_message_event(
        _callback({"action": "cancel"}, event_id="manual-cancel")
    )
    assert h.sessions.get(USER_ID).state is VkUiState.IDLE
    assert h.publisher.calls == []


async def test_wait_destination_ignores_text_input() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg("", fwd=1))
    message_count = len(h.send.messages)
    picker_text = h.send.last_text
    await h.dispatcher.dispatch(_msg("важное"))
    assert len(h.send.messages) == message_count
    assert h.send.last_text == picker_text
    assert h.publisher.calls == []


async def test_config_error_when_unregistered() -> None:
    h = _harness(chat_id=None)
    await h.dispatcher.dispatch(_msg("", fwd=1))
    assert "недоступна" in h.send.last_text
    assert h.sessions.get(USER_ID).state is VkUiState.IDLE


async def test_manual_publication_failure_clears_fsm() -> None:
    h = _harness(publisher=FakeManualPublisher(error=ProvisioningError("topic gone")))
    await h.dispatcher.dispatch(_msg("", fwd=1))
    await h.dispatcher.handle_message_event(
        _callback({"action": "topic", "topic_id": 7}, event_id="manual-topic")
    )
    assert h.sessions.get(USER_ID).state is VkUiState.IDLE
    assert "Не удалось" in h.send.edited_messages[-1][2]  # noqa: RUF001


async def test_manual_publication_result_failure_keeps_destination_fsm() -> None:
    publisher = FakeManualPublisher(
        result=ManualPublicationResult(
            published=False,
            message_ids=(),
            delivery_id=1,
            error="telegram_topic_not_found",
        )
    )
    h = _harness(publisher=publisher)

    await h.dispatcher.dispatch(_msg("", fwd=1))
    await h.dispatcher.handle_message_event(
        _callback({"action": "topic", "topic_id": 7}, event_id="manual-topic")
    )

    assert h.sessions.get(USER_ID).state is VkUiState.IDLE
    assert h.sessions.get(USER_ID).manual_pending_message is not None
    assert "топик" in h.send.edited_messages[-1][2].lower()
    assert "не отправлено" in h.send.edited_messages[-1][2].lower()
    retry_keyboard = json.loads(h.send.edited_messages[-1][3])
    assert retry_keyboard["inline"] is True
    retry_labels = [
        button["action"]["label"] for row in retry_keyboard["buttons"] for button in row
    ]
    assert retry_labels == ["General", BTN_CANCEL]

    publisher.result = ManualPublicationResult(
        published=True,
        message_ids=(2,),
        delivery_id=2,
    )
    await h.dispatcher.handle_message_event(
        _callback({"action": "topic", "topic_id": None}, event_id="manual-general")
    )

    assert h.sessions.get(USER_ID).state is VkUiState.IDLE
    assert len(publisher.calls) == 2
    assert publisher.calls[1].destination.message_thread_id is None
    assert "✅ Сообщение отправлено" in h.send.edited_messages[-1][2]
    assert "Telegram → топик «General»." in h.send.edited_messages[-1][2]


# --- session isolation -------------------------------------------------------


async def test_two_users_have_independent_sessions() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg("", fwd=1))
    other = replace(_msg("", fwd=1), from_id=999, peer_id=999)
    await h.dispatcher.dispatch(other)
    assert h.sessions.get(USER_ID).state is VkUiState.IDLE
    assert h.sessions.get(999).state is VkUiState.IDLE
    assert h.sessions.get(USER_ID).manual_pending_message is not None
    assert h.sessions.get(999).manual_pending_message is not None
    # cancel for one user does not touch the other
    await h.dispatcher.handle_message_event(
        _callback({"action": "cancel"}, event_id="manual-cancel")
    )
    assert h.sessions.get(USER_ID).state is VkUiState.IDLE
    assert h.sessions.get(999).manual_pending_message is not None


# --- raw consumer seam (VkUiRouter.handle_dm) --------------------------------


def _update(payload: dict[str, object]) -> dict[str, object]:
    return {"type": "message_new", "group_id": 1, "object": payload}


async def test_handle_dm_normalizes_plain_object_payload() -> None:
    h = _harness()
    consumed = await h.dispatcher.handle_dm(
        _update({"peer_id": USER_ID, "from_id": USER_ID, "text": "Помощь"})
    )
    assert consumed is True
    assert "Перешли боту ровно одно сообщение" in h.send.last_text


async def test_handle_dm_supports_nested_message_payload() -> None:
    h = _harness()
    consumed = await h.dispatcher.handle_dm(
        _update(
            {
                "message": {
                    "peer_id": USER_ID,
                    "from_id": USER_ID,
                    "conversation_message_id": 333,
                    "text": "",
                    "fwd_messages": [{"id": 1}],
                }
            }
        )
    )
    assert consumed is True
    assert "Куда отправить" in h.send.last_text
    assert h.sessions.get(USER_ID).state is VkUiState.IDLE
    assert h.sessions.get(USER_ID).manual_pending_message is not None


async def test_handle_dm_rejects_payload_without_ids() -> None:
    h = _harness()
    consumed = await h.dispatcher.handle_dm(_update({"text": "Помощь"}))
    assert consumed is False
    assert h.send.messages == []


async def test_handle_dm_counts_multiple_forwards_from_nested_payload() -> None:
    h = _harness()
    await h.dispatcher.handle_dm(
        _update(
            {
                "message": {
                    "peer_id": USER_ID,
                    "from_id": USER_ID,
                    "conversation_message_id": 333,
                    "text": "",
                    "fwd_messages": [{"id": 1}, {"id": 2}],
                }
            }
        )
    )
    assert "только одно сообщение" in h.send.last_text
