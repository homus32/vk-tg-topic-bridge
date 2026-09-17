"""Temporary pre-Stage-7 destination selection commands: list topics and confirm by send.

The handler is invoked directly with fakes; only observable reply texts and use-case calls
are asserted. The proof-send gate itself lives in ``SelectDestination`` and is covered by
its own unit tests; here we pin the index-to-topic mapping and the guard rails.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from aiogram.types import Message

from vk_topic_bridge.domain.value_objects import TopicInfo
from vk_topic_bridge.presentation.telegram.routers.destination import (
    handle_set_topic,
    handle_topics,
)

CHAT_ID = -1001234567890
RUN_ID = "20260918T101010-deadbeef"
TOPICS = [
    TopicInfo(topic_id=1, title="General", is_general=True, is_closed=False, is_hidden=False),
    TopicInfo(topic_id=7, title="Новости", is_general=False, is_closed=False, is_hidden=False),
    TopicInfo(topic_id=9, title="Важное", is_general=False, is_closed=False, is_hidden=False),
]


class FakeMessage:
    """Minimal Message stand-in: exposes chat identity, text and records answers."""

    def __init__(self, text: str = "", chat_type: str = "supergroup") -> None:
        self.text = text
        self.chat = SimpleNamespace(id=CHAT_ID, title="Тестовый чат", type=chat_type)
        self.answers: list[str] = []

    async def answer(self, text: str, **kwargs: object) -> None:
        self.answers.append(text)


class FakeSelection:
    """SelectDestination-shaped use case: records calls and replays one outcome."""

    def __init__(self, message_id: int = 555, failure: Exception | None = None) -> None:
        self._message_id = message_id
        self._failure = failure
        self.calls: list[tuple[int, TopicInfo, str]] = []

    async def execute(self, chat_id: int, topic: TopicInfo, run_id: str) -> int:
        self.calls.append((chat_id, topic, run_id))
        if self._failure is not None:
            raise self._failure
        return self._message_id


async def _topics_reader(_chat_id: int) -> list[TopicInfo]:
    return list(TOPICS)


async def test_topics_lists_index_title_and_stable_id_in_order() -> None:
    message = FakeMessage()

    await handle_topics(cast(Message, message), _topics_reader)

    assert len(message.answers) == 1
    reply = message.answers[0]
    assert "1. General" in reply
    assert "2. Новости" in reply
    assert "3. Важное" in reply
    assert "id: 7" in reply
    assert "/set_topic" in reply


async def test_topics_with_no_persisted_topics_points_back_to_register() -> None:
    message = FakeMessage()

    async def empty_reader(_chat_id: int) -> list[TopicInfo]:
        return []

    await handle_topics(cast(Message, message), empty_reader)

    assert len(message.answers) == 1
    assert "/register" in message.answers[0]


async def test_set_topic_maps_ordinal_to_second_topic_and_passes_run_id() -> None:
    message = FakeMessage(text="/set_topic 2")
    selection = FakeSelection()

    await handle_set_topic(
        cast(Message, message),
        selection,
        _topics_reader,
        run_id_factory=lambda: RUN_ID,
    )

    assert len(selection.calls) == 1
    called_chat_id, called_topic, called_run_id = selection.calls[0]
    assert called_chat_id == CHAT_ID
    assert called_topic == TOPICS[1]
    assert called_run_id == RUN_ID
    assert message.answers
    assert "Новости" in message.answers[0]


async def test_set_topic_without_argument_reports_usage_and_calls_nothing() -> None:
    message = FakeMessage(text="/set_topic")
    selection = FakeSelection()

    await handle_set_topic(
        cast(Message, message),
        selection,
        _topics_reader,
        run_id_factory=lambda: RUN_ID,
    )

    assert selection.calls == []
    assert len(message.answers) == 1
    assert "/set_topic" in message.answers[0]


async def test_set_topic_out_of_range_reports_and_calls_nothing() -> None:
    message = FakeMessage(text="/set_topic 99")
    selection = FakeSelection()

    await handle_set_topic(
        cast(Message, message),
        selection,
        _topics_reader,
        run_id_factory=lambda: RUN_ID,
    )

    assert selection.calls == []
    assert len(message.answers) == 1
    assert "99" in message.answers[0]


async def test_set_topic_failure_reports_without_claiming_success() -> None:
    message = FakeMessage(text="/set_topic 2")
    selection = FakeSelection(failure=RuntimeError("bot api rejected the send"))

    await handle_set_topic(
        cast(Message, message),
        selection,
        _topics_reader,
        run_id_factory=lambda: RUN_ID,
    )

    assert len(message.answers) == 1
    assert "не" in message.answers[0].lower()
    assert "зарегистрирован" not in message.answers[0].lower()


async def test_destination_commands_reject_private_chat() -> None:
    message = FakeMessage(text="/topics", chat_type="private")
    selection = FakeSelection()

    await handle_topics(cast(Message, message), _topics_reader)
    await handle_set_topic(
        cast(Message, message),
        selection,
        _topics_reader,
        run_id_factory=lambda: RUN_ID,
    )

    assert selection.calls == []
    assert len(message.answers) == 2
    assert all("целевом чате" in answer for answer in message.answers)


async def _router_command_names() -> set[str]:
    from vk_topic_bridge.presentation.telegram.routers.destination import (
        DestinationSelector,
        build_destination_router,
    )

    async def reader(_chat_id: int) -> list[TopicInfo]:
        return list(TOPICS)

    router = build_destination_router(cast(DestinationSelector, FakeSelection()), reader)
    names: set[str] = set()
    for handler in router.message.handlers:
        for filter_ in handler.filters or ():
            command = getattr(getattr(filter_, "callback", None), "commands", None)
            if command:
                names.update(command)
    return names


async def test_destination_router_registers_both_commands() -> None:
    assert await _router_command_names() == {"topics", "set_topic"}
