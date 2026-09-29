"""Destination wizard tests: General selectable, named proof-gated, unavailable rejected.

Handlers are invoked directly with fakes; no network and no real dispatcher involved.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, cast

import pytest
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

from vk_topic_bridge.application.admin.destination_admin import (
    DestinationConfirmationResult,
)
from vk_topic_bridge.application.dto.settings import BridgeSettingsState
from vk_topic_bridge.application.errors import (
    ProvisioningError,
    PublicationAmbiguousError,
    PublicationRejectedError,
)
from vk_topic_bridge.domain.value_objects import TopicInfo
from vk_topic_bridge.presentation.telegram import filters as btn
from vk_topic_bridge.presentation.telegram.routers.destinations import (
    DestinationCallback,
    build_destinations_router,
)
from vk_topic_bridge.presentation.telegram.states import (
    MessagesDestinationWizard,
    WallDestinationWizard,
)

CHAT_ID = -1001234567890
CHAT_TITLE = "Тестовый чат"
RUN_ID = "dest-run-1"

GENERAL = TopicInfo(
    topic_id=None, title="General", is_general=True, is_closed=False, is_hidden=False
)
VAZHNYE = TopicInfo(topic_id=7, title="Важные", is_general=False, is_closed=False, is_hidden=False)
CLOSED = TopicInfo(topic_id=9, title="Закрытая", is_general=False, is_closed=True, is_hidden=False)

TOPICS = [VAZHNYE, GENERAL, CLOSED]


class FakeFSMContext:
    def __init__(self, state: str | None = None) -> None:
        self._state = state
        self.data: dict[str, object] = {}

    async def set_state(self, state: object) -> None:
        if state is None:
            self._state = None
            return
        self._state = getattr(state, "state", str(state))

    async def get_state(self) -> str | None:
        return self._state

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)

    async def clear(self) -> None:
        self._state = None
        self.data.clear()


@dataclass
class FakeMessage:
    text: str = ""
    answers: list[tuple[str, object | None]] = field(default_factory=list)
    edits: list[tuple[str, object | None]] = field(default_factory=list)

    async def answer(self, text: str, **kwargs: object) -> None:
        self.answers.append((text, kwargs.get("reply_markup")))

    async def edit_text(self, text: str, **kwargs: object) -> None:
        self.edits.append((text, kwargs.get("reply_markup")))


@dataclass
class FakeCallback:
    message: FakeMessage | None
    user_id: int = 111
    answers: list[str | None] = field(default_factory=list)

    @property
    def from_user(self) -> object:
        return type("User", (), {"id": self.user_id})()

    async def answer(self, text: str | None = None, **_: object) -> None:
        self.answers.append(text)


@dataclass
class FakeSelectDestination:
    result: DestinationConfirmationResult | None = None
    error: Exception | None = None
    calls: list[tuple[int, TopicInfo, str, str]] = field(default_factory=list)

    async def execute(
        self, chat_id: int, topic: TopicInfo, kind: str, run_id: str
    ) -> DestinationConfirmationResult:
        self.calls.append((chat_id, topic, kind, run_id))
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


@dataclass
class FakeRefreshTopics:
    topics: list[TopicInfo]
    error: Exception | None = None
    calls: list[int] = field(default_factory=list)

    async def refresh(self, chat_id: int) -> list[TopicInfo]:
        self.calls.append(chat_id)
        if self.error is not None:
            raise self.error
        return list(self.topics)


def _registered(**overrides: object) -> BridgeSettingsState:
    base = BridgeSettingsState(
        telegram_chat_id=CHAT_ID,
        telegram_chat_title=CHAT_TITLE,
        auto_forward_all=True,
        auto_forward_hashtags=True,
        auto_forward_wall=True,
        telegram_messages_topic_id=None,
        telegram_wall_topic_id=None,
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


@dataclass
class Harness:
    router: object
    select: FakeSelectDestination


def _harness(
    *,
    state: BridgeSettingsState | None = None,
    topics: list[TopicInfo] | None = None,
    select: FakeSelectDestination | None = None,
    refresh: FakeRefreshTopics | None = None,
) -> Harness:
    current = state if state is not None else _registered()
    topic_list = topics if topics is not None else TOPICS
    use_case = select or FakeSelectDestination(
        result=DestinationConfirmationResult(persisted=True, message_id=555, general_selected=False)
    )

    async def settings_reader() -> BridgeSettingsState | None:
        return current

    async def topics_reader(_chat_id: int) -> list[TopicInfo]:
        return list(topic_list)

    router = build_destinations_router(
        cast("Any", use_case),
        settings_reader,
        topics_reader,
        run_id_factory=lambda: RUN_ID,
        refresh_use_case=cast("Any", refresh or FakeRefreshTopics(topic_list)),
        owner_ids=frozenset({111}),
    )
    return Harness(router=router, select=use_case)


def _handler(router: object, name: str) -> Any:
    handlers = router.message.handlers  # type: ignore[attr-defined]
    for handler in handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    msg = f"handler {name!r} not found"
    raise AssertionError(msg)


def _callback_handler(router: object, name: str) -> Any:
    handlers = router.callback_query.handlers  # type: ignore[attr-defined]
    for handler in handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    msg = f"callback handler {name!r} not found"
    raise AssertionError(msg)


async def test_messages_wizard_lists_general_first_and_marks_unavailable() -> None:
    harness = _harness()
    message = FakeMessage(text=btn.MENU_MESSAGES_DESTINATION)
    fsm = FakeFSMContext()

    await _handler(harness.router, "messages_destination")(message, fsm)

    assert await fsm.get_state() == MessagesDestinationWizard.wait_ordinal.state
    text, markup = message.answers[0]
    lines = text.splitlines()
    assert lines[2] == "1. General"
    assert any("Важные" in line for line in lines)
    assert any("(недоступна)" in line for line in lines)
    assert isinstance(markup, InlineKeyboardMarkup)


async def test_destination_callback_uses_stable_topic_identity() -> None:
    harness = _harness()
    message = FakeMessage(text=btn.MENU_MESSAGES_DESTINATION)
    fsm = FakeFSMContext()

    await _handler(harness.router, "messages_destination")(message, fsm)

    markup = message.answers[0][1]
    assert isinstance(markup, InlineKeyboardMarkup)
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert len(callbacks) == 2
    assert isinstance(callbacks[0], str)
    assert isinstance(callbacks[1], str)
    assert DestinationCallback.unpack(callbacks[0]).topic_id == -1
    assert DestinationCallback.unpack(callbacks[1]).topic_id == VAZHNYE.topic_id


async def test_destination_callback_selects_general_and_answers_query() -> None:
    select = FakeSelectDestination(
        result=DestinationConfirmationResult(persisted=True, message_id=None, general_selected=True)
    )
    harness = _harness(select=select)
    fsm = FakeFSMContext()
    await _handler(harness.router, "messages_destination")(FakeMessage(), fsm)
    version = cast(int, (await fsm.get_data())["destination_version"])
    callback = FakeCallback(FakeMessage())

    await _callback_handler(harness.router, "messages_callback")(
        callback,
        fsm,
        DestinationCallback(kind="messages", action="select", topic_id=-1, version=version),
    )

    assert select.calls == [(CHAT_ID, GENERAL, "messages", RUN_ID)]
    assert await fsm.get_state() is None
    assert callback.answers == ["Топик выбран."]
    assert callback.message is not None
    assert callback.message.answers == []
    assert len(callback.message.edits) == 1
    edited_text, edited_markup = callback.message.edits[0]
    assert "изменён" in edited_text
    assert "General" in edited_text
    assert isinstance(edited_markup, InlineKeyboardMarkup)
    assert edited_markup.inline_keyboard == []


async def test_stale_destination_callback_is_rejected_without_mutation() -> None:
    harness = _harness()
    fsm = FakeFSMContext()
    await _handler(harness.router, "messages_destination")(FakeMessage(), fsm)
    version = cast(int, (await fsm.get_data())["destination_version"])
    callback = FakeCallback(FakeMessage())

    await _callback_handler(harness.router, "messages_callback")(
        callback,
        fsm,
        DestinationCallback(kind="messages", action="select", topic_id=99, version=version),
    )

    assert harness.select.calls == []
    assert await fsm.get_state() == MessagesDestinationWizard.wait_ordinal.state
    assert callback.answers == ["Топик больше недоступен."]


async def test_wrong_owner_destination_callback_is_ignored() -> None:
    harness = _harness()
    fsm = FakeFSMContext()
    await _handler(harness.router, "messages_destination")(FakeMessage(), fsm)
    version = cast(int, (await fsm.get_data())["destination_version"])
    callback = FakeCallback(FakeMessage(), user_id=999)

    await _callback_handler(harness.router, "messages_callback")(
        callback,
        fsm,
        DestinationCallback(kind="messages", action="select", topic_id=7, version=version),
    )

    assert harness.select.calls == []
    assert callback.answers == []


async def test_destination_callback_double_click_is_idempotent() -> None:
    select = FakeSelectDestination(
        result=DestinationConfirmationResult(persisted=True, message_id=None, general_selected=True)
    )
    harness = _harness(select=select)
    fsm = FakeFSMContext()
    await _handler(harness.router, "messages_destination")(FakeMessage(), fsm)
    version = cast(int, (await fsm.get_data())["destination_version"])
    callback = FakeCallback(FakeMessage())
    callback_data = DestinationCallback(
        kind="messages", action="select", topic_id=-1, version=version
    )

    await _callback_handler(harness.router, "messages_callback")(callback, fsm, callback_data)
    await _callback_handler(harness.router, "messages_callback")(callback, fsm, callback_data)

    assert len(select.calls) == 1
    assert callback.answers == ["Топик выбран.", "Кнопка устарела."]


async def test_destination_callback_cancel_clears_fsm() -> None:
    harness = _harness()
    fsm = FakeFSMContext()
    await _handler(harness.router, "messages_destination")(FakeMessage(), fsm)
    version = cast(int, (await fsm.get_data())["destination_version"])
    callback = FakeCallback(FakeMessage())

    await _callback_handler(harness.router, "messages_callback")(
        callback,
        fsm,
        DestinationCallback(kind="messages", action="cancel", topic_id=-1, version=version),
    )

    assert await fsm.get_state() is None
    assert callback.answers == ["Действие отменено."]


async def test_general_is_selectable_destination() -> None:
    select = FakeSelectDestination(
        result=DestinationConfirmationResult(persisted=True, message_id=None, general_selected=True)
    )
    harness = _harness(select=select)
    fsm = FakeFSMContext(state=MessagesDestinationWizard.wait_ordinal.state)
    message = FakeMessage(text="1")

    await _handler(harness.router, "messages_pick")(message, fsm)

    assert select.calls == [(CHAT_ID, GENERAL, "messages", RUN_ID)]
    assert await fsm.get_state() is None
    text, markup = message.answers[0]
    assert "General" in text
    assert isinstance(markup, ReplyKeyboardMarkup)


async def test_named_topic_pick_persists_via_use_case() -> None:
    select = FakeSelectDestination(
        result=DestinationConfirmationResult(persisted=True, message_id=555, general_selected=False)
    )
    harness = _harness(select=select)
    fsm = FakeFSMContext(state=MessagesDestinationWizard.wait_ordinal.state)
    message = FakeMessage(text="2")

    await _handler(harness.router, "messages_pick")(message, fsm)

    assert select.calls == [(CHAT_ID, VAZHNYE, "messages", RUN_ID)]
    text, _ = message.answers[0]
    assert "Важные" in text


async def test_unavailable_topic_is_rejected_and_list_repeats() -> None:
    harness = _harness()
    fsm = FakeFSMContext(state=MessagesDestinationWizard.wait_ordinal.state)
    message = FakeMessage(text="3")

    await _handler(harness.router, "messages_pick")(message, fsm)

    assert harness.select.calls == []
    text, _ = message.answers[0]
    assert "недоступна" in text
    assert "1. General" in text
    assert await fsm.get_state() == MessagesDestinationWizard.wait_ordinal.state


async def test_invalid_ordinal_repeats_list_without_calling_use_case() -> None:
    harness = _harness()
    fsm = FakeFSMContext(state=MessagesDestinationWizard.wait_ordinal.state)
    message = FakeMessage(text="99")

    await _handler(harness.router, "messages_pick")(message, fsm)

    assert harness.select.calls == []
    text, _ = message.answers[0]
    assert "Неверный номер" in text


async def test_proof_failure_reports_and_persists_nothing() -> None:
    select = FakeSelectDestination(error=ProvisioningError("test send failed"))
    harness = _harness(select=select)
    fsm = FakeFSMContext(state=MessagesDestinationWizard.wait_ordinal.state)
    message = FakeMessage(text="2")

    await _handler(harness.router, "messages_pick")(message, fsm)

    text, _ = message.answers[0]
    assert "test send failed" in text
    assert await fsm.get_state() == MessagesDestinationWizard.wait_ordinal.state


async def test_unexpected_proof_failure_reports_and_keeps_wizard_active() -> None:
    select = FakeSelectDestination(error=RuntimeError("unexpected proof failure"))
    harness = _harness(select=select)
    fsm = FakeFSMContext(state=MessagesDestinationWizard.wait_ordinal.state)
    message = FakeMessage(text="2")

    await _handler(harness.router, "messages_pick")(message, fsm)

    text, _ = message.answers[0]
    assert "Не удалось подтвердить топик" in text
    assert "Повторите попытку" in text
    assert await fsm.get_state() == MessagesDestinationWizard.wait_ordinal.state


async def test_stale_topic_recovers_refreshes_list_and_keeps_wizard_active() -> None:
    stale = TopicInfo(
        topic_id=11, title="Удалённая", is_general=False, is_closed=False, is_hidden=False
    )
    refreshed = [GENERAL, VAZHNYE]
    select = FakeSelectDestination(
        error=PublicationRejectedError(
            "Bad Request: message thread not found", code="telegram_topic_not_found"
        )
    )
    refresh = FakeRefreshTopics(refreshed)
    harness = _harness(topics=[GENERAL, stale], select=select, refresh=refresh)
    fsm = FakeFSMContext(state=MessagesDestinationWizard.wait_ordinal.state)
    message = FakeMessage(text="2")

    await _handler(harness.router, "messages_pick")(message, fsm)

    assert refresh.calls == [CHAT_ID]
    assert await fsm.get_state() == MessagesDestinationWizard.wait_ordinal.state
    text, _ = message.answers[0]
    assert "больше недоступен" in text
    assert "2. Удалённая" not in text
    assert "Важные" in text


async def test_stale_topic_refresh_failure_keeps_cached_selection_recoverable() -> None:
    stale = TopicInfo(
        topic_id=11, title="Удалённая", is_general=False, is_closed=False, is_hidden=False
    )
    select = FakeSelectDestination(
        error=PublicationRejectedError(
            "Bad Request: message thread not found", code="telegram_topic_not_found"
        )
    )
    refresh = FakeRefreshTopics([GENERAL], error=RuntimeError("telethon unavailable"))
    harness = _harness(topics=[GENERAL, stale], select=select, refresh=refresh)
    fsm = FakeFSMContext(state=MessagesDestinationWizard.wait_ordinal.state)
    message = FakeMessage(text="2")

    await _handler(harness.router, "messages_pick")(message, fsm)

    assert await fsm.get_state() == MessagesDestinationWizard.wait_ordinal.state
    text, _ = message.answers[0]
    assert "не удалось обновить" in text


async def test_transient_proof_failure_does_not_trigger_stale_refresh() -> None:
    select = FakeSelectDestination(
        error=PublicationAmbiguousError("network timeout", code="bot_api_network")
    )
    refresh = FakeRefreshTopics([GENERAL, VAZHNYE])
    harness = _harness(select=select, refresh=refresh)
    fsm = FakeFSMContext(state=MessagesDestinationWizard.wait_ordinal.state)
    message = FakeMessage(text="2")

    await _handler(harness.router, "messages_pick")(message, fsm)

    assert refresh.calls == []
    assert await fsm.get_state() == MessagesDestinationWizard.wait_ordinal.state
    assert "telegram не подтвердил" in message.answers[0][0].lower()


async def test_general_can_be_selected_after_stale_topic_recovery() -> None:
    stale = TopicInfo(
        topic_id=11, title="Удалённая", is_general=False, is_closed=False, is_hidden=False
    )
    cached_topics = [GENERAL, stale]
    select = FakeSelectDestination(
        result=DestinationConfirmationResult(persisted=True, message_id=555, general_selected=True),
        error=PublicationRejectedError(
            "Bad Request: message thread not found", code="telegram_topic_not_found"
        ),
    )
    refresh = FakeRefreshTopics([GENERAL, VAZHNYE])
    harness = _harness(topics=cached_topics, select=select, refresh=refresh)
    fsm = FakeFSMContext(state=MessagesDestinationWizard.wait_ordinal.state)
    stale_message = FakeMessage(text="2")

    await _handler(harness.router, "messages_pick")(stale_message, fsm)

    cached_topics[:] = [GENERAL, VAZHNYE]
    select.error = None
    message = FakeMessage(text="1")

    await _handler(harness.router, "messages_pick")(message, fsm)

    assert await fsm.get_state() is None
    assert select.calls == [
        (CHAT_ID, stale, "messages", RUN_ID),
        (CHAT_ID, GENERAL, "messages", RUN_ID),
    ]


async def test_named_topic_can_be_selected_after_stale_topic_recovery() -> None:
    stale = TopicInfo(
        topic_id=11, title="Удалённая", is_general=False, is_closed=False, is_hidden=False
    )
    cached_topics = [GENERAL, stale]
    select = FakeSelectDestination(
        result=DestinationConfirmationResult(
            persisted=True, message_id=556, general_selected=False
        ),
        error=PublicationRejectedError(
            "Bad Request: message thread not found", code="telegram_topic_not_found"
        ),
    )
    refresh = FakeRefreshTopics([GENERAL, VAZHNYE])
    harness = _harness(topics=cached_topics, select=select, refresh=refresh)
    fsm = FakeFSMContext(state=MessagesDestinationWizard.wait_ordinal.state)
    stale_message = FakeMessage(text="2")

    await _handler(harness.router, "messages_pick")(stale_message, fsm)

    cached_topics[:] = [GENERAL, VAZHNYE]
    select.error = None
    message = FakeMessage(text="2")

    await _handler(harness.router, "messages_pick")(message, fsm)

    assert await fsm.get_state() is None
    assert select.calls == [
        (CHAT_ID, stale, "messages", RUN_ID),
        (CHAT_ID, VAZHNYE, "messages", RUN_ID),
    ]


async def test_wall_wizard_separate_state_and_kind() -> None:
    select = FakeSelectDestination(
        result=DestinationConfirmationResult(persisted=True, message_id=556, general_selected=False)
    )
    harness = _harness(select=select)
    message = FakeMessage(text=btn.MENU_WALL_DESTINATION)
    fsm = FakeFSMContext()

    await _handler(harness.router, "wall_destination")(message, fsm)

    assert await fsm.get_state() == WallDestinationWizard.wait_ordinal.state

    pick = FakeMessage(text="2")
    await _handler(harness.router, "wall_pick")(pick, fsm)

    assert select.calls == [(CHAT_ID, VAZHNYE, "wall", RUN_ID)]
    text, _ = pick.answers[0]
    assert "постов стены" in text


async def test_messages_pick_ignored_outside_wizard_state() -> None:
    harness = _harness()
    fsm = FakeFSMContext(state=None)
    message = FakeMessage(text="1")

    with pytest.raises(SkipHandler):
        await _handler(harness.router, "messages_pick")(message, fsm)

    assert harness.select.calls == []
    assert message.answers == []


async def test_wizard_cancel_returns_main_keyboard() -> None:
    harness = _harness()
    fsm = FakeFSMContext(state=MessagesDestinationWizard.wait_ordinal.state)
    message = FakeMessage(text=btn.BTN_CANCEL)

    await _handler(harness.router, "wizard_cancel")(message, fsm)

    assert await fsm.get_state() is None
    text, markup = message.answers[0]
    assert "отменено" in text.lower()
    assert isinstance(markup, ReplyKeyboardMarkup)


async def test_wizard_cancel_outside_wizard_is_ignored() -> None:
    harness = _harness()
    fsm = FakeFSMContext(state=ChangeChatPlaceholderState)
    message = FakeMessage(text=btn.BTN_CANCEL)

    with pytest.raises(SkipHandler):
        await _handler(harness.router, "wizard_cancel")(message, fsm)

    assert message.answers == []


ChangeChatPlaceholderState = "ChangeChatConfirm:confirm"
