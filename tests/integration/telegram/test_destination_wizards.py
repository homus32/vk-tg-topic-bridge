"""Destination wizard tests: General selectable, named proof-gated, unavailable rejected.

Handlers are invoked directly with fakes; no network and no real dispatcher involved.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, cast

import pytest
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.types import ReplyKeyboardMarkup

from vk_topic_bridge.application.admin.destination_admin import (
    DestinationConfirmationResult,
)
from vk_topic_bridge.application.dto.settings import BridgeSettingsState
from vk_topic_bridge.application.errors import ProvisioningError
from vk_topic_bridge.domain.value_objects import TopicInfo
from vk_topic_bridge.presentation.telegram import filters as btn
from vk_topic_bridge.presentation.telegram.routers.destinations import build_destinations_router
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

    async def set_state(self, state: object) -> None:
        if state is None:
            self._state = None
            return
        self._state = getattr(state, "state", str(state))

    async def get_state(self) -> str | None:
        return self._state


@dataclass
class FakeMessage:
    text: str = ""
    answers: list[tuple[str, object | None]] = field(default_factory=list)

    async def answer(self, text: str, **kwargs: object) -> None:
        self.answers.append((text, kwargs.get("reply_markup")))


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
) -> Harness:
    current = state if state is not None else _registered()
    topic_list = topics if topics is not None else TOPICS
    use_case = select or FakeSelectDestination(
        result=DestinationConfirmationResult(persisted=True, message_id=555, general_selected=False)
    )

    async def settings_reader() -> BridgeSettingsState | None:
        return current

    async def topics_reader(chat_id: int) -> list[TopicInfo]:
        return list(topic_list)

    router = build_destinations_router(
        cast("Any", use_case),
        settings_reader,
        topics_reader,
        run_id_factory=lambda: RUN_ID,
    )
    return Harness(router=router, select=use_case)


def _handler(router: object, name: str) -> Any:
    handlers = router.message.handlers  # type: ignore[attr-defined]
    for handler in handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    msg = f"handler {name!r} not found"
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
    assert isinstance(markup, ReplyKeyboardMarkup)


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
