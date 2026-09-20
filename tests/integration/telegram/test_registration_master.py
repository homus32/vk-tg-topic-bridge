"""Registration master tests: cross-chat gating, silence rules, owner DM, menu scopes.

Handlers are invoked directly with fakes; no dispatcher session or network is involved.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field, replace
from types import SimpleNamespace
from typing import Any, cast

import pytest
from aiogram.types import (
    ReplyKeyboardMarkup,
)

from vk_topic_bridge.application.admin.register_chat import (
    MissingCapabilitiesError,
    RegisterChatResult,
)
from vk_topic_bridge.application.dto.settings import BridgeSettingsState
from vk_topic_bridge.domain.value_objects import ChatCapabilities, TopicInfo
from vk_topic_bridge.presentation.telegram.registration_session import RegistrationCoordinator
from vk_topic_bridge.presentation.telegram.routers.registration import (
    build_registration_router,
)
from vk_topic_bridge.presentation.telegram.states import RegistrationMaster

CHAT_ID = -1001234567890
CHAT_TITLE = "Тестовый чат"
OWNER_ID = 111
OTHER_OWNER_ID = 222


class FakeFSMContext:
    def __init__(self, state: str | None = None) -> None:
        self._state = state

    async def clear(self) -> None:
        self._state = None

    async def set_state(self, state: object) -> None:
        self._state = getattr(state, "state", str(state))

    async def get_state(self) -> str | None:
        return self._state


@dataclass
class FakeMessage:
    chat_type: str = "supergroup"
    user_id: int = OWNER_ID
    text: str = ""
    fail_answers: bool = False
    answers: list[tuple[str, object | None]] = field(default_factory=list)

    @property
    def chat(self) -> object:
        return SimpleNamespace(id=CHAT_ID, title=CHAT_TITLE, type=self.chat_type)

    @property
    def from_user(self) -> object:
        return SimpleNamespace(id=self.user_id)

    async def answer(self, text: str, **kwargs: object) -> None:
        if self.fail_answers:
            raise AssertionError("group answer must not be used for registration feedback")
        self.answers.append((text, kwargs.get("reply_markup")))


class FakeBot:
    def __init__(self, username: str = "bridge_bot") -> None:
        self._bridge_username = username
        self.sent: list[dict[str, object]] = []

    async def send_message(self, **kwargs: object) -> None:
        self.sent.append(kwargs)

    async def me(self) -> object:
        return SimpleNamespace(username=self._bridge_username)


@dataclass
class FakeRegisterChat:
    result: RegisterChatResult | None = None
    error: Exception | None = None
    calls: list[tuple[int, str | None]] = field(default_factory=list)

    async def execute(self, chat_id: int, title: str | None) -> RegisterChatResult:
        self.calls.append((chat_id, title))
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def _state(**overrides: object) -> BridgeSettingsState:
    base = BridgeSettingsState.defaults()
    return BridgeSettingsState(
        telegram_chat_id=overrides.get("telegram_chat_id"),  # type: ignore[arg-type]
        telegram_chat_title=overrides.get("telegram_chat_title"),  # type: ignore[arg-type]
        auto_forward_all=base.auto_forward_all,
        auto_forward_hashtags=base.auto_forward_hashtags,
        auto_forward_wall=base.auto_forward_wall,
        telegram_messages_topic_id=None,
        telegram_wall_topic_id=None,
    )


def _result() -> RegisterChatResult:
    return RegisterChatResult(
        chat_id=CHAT_ID,
        title=CHAT_TITLE,
        capabilities=ChatCapabilities(
            can_send_text=True,
            can_send_photo=True,
            can_send_video=True,
            can_send_document=True,
            missing=(),
        ),
        topics=[
            TopicInfo(
                topic_id=7, title="Новости", is_general=False, is_closed=False, is_hidden=False
            )
        ],
        ready=True,
    )


def _handler(router: object, name: str) -> Callable[..., Coroutine[Any, Any, None]]:
    handlers = router.message.handlers  # type: ignore[attr-defined]
    for handler in handlers:
        if handler.callback.__name__ == name:
            return cast(Callable[..., Coroutine[Any, Any, None]], handler.callback)
    msg = f"handler {name!r} not found"
    raise AssertionError(msg)


def _router(
    *,
    state: BridgeSettingsState | None,
    register_chat: FakeRegisterChat | None = None,
    bot: FakeBot | None = None,
    menu_sync: object | None = None,
    registration: RegistrationCoordinator | None = None,
    username: str = "bridge_bot",
    fresh_state: BridgeSettingsState | None = None,
) -> tuple[object, FakeBot]:
    holder = {"state": state}

    async def reader() -> BridgeSettingsState | None:
        return holder["state"]

    real_bot = bot or FakeBot(username=username)
    fake_register = register_chat or FakeRegisterChat(result=_result())
    coordinator = registration or RegistrationCoordinator()
    if registration is None:
        assert coordinator.acquire(OWNER_ID)
    original_execute = fake_register.execute

    async def execute(chat_id: int, title: str | None) -> RegisterChatResult:
        result = await original_execute(chat_id, title)
        if fresh_state is not None:
            holder["state"] = fresh_state
        return result

    fake_register.execute = execute  # type: ignore[method-assign]
    router = build_registration_router(
        cast("object", fake_register),  # type: ignore[arg-type]
        reader,
        cast("object", real_bot),  # type: ignore[arg-type]
        menu_sync=menu_sync,
        registration=coordinator,
    )
    return router, real_bot


# --- private /start master ---------------------------------------------------------


async def test_private_start_sets_pending_and_shows_onboarding(
    caplog: pytest.LogCaptureFixture,
) -> None:
    router, _ = _router(state=_state())
    fsm = FakeFSMContext()
    message = FakeMessage(chat_type="private")

    with caplog.at_level(logging.DEBUG):
        await _handler(router, "private_start")(message, fsm)

    assert await fsm.get_state() == RegistrationMaster.pending.state
    text, _ = message.answers[0]
    assert "/register" in text
    assert "Добавьте бота" in text
    assert "telegram registration started" in caplog.text
    assert "telegram registration FSM transition" in caplog.text


async def test_private_start_registered_shows_main_keyboard() -> None:
    registered = BridgeSettingsState(
        telegram_chat_id=CHAT_ID,
        telegram_chat_title=CHAT_TITLE,
        auto_forward_all=True,
        auto_forward_hashtags=True,
        auto_forward_wall=True,
        telegram_messages_topic_id=None,
        telegram_wall_topic_id=None,
    )
    router, _ = _router(state=registered)
    fsm = FakeFSMContext(state=RegistrationMaster.pending.state)
    message = FakeMessage(chat_type="private")

    await _handler(router, "private_start")(message, fsm)

    assert await fsm.get_state() is None
    text, markup = message.answers[0]
    assert CHAT_TITLE in text
    assert isinstance(markup, ReplyKeyboardMarkup)


async def test_registration_master_is_exclusive_to_one_owner() -> None:
    registration = RegistrationCoordinator()
    register = FakeRegisterChat(result=_result())
    router, _ = _router(state=_state(), register_chat=register, registration=registration)
    start_handler = _handler(router, "private_start")
    group_handler = _handler(router, "group_register")

    owner_message = FakeMessage(chat_type="private", user_id=OWNER_ID)
    owner_state = FakeFSMContext()
    await start_handler(owner_message, owner_state)

    other_message = FakeMessage(chat_type="private", user_id=OTHER_OWNER_ID)
    other_state = FakeFSMContext()
    await start_handler(other_message, other_state)

    assert await owner_state.get_state() == RegistrationMaster.pending.state
    assert await other_state.get_state() is None
    assert other_message.answers == []

    other_group_state = FakeFSMContext(state=RegistrationMaster.pending.state)
    await group_handler(FakeMessage(user_id=OTHER_OWNER_ID), other_group_state)

    assert register.calls == []
    assert await other_group_state.get_state() == RegistrationMaster.pending.state


# --- group /register ---------------------------------------------------------------


async def test_register_without_master_is_silently_ignored() -> None:
    register = FakeRegisterChat(result=_result())
    router, bot = _router(state=_state(), register_chat=register)
    fsm = FakeFSMContext()
    message = FakeMessage()

    await _handler(router, "group_register")(message, fsm)

    assert register.calls == []
    assert message.answers == []
    assert bot.sent == []


async def test_register_with_pending_master_registers_and_dms_owner() -> None:
    registered = BridgeSettingsState(
        telegram_chat_id=CHAT_ID,
        telegram_chat_title=CHAT_TITLE,
        auto_forward_all=True,
        auto_forward_hashtags=True,
        auto_forward_wall=True,
        telegram_messages_topic_id=None,
        telegram_wall_topic_id=None,
    )
    register = FakeRegisterChat(result=_result())
    router, bot = _router(state=_state(), register_chat=register, fresh_state=registered)
    fsm = FakeFSMContext(state=RegistrationMaster.pending.state)
    message = FakeMessage()

    await _handler(router, "group_register")(message, fsm)

    assert register.calls == [(CHAT_ID, CHAT_TITLE)]
    assert await fsm.get_state() is None
    assert len(bot.sent) == 1
    assert bot.sent[0]["chat_id"] == OWNER_ID
    markup = bot.sent[0]["reply_markup"]
    assert isinstance(markup, ReplyKeyboardMarkup)


async def test_register_in_already_registered_chat_is_ignored() -> None:
    registered = BridgeSettingsState(
        telegram_chat_id=CHAT_ID,
        telegram_chat_title=CHAT_TITLE,
        auto_forward_all=True,
        auto_forward_hashtags=True,
        auto_forward_wall=True,
        telegram_messages_topic_id=None,
        telegram_wall_topic_id=None,
    )
    register = FakeRegisterChat(result=_result())
    router, bot = _router(state=registered, register_chat=register)
    fsm = FakeFSMContext(state=RegistrationMaster.pending.state)
    message = FakeMessage()

    await _handler(router, "group_register")(message, fsm)

    assert register.calls == []
    assert message.answers == []
    assert bot.sent == []
    assert await fsm.get_state() is None


async def test_register_missing_capabilities_lists_rights_and_keeps_master() -> None:
    register = FakeRegisterChat(error=MissingCapabilitiesError(("can_send_photo",)))
    router, bot = _router(state=_state(), register_chat=register)
    fsm = FakeFSMContext(state=RegistrationMaster.pending.state)
    message = FakeMessage(fail_answers=True)

    await _handler(router, "group_register")(message, fsm)

    assert message.answers == []
    assert len(bot.sent) == 1
    assert bot.sent[0]["chat_id"] == OWNER_ID
    text = str(bot.sent[0]["text"])
    assert "can_send_photo" in text
    assert await fsm.get_state() == RegistrationMaster.pending.state


async def test_registration_ready_false_keeps_master_for_retry() -> None:
    register = FakeRegisterChat(result=replace(_result(), ready=False))
    menu_sync = RecordingMenuSync()
    router, bot = _router(
        state=_state(),
        register_chat=register,
        menu_sync=menu_sync,
        fresh_state=_state(telegram_chat_id=CHAT_ID, telegram_chat_title=CHAT_TITLE),
    )
    fsm = FakeFSMContext(state=RegistrationMaster.pending.state)
    message = FakeMessage()
    handler = _handler(router, "group_register")

    await handler(message, fsm)

    assert await fsm.get_state() == RegistrationMaster.pending.state
    assert menu_sync.cleared == []
    assert len(bot.sent) == 1
    assert "повторите /register" in str(bot.sent[0]["text"]).lower()

    register.result = _result()
    await handler(message, fsm)

    assert await fsm.get_state() is None
    assert register.calls == [(CHAT_ID, CHAT_TITLE), (CHAT_ID, CHAT_TITLE)]
    assert menu_sync.cleared == [(CHAT_ID, OWNER_ID)]


async def test_register_in_private_context_is_ignored_by_filter() -> None:
    register = FakeRegisterChat(result=_result())
    router, _ = _router(state=_state(), register_chat=register)
    fsm = FakeFSMContext(state=RegistrationMaster.pending.state)
    message = FakeMessage(chat_type="private")

    await _handler(router, "group_register")(message, fsm)

    assert register.calls == []


class RecordingMenuSync:
    def __init__(self) -> None:
        self.applied: list[tuple[int, int]] = []
        self.cleared: list[tuple[int, int]] = []

    async def apply_registration_group(self, chat_id: int, owner_id: int) -> None:
        self.applied.append((chat_id, owner_id))

    async def clear_registration_group(self, chat_id: int, owner_id: int) -> None:
        self.cleared.append((chat_id, owner_id))


async def test_register_applies_and_clears_group_scope() -> None:
    registered = BridgeSettingsState(
        telegram_chat_id=CHAT_ID,
        telegram_chat_title=CHAT_TITLE,
        auto_forward_all=True,
        auto_forward_hashtags=True,
        auto_forward_wall=True,
        telegram_messages_topic_id=None,
        telegram_wall_topic_id=None,
    )
    menu_sync = RecordingMenuSync()
    register = FakeRegisterChat(result=_result())
    router, _ = _router(
        state=_state(),
        register_chat=register,
        menu_sync=menu_sync,
        fresh_state=registered,
    )
    fsm = FakeFSMContext(state=RegistrationMaster.pending.state)
    message = FakeMessage()

    await _handler(router, "group_register")(message, fsm)

    assert menu_sync.applied == [(CHAT_ID, OWNER_ID)]
    assert menu_sync.cleared == [(CHAT_ID, OWNER_ID)]


async def test_capability_failure_keeps_group_scope_for_retry() -> None:
    menu_sync = RecordingMenuSync()
    register = FakeRegisterChat(error=MissingCapabilitiesError(("can_send_video",)))
    router, _ = _router(state=_state(), register_chat=register, menu_sync=menu_sync)
    fsm = FakeFSMContext(state=RegistrationMaster.pending.state)
    message = FakeMessage()

    await _handler(router, "group_register")(message, fsm)

    assert menu_sync.applied == [(CHAT_ID, OWNER_ID)]
    assert menu_sync.cleared == []


async def test_directed_filter_accepts_bare_and_this_bot() -> None:
    from vk_topic_bridge.presentation.telegram.filters import DirectedAtThisBotFilter

    bot = FakeBot(username="bridge_bot")
    directed = DirectedAtThisBotFilter(cast("Any", bot))

    assert await directed(FakeMessage(text="/register"))  # type: ignore[arg-type]
    assert await directed(FakeMessage(text="/register@bridge_bot"))  # type: ignore[arg-type]
    assert await directed(FakeMessage(text="/register@Bridge_Bot"))  # type: ignore[arg-type]


async def test_directed_filter_rejects_other_bot_mention() -> None:
    from vk_topic_bridge.presentation.telegram.filters import DirectedAtThisBotFilter

    bot = FakeBot(username="bridge_bot")
    directed = DirectedAtThisBotFilter(cast("Any", bot))

    assert not await directed(FakeMessage(text="/register@other_bot"))  # type: ignore[arg-type]
