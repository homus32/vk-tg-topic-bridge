"""US-02/US-03: precise owner-facing replies for every registration outcome.

The handler is invoked directly with fakes, so no network, dispatcher or aiogram
session is involved; only the observable reply texts are asserted.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from aiogram.types import Message

from vk_topic_bridge.application.admin.register_chat import (
    MissingCapabilitiesError,
    RegisterChatResult,
)
from vk_topic_bridge.application.errors import ProvisioningError
from vk_topic_bridge.domain.value_objects import ChatCapabilities, TopicInfo
from vk_topic_bridge.presentation.telegram.routers.register import handle_register

CHAT_ID = -1001234567890
CHAT_TITLE = "Тестовый чат"


class FakeRegisterChat:
    """RegisterChat-shaped use case: replays one outcome and records calls."""

    def __init__(self, outcome: RegisterChatResult | ProvisioningError) -> None:
        self._outcome = outcome
        self.calls: list[tuple[int, str | None]] = []

    async def execute(self, chat_id: int, title: str | None) -> RegisterChatResult:
        self.calls.append((chat_id, title))
        if isinstance(self._outcome, ProvisioningError):
            raise self._outcome
        return self._outcome


class FakeMessage:
    """Minimal Message stand-in: exposes chat identity and records answers."""

    def __init__(self) -> None:
        self.chat = SimpleNamespace(id=CHAT_ID, title=CHAT_TITLE)
        self.answers: list[str] = []

    async def answer(self, text: str, **kwargs: object) -> None:
        self.answers.append(text)


def _capabilities() -> ChatCapabilities:
    return ChatCapabilities(
        can_send_text=True,
        can_send_photo=True,
        can_send_video=True,
        can_send_document=True,
        missing=(),
    )


def _result(*, ready: bool, topics: list[TopicInfo]) -> RegisterChatResult:
    return RegisterChatResult(
        chat_id=CHAT_ID,
        title=CHAT_TITLE,
        capabilities=_capabilities(),
        topics=topics,
        ready=ready,
    )


def _topics(count: int) -> list[TopicInfo]:
    return [
        TopicInfo(
            topic_id=index,
            title=f"Тема {index}",
            is_general=False,
            is_closed=False,
            is_hidden=False,
        )
        for index in range(1, count + 1)
    ]


async def test_ready_registration_replies_success_once_with_topic_count() -> None:
    message = FakeMessage()
    register_chat = FakeRegisterChat(_result(ready=True, topics=_topics(2)))

    await handle_register(cast(Message, message), register_chat)

    assert len(message.answers) == 1
    reply = message.answers[0]
    assert "зарегистрирован" in reply
    assert "2" in reply
    assert register_chat.calls == [(CHAT_ID, CHAT_TITLE)]


async def test_partial_registration_asks_owner_to_retry() -> None:
    message = FakeMessage()
    register_chat = FakeRegisterChat(_result(ready=False, topics=[]))

    await handle_register(cast(Message, message), register_chat)

    assert len(message.answers) == 1
    assert "повторите" in message.answers[0].lower()
    assert "/register" in message.answers[0]


async def test_missing_capabilities_lists_every_missing_right() -> None:
    message = FakeMessage()
    register_chat = FakeRegisterChat(
        MissingCapabilitiesError(("can_send_video", "can_send_document"))
    )

    await handle_register(cast(Message, message), register_chat)

    assert len(message.answers) == 1
    reply = message.answers[0]
    assert "can_send_video" in reply
    assert "can_send_document" in reply


async def test_generic_provisioning_error_is_reported_without_raising() -> None:
    message = FakeMessage()
    register_chat = FakeRegisterChat(ProvisioningError("telethon is not authorized"))

    await handle_register(cast(Message, message), register_chat)

    assert len(message.answers) == 1
    assert message.answers[0].strip() != ""
