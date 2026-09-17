"""Unit tests for ``RegisterChat``: capability gate, persistence, partial success."""

import logging
from dataclasses import dataclass

import pytest

from tests.unit.application.test_port_fakes import (
    FakeBridgeSettingsRepository,
    FakeTelegramAdminPort,
    FakeTelegramTopicsRepository,
    FakeTelethonPort,
    FakeUnitOfWork,
)
from vk_topic_bridge.application.admin.refresh_topics import RefreshTopics
from vk_topic_bridge.application.admin.register_chat import (
    MissingCapabilitiesError,
    RegisterChat,
)
from vk_topic_bridge.application.dto.settings import BridgeSettingsState
from vk_topic_bridge.application.errors import ProvisioningError
from vk_topic_bridge.domain.value_objects import ChatCapabilities, TopicInfo

CHAT_ID = -1001234567890
CHAT_TITLE = "Тестовый чат"
NEWS_TOPIC = TopicInfo(
    topic_id=7, title="Новости", is_general=False, is_closed=False, is_hidden=False
)

FULL_CAPABILITIES = ChatCapabilities(
    can_send_text=True,
    can_send_photo=True,
    can_send_video=True,
    can_send_document=True,
    missing=(),
)

CAPABILITIES_WITH_HOLES = ChatCapabilities(
    can_send_text=True,
    can_send_photo=True,
    can_send_video=False,
    can_send_document=False,
    missing=("can_send_video", "can_send_document"),
)


class _AdminFake(FakeTelegramAdminPort):
    def __init__(self, capabilities: ChatCapabilities) -> None:
        self._capabilities = capabilities

    async def get_chat_capabilities(self, chat_id: int) -> ChatCapabilities:
        return self._capabilities


class _TelethonFake(FakeTelethonPort):
    def __init__(self, topics: list[TopicInfo]) -> None:
        self._topics = topics

    async def list_topics(self, chat_id: int) -> list[TopicInfo]:
        return list(self._topics)


@dataclass(frozen=True, slots=True)
class _Harness:
    use_case: RegisterChat
    uow: FakeUnitOfWork
    settings: FakeBridgeSettingsRepository
    topics: FakeTelegramTopicsRepository


def _build(capabilities: ChatCapabilities, topics: list[TopicInfo]) -> _Harness:
    uow = FakeUnitOfWork()
    settings = FakeBridgeSettingsRepository()
    topics_repo = FakeTelegramTopicsRepository()
    uow.bridge_settings = settings
    uow.telegram_topics = topics_repo
    refresh = RefreshTopics(lambda: uow, _TelethonFake(topics))
    return _Harness(
        use_case=RegisterChat(lambda: uow, _AdminFake(capabilities), refresh),
        uow=uow,
        settings=settings,
        topics=topics_repo,
    )


async def test_register_persists_chat_and_refreshed_topics() -> None:
    harness = _build(FULL_CAPABILITIES, [NEWS_TOPIC])

    result = await harness.use_case.execute(CHAT_ID, CHAT_TITLE)

    assert result.chat_id == CHAT_ID
    assert result.title == CHAT_TITLE
    assert result.capabilities == FULL_CAPABILITIES
    assert result.topics == [NEWS_TOPIC]
    assert result.ready is True
    assert harness.settings.state.telegram_chat_id == CHAT_ID
    assert harness.settings.state.telegram_chat_title == CHAT_TITLE
    assert harness.topics.by_chat[CHAT_ID] == [NEWS_TOPIC]
    assert harness.uow.committed is True


async def test_register_lists_every_missing_capability_and_persists_nothing() -> None:
    harness = _build(CAPABILITIES_WITH_HOLES, [NEWS_TOPIC])

    with pytest.raises(MissingCapabilitiesError) as excinfo:
        await harness.use_case.execute(CHAT_ID, CHAT_TITLE)

    assert isinstance(excinfo.value, ProvisioningError)
    assert excinfo.value.missing == ("can_send_video", "can_send_document")
    assert "can_send_video" in str(excinfo.value)
    assert "can_send_document" in str(excinfo.value)
    assert harness.settings.state == BridgeSettingsState.defaults()
    assert harness.topics.by_chat == {}
    assert harness.uow.committed is False


class _RecordSpy(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


async def test_register_keeps_chat_when_topic_refresh_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _build(FULL_CAPABILITIES, [])
    module_logger = logging.getLogger("vk_topic_bridge.application.admin.register_chat")
    spy = _RecordSpy()
    module_logger.addHandler(spy)
    # `migrations/env.py` runs `fileConfig`, whose `disable_existing_loggers=True` can
    # disable this collection-time logger once DB integration tests run in the same session.
    monkeypatch.setattr(module_logger, "disabled", False)
    monkeypatch.setattr(module_logger, "level", logging.WARNING)
    try:
        result = await harness.use_case.execute(CHAT_ID, CHAT_TITLE)
    finally:
        module_logger.removeHandler(spy)

    assert result.ready is False
    assert result.topics == []
    assert harness.settings.state.telegram_chat_id == CHAT_ID
    assert harness.uow.committed is True
    assert len(spy.records) == 1
    assert spy.records[0].levelno == logging.WARNING
    assert getattr(spy.records[0], "chat_id", None) == CHAT_ID


async def test_register_does_not_require_can_manage_topics() -> None:
    # ChatCapabilities has no can_manage_topics field: registration only requires the
    # publication capabilities, so a clean missing list must succeed (D21).
    harness = _build(FULL_CAPABILITIES, [NEWS_TOPIC])

    result = await harness.use_case.execute(CHAT_ID, CHAT_TITLE)

    assert result.ready is True
    assert result.capabilities.missing == ()
