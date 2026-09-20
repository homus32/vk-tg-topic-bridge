"""VK UI dispatcher tests: Help, alias FSM, manual forwarding, no-reaction invariant."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, cast

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
from vk_topic_bridge.domain.value_objects import TopicInfo
from vk_topic_bridge.presentation.vk.handlers import VkUiDispatcher, VkUiMessage
from vk_topic_bridge.presentation.vk.keyboards import (
    BTN_ADD,
    BTN_ALIASES,
    BTN_BACK,
    BTN_CANCEL,
    BTN_DELETE,
    BTN_HELP,
    BTN_YES,
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

    async def send_user_message(self, user_id: int, text: str, keyboard_json: str | None) -> int:
        self.messages.append((user_id, text, keyboard_json))
        return len(self.messages)

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
        self, vk_user_id: int, topic_id: int | None, alias: str, alias_normalized: str
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


def _msg(text: str, *, fwd: int = 0) -> VkUiMessage:
    return VkUiMessage(
        from_id=USER_ID,
        peer_id=PEER_ID,
        text=text,
        fwd_count=fwd,
        conversation_message_id=333,
        raw={"text": text, "conversation_message_id": 333, "peer_id": PEER_ID},
    )


def _harness(
    *,
    chat_id: int | None = CHAT_ID,
    topics: Sequence[TopicInfo] = (GENERAL, NEWS),
    publisher: FakeManualPublisher | None = None,
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
        source_resolver=cast(Any, make_test_source_resolver()),
    )
    return Harness(dispatcher, send, real_publisher, uow, dispatcher._sessions)


# --- Help ------------------------------------------------------------------


async def test_help_triggers_all_open_same_help() -> None:
    h = _harness()
    for trigger in ("Начать", "Помощь", "Помоги", "Help", "help", " ПОМОГИ "):
        await h.dispatcher.dispatch(_msg(trigger))
    texts = {text for _, text, _ in h.send.messages}
    assert len(texts) == 1
    assert "переслать" in h.send.last_text
    assert h.send.last_keyboard is not None


async def test_help_button_text_opens_help() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg(BTN_HELP))
    assert "переслать" in h.send.last_text


# --- Alias menu ------------------------------------------------------------


async def test_aliases_button_opens_menu_with_topics() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))
    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_MENU
    assert "General" in h.send.last_text
    assert "Новости" in h.send.last_text
    assert h.send.last_keyboard is not None


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


async def test_alias_add_flow_persists_alias() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))
    await h.dispatcher.dispatch(_msg(BTN_ADD))
    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_ADD_WAIT_TOPIC
    await h.dispatcher.dispatch(_msg("2"))
    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_ADD_WAIT_VALUE
    await h.dispatcher.dispatch(_msg("важное"))
    assert "назначен" in h.send.last_text
    assert h.uow.vk_aliases.rows[USER_ID][7] == "важное"
    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_MENU


async def test_alias_add_rejects_alias_with_space() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))
    await h.dispatcher.dispatch(_msg(BTN_ADD))
    await h.dispatcher.dispatch(_msg("1"))
    await h.dispatcher.dispatch(_msg("два слова"))
    assert "не сохранён" in h.send.last_text
    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_ADD_WAIT_VALUE


async def test_alias_delete_requires_confirmation() -> None:
    h = _harness()
    h.uow.vk_aliases.rows[USER_ID] = {7: "важное"}
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))
    await h.dispatcher.dispatch(_msg(BTN_DELETE))
    await h.dispatcher.dispatch(_msg("2"))
    assert h.sessions.get(USER_ID).state is VkUiState.ALIAS_DELETE_CONFIRM
    assert "Удалить алиас" in h.send.last_text
    await h.dispatcher.dispatch(_msg(BTN_YES))
    assert h.uow.vk_aliases.rows[USER_ID] == {}
    assert "удалён" in h.send.last_text


async def test_alias_back_returns_to_help() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg(BTN_ALIASES))
    await h.dispatcher.dispatch(_msg(BTN_BACK))
    assert h.sessions.get(USER_ID).state is VkUiState.IDLE


# --- Manual forwarding ------------------------------------------------------


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
    assert h.sessions.get(USER_ID).state is VkUiState.WAIT_DESTINATION


async def test_ordinal_choice_publishes_without_reaction() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg("", fwd=1))
    await h.dispatcher.dispatch(_msg("2"))
    assert len(h.publisher.calls) == 1
    request = h.publisher.calls[0]
    assert request.destination.message_thread_id == 7
    assert "отправлено" in h.send.last_text
    assert h.sessions.get(USER_ID).state is VkUiState.IDLE


async def test_unknown_alias_shows_error_and_ordinal_list() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg("неттакого", fwd=1))
    assert "Алиас неизвестен" in h.send.last_text
    assert h.sessions.get(USER_ID).state is VkUiState.WAIT_DESTINATION
    assert h.publisher.calls == []


async def test_found_alias_publishes_immediately() -> None:
    h = _harness()
    h.uow.vk_aliases.rows[USER_ID] = {7: "важное"}
    await h.dispatcher.dispatch(_msg("важное", fwd=1))
    assert len(h.publisher.calls) == 1
    assert h.publisher.calls[0].destination.message_thread_id == 7


async def test_stale_alias_never_falls_back_to_general() -> None:
    h = _harness(topics=(GENERAL, STALE))
    h.uow.vk_aliases.rows[USER_ID] = {9: "старое"}
    await h.dispatcher.dispatch(_msg("старое", fwd=1))
    assert "больше недоступен" in h.send.last_text
    assert h.publisher.calls == []
    assert h.sessions.get(USER_ID).state is VkUiState.WAIT_DESTINATION


async def test_multi_message_never_starts_fsm_when_alias_present() -> None:
    h = _harness()
    h.uow.vk_aliases.rows[USER_ID] = {7: "важное"}
    await h.dispatcher.dispatch(_msg("важное", fwd=3))
    assert h.publisher.calls == []
    assert h.sessions.get(USER_ID).state is VkUiState.IDLE


async def test_cancel_in_wait_destination_returns_idle() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg("", fwd=1))
    await h.dispatcher.dispatch(_msg(BTN_CANCEL))
    assert h.sessions.get(USER_ID).state is VkUiState.IDLE
    assert h.publisher.calls == []


async def test_wait_destination_rejects_alias_word() -> None:
    h = _harness()
    h.uow.vk_aliases.rows[USER_ID] = {7: "важное"}
    await h.dispatcher.dispatch(_msg("", fwd=1))
    await h.dispatcher.dispatch(_msg("важное"))
    assert "только номер" in h.send.last_text
    assert h.publisher.calls == []


async def test_config_error_when_unregistered() -> None:
    h = _harness(chat_id=None)
    await h.dispatcher.dispatch(_msg("", fwd=1))
    assert "недоступна" in h.send.last_text
    assert h.sessions.get(USER_ID).state is VkUiState.IDLE


async def test_manual_publication_failure_clears_fsm() -> None:
    h = _harness(publisher=FakeManualPublisher(error=ProvisioningError("topic gone")))
    await h.dispatcher.dispatch(_msg("", fwd=1))
    await h.dispatcher.dispatch(_msg("2"))
    assert h.sessions.get(USER_ID).state is VkUiState.IDLE
    assert "Не удалось" in h.send.last_text  # noqa: RUF001


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
    await h.dispatcher.dispatch(_msg("2"))

    assert h.sessions.get(USER_ID).state is VkUiState.WAIT_DESTINATION
    assert "топик" in h.send.last_text.lower()
    assert "не отправлено" in h.send.last_text.lower()
    assert "1. General" in h.send.last_text
    assert "2. Новости (недоступна)" in h.send.last_text

    publisher.result = ManualPublicationResult(
        published=True,
        message_ids=(2,),
        delivery_id=2,
    )
    await h.dispatcher.dispatch(_msg("1"))

    assert h.sessions.get(USER_ID).state is VkUiState.IDLE
    assert len(publisher.calls) == 2
    assert publisher.calls[1].destination.message_thread_id is None
    assert "отправлено" in h.send.last_text


# --- session isolation -------------------------------------------------------


async def test_two_users_have_independent_sessions() -> None:
    h = _harness()
    await h.dispatcher.dispatch(_msg("", fwd=1))
    other = replace(_msg("", fwd=1), from_id=999, peer_id=999)
    await h.dispatcher.dispatch(other)
    assert h.sessions.get(USER_ID).state is VkUiState.WAIT_DESTINATION
    assert h.sessions.get(999).state is VkUiState.WAIT_DESTINATION
    # cancel for one user does not touch the other
    await h.dispatcher.dispatch(_msg(BTN_CANCEL))
    assert h.sessions.get(USER_ID).state is VkUiState.IDLE
    assert h.sessions.get(999).state is VkUiState.WAIT_DESTINATION


# --- raw consumer seam (VkUiRouter.handle_dm) --------------------------------


def _update(payload: dict[str, object]) -> dict[str, object]:
    return {"type": "message_new", "group_id": 1, "object": payload}


async def test_handle_dm_normalizes_plain_object_payload() -> None:
    h = _harness()
    consumed = await h.dispatcher.handle_dm(
        _update({"peer_id": USER_ID, "from_id": USER_ID, "text": "Помощь"})
    )
    assert consumed is True
    assert "переслать" in h.send.last_text


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
    assert h.sessions.get(USER_ID).state is VkUiState.WAIT_DESTINATION


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
