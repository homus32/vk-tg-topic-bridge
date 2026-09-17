"""Unit tests for ``SelectDestination``: proof-send gate before persistence (fakes only).

The use case is temporary pre-Stage-7 provisioning; the tests pin the frozen contract that
``telegram_messages_topic_id`` is written only after a real Bot API send returns a positive
message id, and that ``telegram_wall_topic_id`` is never touched.
"""

from dataclasses import dataclass, replace

import pytest

from tests.unit.application.test_port_fakes import (
    FakeBridgeSettingsRepository,
    FakeTelegramAdminPort,
    FakeUnitOfWork,
)
from vk_topic_bridge.application.admin.select_destination import SelectDestination
from vk_topic_bridge.application.errors import ProvisioningError
from vk_topic_bridge.domain.value_objects import TopicInfo

CHAT_ID = -1001234567890
RUN_ID = "gate-topic-run-1"
CONFIRMED_MESSAGE_ID = 555
NEWS_TOPIC = TopicInfo(
    topic_id=7, title="Новости", is_general=False, is_closed=False, is_hidden=False
)


class _AdminFake(FakeTelegramAdminPort):
    def __init__(
        self, message_id: int = CONFIRMED_MESSAGE_ID, failure: Exception | None = None
    ) -> None:
        self._message_id = message_id
        self._failure = failure
        self.calls: list[tuple[int, int | None, str]] = []

    async def send_test_into_topic(
        self, chat_id: int, message_thread_id: int | None, text: str
    ) -> int:
        self.calls.append((chat_id, message_thread_id, text))
        if self._failure is not None:
            raise self._failure
        return self._message_id


@dataclass(frozen=True, slots=True)
class _Harness:
    use_case: SelectDestination
    uow: FakeUnitOfWork
    settings: FakeBridgeSettingsRepository
    admin: _AdminFake


def _build(*, message_id: int = CONFIRMED_MESSAGE_ID, failure: Exception | None = None) -> _Harness:
    uow = FakeUnitOfWork()
    settings = FakeBridgeSettingsRepository()
    uow.bridge_settings = settings
    admin = _AdminFake(message_id=message_id, failure=failure)
    return _Harness(
        use_case=SelectDestination(lambda: uow, admin),
        uow=uow,
        settings=settings,
        admin=admin,
    )


async def test_topic_is_persisted_only_after_positive_test_send() -> None:
    harness = _build()

    message_id = await harness.use_case.execute(CHAT_ID, NEWS_TOPIC, RUN_ID)

    assert message_id == CONFIRMED_MESSAGE_ID
    assert len(harness.admin.calls) == 1
    called_chat_id, called_thread_id, confirmation_text = harness.admin.calls[0]
    assert (called_chat_id, called_thread_id) == (CHAT_ID, NEWS_TOPIC.topic_id)
    assert RUN_ID in confirmation_text
    assert harness.settings.state.telegram_messages_topic_id == NEWS_TOPIC.topic_id
    assert harness.uow.committed is True


async def test_failed_test_send_propagates_and_persists_no_topic() -> None:
    harness = _build(failure=RuntimeError("bot api rejected the test send"))

    with pytest.raises(RuntimeError, match="rejected the test send"):
        await harness.use_case.execute(CHAT_ID, NEWS_TOPIC, RUN_ID)

    assert harness.admin.calls
    assert harness.settings.state.telegram_messages_topic_id is None
    assert harness.uow.committed is False


async def test_non_positive_test_send_message_id_is_a_provisioning_error() -> None:
    harness = _build(message_id=0)

    with pytest.raises(ProvisioningError):
        await harness.use_case.execute(CHAT_ID, NEWS_TOPIC, RUN_ID)

    assert harness.settings.state.telegram_messages_topic_id is None
    assert harness.uow.committed is False


async def test_wall_topic_is_never_touched() -> None:
    harness = _build()
    harness.settings.state = replace(harness.settings.state, telegram_wall_topic_id=99)

    await harness.use_case.execute(CHAT_ID, NEWS_TOPIC, RUN_ID)

    assert harness.settings.state.telegram_wall_topic_id == 99


GENERAL_TOPIC = TopicInfo(
    topic_id=None, title="General", is_general=True, is_closed=False, is_hidden=False
)


async def test_general_topic_is_rejected_before_any_send_or_persistence() -> None:
    harness = _build()

    with pytest.raises(ProvisioningError):
        await harness.use_case.execute(CHAT_ID, GENERAL_TOPIC, RUN_ID)

    assert harness.admin.calls == []
    assert harness.settings.state.telegram_messages_topic_id is None
    assert harness.uow.committed is False
