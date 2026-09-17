"""US-02: Telegram chat registration.

AC-02.1 — ``/start`` before registration instructs the owner to add the bot and run
the registration command inside the target chat.
AC-02.2 — a successful registration inside an allowed chat persists the chat.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import cast

from aiogram.types import Message

from tests.acceptance._fakes import CHAT_ID, CHAT_TITLE, make_registration_harness
from vk_topic_bridge.application.dto.settings import BridgeSettingsState
from vk_topic_bridge.presentation.telegram.routers.register import handle_register
from vk_topic_bridge.presentation.telegram.routers.start import ONBOARDING_TEXT, handle_start


@dataclass
class FakeMessage:
    """Minimal aiogram Message stand-in for the target chat, recording replies."""

    answers: list[str] = field(default_factory=list)
    reply_markups: list[object] = field(default_factory=list)
    chat: object = field(default_factory=lambda: SimpleNamespace(id=CHAT_ID, title=CHAT_TITLE))

    async def answer(self, text: str, **kwargs: object) -> None:
        self.answers.append(text)
        if "reply_markup" in kwargs:
            self.reply_markups.append(kwargs["reply_markup"])


async def missing_chat_settings() -> BridgeSettingsState | None:
    """Nothing registered yet: the chat id is absent from the persisted state."""
    return BridgeSettingsState.defaults()


async def test_us02_ac021_start_instructs_before_registration() -> None:
    message = FakeMessage()

    await handle_start(cast(Message, message), missing_chat_settings)

    assert message.answers == [ONBOARDING_TEXT]
    reply = message.answers[0]
    assert "Добавьте бота" in reply
    assert "/register" in reply
    assert "внутри этого чата" in reply


async def test_us02_ac022_registration_persists_the_chat() -> None:
    harness = make_registration_harness()
    message = FakeMessage()

    await handle_register(cast(Message, message), harness.use_case)

    persisted = await harness.settings.get()
    assert persisted is not None
    assert persisted.telegram_chat_id == CHAT_ID
    assert persisted.telegram_chat_title == CHAT_TITLE
    assert len(message.answers) == 1
    assert "зарегистрирован" in message.answers[0]
    assert harness.uow.commits >= 1
