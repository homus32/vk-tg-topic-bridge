"""Settings router tests: toggles + broadcast, topics settings, refresh, diagnostics,
change-chat confirmation. Handlers are invoked directly with fakes; no network."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, cast

from aiogram.types import ReplyKeyboardMarkup, ReplyKeyboardRemove

from vk_topic_bridge.application.admin.destination_admin import ChangeChatOutcome
from vk_topic_bridge.application.dto.finish import DeliveryReviewEntry
from vk_topic_bridge.application.dto.settings import (
    BridgeSettingsState,
    ToggleKind,
)
from vk_topic_bridge.application.errors import ProvisioningError
from vk_topic_bridge.domain.value_objects import TopicInfo
from vk_topic_bridge.presentation.telegram import filters as btn
from vk_topic_bridge.presentation.telegram.routers.settings import build_settings_router
from vk_topic_bridge.presentation.telegram.states import (
    ChangeChatConfirm,
    DeliveryDiagnosticsView,
    TopicSettingsView,
)

CHAT_ID = -1001234567890
CHAT_TITLE = "Тестовый чат"
OWNER_ID = 111
OTHER_OWNER_1 = 222
OTHER_OWNER_2 = 333
MESSAGES_TOPIC_ID = 7
WALL_TOPIC_ID = 8

TOPICS = [
    TopicInfo(topic_id=None, title="General", is_general=True, is_closed=False, is_hidden=False),
    TopicInfo(
        topic_id=MESSAGES_TOPIC_ID,
        title="Важные",
        is_general=False,
        is_closed=False,
        is_hidden=False,
    ),
]


class FakeFSMContext:
    def __init__(self, state: str | None = None) -> None:
        self._state = state
        self.data: dict[str, Any] = {}

    async def clear(self) -> None:
        self._state = None
        self.data = {}

    async def set_state(self, state: object) -> None:
        if state is None:
            self._state = None
            return
        self._state = getattr(state, "state", str(state))

    async def get_state(self) -> str | None:
        return self._state

    async def update_data(self, **kwargs: Any) -> None:
        self.data.update(kwargs)

    async def get_data(self) -> dict[str, Any]:
        return dict(self.data)


@dataclass
class FakeMessage:
    text: str = ""
    user_id: int = OWNER_ID
    answers: list[tuple[str, object | None]] = field(default_factory=list)

    @property
    def from_user(self) -> object:
        return SimpleNamespace(id=self.user_id)

    async def answer(self, text: str, **kwargs: object) -> None:
        self.answers.append((text, kwargs.get("reply_markup")))


class RecordingBot:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_message(self, **kwargs: Any) -> None:
        self.sent.append(kwargs)


@dataclass
class FakeToggleUseCase:
    state: BridgeSettingsState
    calls: list[tuple[ToggleKind, bool]] = field(default_factory=list)

    async def execute(self, kind: ToggleKind, value: bool) -> BridgeSettingsState:
        self.calls.append((kind, value))
        field_name = {
            ToggleKind.ALL: "auto_forward_all",
            ToggleKind.HASHTAGS: "auto_forward_hashtags",
            ToggleKind.WALL: "auto_forward_wall",
        }[kind]
        from dataclasses import replace as _replace

        self.state = _replace(self.state, **{field_name: value})
        return self.state


@dataclass
class FakeRefreshUseCase:
    topics: list[TopicInfo] = field(default_factory=lambda: list(TOPICS))
    error: Exception | None = None
    calls: list[int] = field(default_factory=list)

    async def refresh(self, chat_id: int) -> list[TopicInfo]:
        self.calls.append(chat_id)
        if self.error is not None:
            raise self.error
        return list(self.topics)


@dataclass
class FakeResetUseCase:
    outcome: ChangeChatOutcome = field(
        default_factory=lambda: ChangeChatOutcome(chat_cleared=True, aliases_deleted=2)
    )
    calls: int = 0

    async def execute(self) -> ChangeChatOutcome:
        self.calls += 1
        return self.outcome


@dataclass
class FakeDiagnosticsReader:
    entries: list[DeliveryReviewEntry] = field(default_factory=list)
    mark_result: bool = True
    marked: list[int] = field(default_factory=list)
    list_calls: int = 0

    async def list_entries(self) -> list[DeliveryReviewEntry]:
        self.list_calls += 1
        return list(self.entries)

    async def mark_reviewed(self, delivery_id: int) -> bool:
        self.marked.append(delivery_id)
        return self.mark_result


def _entry(**overrides: object) -> DeliveryReviewEntry:
    base = DeliveryReviewEntry(
        delivery_id=41,
        status="ambiguous",
        source_type="message",
        source_key="111:2000000222:333",
        destination_chat_id=CHAT_ID,
        destination_topic_id=MESSAGES_TOPIC_ID,
        attempts=1,
        last_error_code="timeout",
        last_error="read timeout",
        created_at="2026-09-18T10:00:00+00:00",
        ambiguous_at="2026-09-18T10:00:05+00:00",
    )
    from dataclasses import replace as _replace

    return _replace(base, **overrides)  # type: ignore[arg-type]


def _registered(**overrides: object) -> BridgeSettingsState:
    base = BridgeSettingsState(
        telegram_chat_id=CHAT_ID,
        telegram_chat_title=CHAT_TITLE,
        auto_forward_all=True,
        auto_forward_hashtags=True,
        auto_forward_wall=True,
        telegram_messages_topic_id=MESSAGES_TOPIC_ID,
        telegram_wall_topic_id=None,
        telegram_messages_topic_configured=True,
        telegram_wall_topic_configured=False,
    )
    from dataclasses import replace as _replace

    return _replace(base, **overrides)  # type: ignore[arg-type]


@dataclass
class Harness:
    router: object
    bot: RecordingBot
    toggle: FakeToggleUseCase
    refresh: FakeRefreshUseCase
    reset: FakeResetUseCase
    diagnostics: FakeDiagnosticsReader
    state: BridgeSettingsState


def _harness(
    *,
    state: BridgeSettingsState | None = None,
    toggle_state: BridgeSettingsState | None = None,
    refresh: FakeRefreshUseCase | None = None,
    diagnostics: FakeDiagnosticsReader | None = None,
) -> Harness:
    current = state if state is not None else _registered()
    toggle = FakeToggleUseCase(state=toggle_state or current)
    refresh_use_case = refresh or FakeRefreshUseCase()
    reset = FakeResetUseCase()
    diag = diagnostics or FakeDiagnosticsReader()
    bot = RecordingBot()

    async def settings_reader() -> BridgeSettingsState | None:
        return current

    async def topics_reader(_chat_id: int) -> list[TopicInfo]:
        return list(TOPICS)

    router = build_settings_router(
        toggle_use_case=toggle,
        refresh_use_case=refresh_use_case,
        reset_use_case=reset,
        diagnostics_reader=diag,
        settings_reader=settings_reader,
        topics_reader=topics_reader,
        bot=cast("Any", bot),
        owner_ids=frozenset({OWNER_ID, OTHER_OWNER_1, OTHER_OWNER_2}),
    )
    return Harness(
        router=router,
        bot=bot,
        toggle=toggle,
        refresh=refresh_use_case,
        reset=reset,
        diagnostics=diag,
        state=current,
    )


def _handler(router: object, name: str) -> Any:
    handlers = router.message.handlers  # type: ignore[attr-defined]
    for handler in handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    msg = f"handler {name!r} not found"
    raise AssertionError(msg)


# --- toggles -------------------------------------------------------------------------


async def test_toggle_flips_value_and_replies_with_fresh_keyboard() -> None:
    harness = _harness()
    message = FakeMessage(text=btn.TOGGLE_ALL_DISABLE)

    await _handler(harness.router, "toggle_all")(message)

    assert harness.toggle.calls == [(ToggleKind.ALL, False)]
    text, markup = message.answers[0]
    assert "отключена" in text
    assert isinstance(markup, ReplyKeyboardMarkup)
    labels = [button.text for row in markup.keyboard for button in row]
    assert btn.TOGGLE_ALL_ENABLE in labels


async def test_toggle_broadcasts_keyboard_to_other_owners() -> None:
    harness = _harness()
    message = FakeMessage(text=btn.TOGGLE_ALL_DISABLE)

    await _handler(harness.router, "toggle_all")(message)

    recipients = [call["chat_id"] for call in harness.bot.sent]
    assert recipients == [OTHER_OWNER_1, OTHER_OWNER_2]
    for call in harness.bot.sent:
        assert isinstance(call["reply_markup"], ReplyKeyboardMarkup)
        assert "отключена" in call["text"]


async def test_toggle_requires_registered_chat() -> None:
    harness = _harness(state=BridgeSettingsState.defaults(), toggle_state=_registered())
    message = FakeMessage(text=btn.TOGGLE_ALL_DISABLE)

    await _handler(harness.router, "toggle_all")(message)

    assert harness.toggle.calls == []
    text, _ = message.answers[0]
    assert "не зарегистрирован" in text


async def test_toggle_hashtags_and_wall_map_to_their_kinds() -> None:
    harness = _harness()
    message = FakeMessage(text=btn.TOGGLE_HASHTAGS_DISABLE)

    await _handler(harness.router, "toggle_hashtags")(message)
    message_wall = FakeMessage(text=btn.TOGGLE_WALL_DISABLE)
    await _handler(harness.router, "toggle_wall")(message_wall)

    assert harness.toggle.calls == [(ToggleKind.HASHTAGS, False), (ToggleKind.WALL, False)]


# --- topics settings -----------------------------------------------------------------


async def test_topics_settings_lists_named_binding_and_unset_role() -> None:
    harness = _harness()
    message = FakeMessage(text=btn.MENU_TOPICS_SETTINGS)

    await _handler(harness.router, "topics_settings")(message, FakeFSMContext())

    text, markup = message.answers[0]
    assert "Важные" in text
    assert "Сообщения VK-чата" in text
    assert "Посты стены VK" in text
    assert "не настроено" in text
    assert isinstance(markup, ReplyKeyboardMarkup)
    labels = [button.text for row in markup.keyboard for button in row]
    assert labels == [btn.BTN_REFRESH, btn.BTN_BACK]


async def test_topics_settings_back_clears_state_and_returns_to_owner_menu() -> None:
    harness = _harness()
    settings_message = FakeMessage(text=btn.MENU_TOPICS_SETTINGS)
    back_message = FakeMessage(text=btn.BTN_BACK)
    fsm = FakeFSMContext()

    await _handler(harness.router, "topics_settings")(settings_message, fsm)
    assert await fsm.get_state() == TopicSettingsView.view.state

    await _handler(harness.router, "topics_back")(back_message, fsm)

    assert await fsm.get_state() is None
    text, markup = back_message.answers[0]
    assert text == "Возврат в главное меню."
    assert isinstance(markup, ReplyKeyboardMarkup)
    labels = [button.text for row in markup.keyboard for button in row]
    assert btn.MENU_TOPICS_SETTINGS in labels


async def test_topics_settings_shows_general_for_explicit_configuration() -> None:
    harness = _harness(
        state=_registered(
            telegram_messages_topic_id=None,
            telegram_messages_topic_configured=True,
            telegram_wall_topic_id=None,
            telegram_wall_topic_configured=True,
        )
    )
    message = FakeMessage(text=btn.MENU_TOPICS_SETTINGS)

    await _handler(harness.router, "topics_settings")(message, FakeFSMContext())

    text, _ = message.answers[0]
    assert "General" in text
    assert "не настроено" not in text


async def test_refresh_rerenders_and_warns_when_destination_disappeared() -> None:
    refreshed_topics = [
        TopicInfo(topic_id=9, title="Новая", is_general=False, is_closed=False, is_hidden=False)
    ]
    harness = _harness(refresh=FakeRefreshUseCase(topics=refreshed_topics))
    message = FakeMessage(text=btn.BTN_REFRESH)

    await _handler(harness.router, "refresh_topics")(message)

    assert harness.refresh.calls == [CHAT_ID]
    text, _ = message.answers[0]
    assert "больше не найден" in text
    assert str(MESSAGES_TOPIC_ID) in text


async def test_refresh_reports_added_removed_unavailable_and_destinations() -> None:
    refreshed_topics = [
        TopicInfo(
            topic_id=None, title="General", is_general=True, is_closed=False, is_hidden=False
        ),
        TopicInfo(topic_id=9, title="Новая", is_general=False, is_closed=False, is_hidden=False),
        TopicInfo(topic_id=10, title="Скрытая", is_general=False, is_closed=False, is_hidden=True),
    ]
    harness = _harness(refresh=FakeRefreshUseCase(topics=refreshed_topics))
    message = FakeMessage(text=btn.BTN_REFRESH)

    await _handler(harness.router, "refresh_topics")(message)

    text, _ = message.answers[0]
    assert "Добавлены" in text
    assert "Удалены" in text
    assert "Новая" in text
    assert "Скрытая" in text
    assert "Сообщения VK-чата" in text
    assert "Посты стены VK" in text


async def test_refresh_reports_no_changes() -> None:
    harness = _harness(refresh=FakeRefreshUseCase(topics=list(TOPICS)))
    message = FakeMessage(text=btn.BTN_REFRESH)

    await _handler(harness.router, "refresh_topics")(message)

    assert "Изменений нет" in message.answers[0][0]


async def test_refresh_failure_keeps_previous_view_and_reports_error() -> None:
    harness = _harness(refresh=FakeRefreshUseCase(error=ProvisioningError("telethon down")))
    message = FakeMessage(text=btn.BTN_REFRESH)

    await _handler(harness.router, "refresh_topics")(message)

    text, _ = message.answers[0]
    assert "telethon down" in text
    assert "Важные" in text


# --- diagnostics ---------------------------------------------------------------------


async def test_diagnostics_lists_entries_and_sets_state() -> None:
    entry = _entry()
    harness = _harness(diagnostics=FakeDiagnosticsReader(entries=[entry]))
    message = FakeMessage(text=btn.MENU_DELIVERY_DIAGNOSTICS)
    fsm = FakeFSMContext()

    await _handler(harness.router, "diagnostics")(message, fsm)

    assert await fsm.get_state() == DeliveryDiagnosticsView.list_view.state
    text, markup = message.answers[0]
    assert "ambiguous" in text
    assert "ручной проверки" in text
    assert "дубль" in text
    assert str(entry.delivery_id) in text
    assert isinstance(markup, ReplyKeyboardMarkup)


async def test_diagnostics_empty_shows_placeholder() -> None:
    harness = _harness(diagnostics=FakeDiagnosticsReader(entries=[]))
    message = FakeMessage(text=btn.MENU_DELIVERY_DIAGNOSTICS)

    await _handler(harness.router, "diagnostics")(message, FakeFSMContext())

    text, _ = message.answers[0]
    assert "Записей нет" in text


async def test_diagnostics_ordinal_opens_detail_with_retry_warning() -> None:
    harness = _harness(diagnostics=FakeDiagnosticsReader(entries=[_entry()]))
    message = FakeMessage(text="1")
    fsm = FakeFSMContext(state=DeliveryDiagnosticsView.list_view.state)

    await _handler(harness.router, "diag_pick")(message, fsm)

    assert await fsm.get_state() == DeliveryDiagnosticsView.entry_detail.state
    assert (await fsm.get_data())["delivery_id"] == 41
    text, _ = message.answers[0]
    assert "Автоматический повтор запрещён" in text
    assert "timeout" in text


async def test_diagnostics_mark_reviewed_returns_to_list() -> None:
    entry = _entry()
    harness = _harness(diagnostics=FakeDiagnosticsReader(entries=[entry]))
    message = FakeMessage(text=btn.BTN_MARK_REVIEWED)
    fsm = FakeFSMContext(state=DeliveryDiagnosticsView.entry_detail.state)
    await fsm.update_data(delivery_id=41)

    await _handler(harness.router, "diag_mark")(message, fsm)

    assert harness.diagnostics.marked == [41]
    assert await fsm.get_state() == DeliveryDiagnosticsView.list_view.state
    text, _ = message.answers[0]
    assert "отмечена" in text


async def test_diagnostics_mark_rejected_for_non_ambiguous() -> None:
    harness = _harness(diagnostics=FakeDiagnosticsReader(mark_result=False))
    message = FakeMessage(text=btn.BTN_MARK_REVIEWED)
    fsm = FakeFSMContext(state=DeliveryDiagnosticsView.entry_detail.state)
    await fsm.update_data(delivery_id=41)

    await _handler(harness.router, "diag_mark")(message, fsm)

    text, _ = message.answers[0]
    assert "не требует отметки" in text


async def test_diagnostics_back_returns_root_keyboard() -> None:
    harness = _harness()
    message = FakeMessage(text=btn.BTN_BACK)
    fsm = FakeFSMContext(state=DeliveryDiagnosticsView.list_view.state)

    await _handler(harness.router, "diag_back")(message, fsm)

    assert await fsm.get_state() is None
    _, markup = message.answers[0]
    assert isinstance(markup, ReplyKeyboardMarkup)


# --- change chat ---------------------------------------------------------------------


async def test_change_chat_confirmation_then_reset_to_onboarding() -> None:
    harness = _harness()
    prompt = FakeMessage(text=btn.MENU_CHANGE_CHAT)
    fsm = FakeFSMContext()

    await _handler(harness.router, "change_chat")(prompt, fsm)

    assert await fsm.get_state() == ChangeChatConfirm.confirm.state
    text, markup = prompt.answers[0]
    assert "Продолжить?" in text
    assert isinstance(markup, ReplyKeyboardMarkup)

    confirm = FakeMessage(text=btn.BTN_YES)
    await _handler(harness.router, "confirm_yes")(confirm, fsm)

    assert harness.reset.calls == 1
    assert await fsm.get_state() is None
    text, markup = confirm.answers[0]
    assert "не зарегистрирован" in text
    assert isinstance(markup, ReplyKeyboardRemove)


async def test_change_chat_cancel_changes_nothing() -> None:
    harness = _harness()
    message = FakeMessage(text=btn.BTN_CANCEL)
    fsm = FakeFSMContext(state=ChangeChatConfirm.confirm.state)

    await _handler(harness.router, "confirm_cancel")(message, fsm)

    assert harness.reset.calls == 0
    assert await fsm.get_state() is None
    _, markup = message.answers[0]
    assert isinstance(markup, ReplyKeyboardMarkup)
