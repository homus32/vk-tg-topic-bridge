"""US-01: only Telegram users from OWNER_IDS reach the admin bot.

AC-01.1 — an owner's request is handled and answered.
AC-01.2 — a stranger receives no response at all (no reply, no error, no keyboard).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import cast

from aiogram.types import Message, TelegramObject

from vk_topic_bridge.application.dto.settings import BridgeSettingsState
from vk_topic_bridge.presentation.telegram.middlewares import OwnerOnlyMiddleware
from vk_topic_bridge.presentation.telegram.routers.start import ONBOARDING_TEXT, handle_start

OWNER_ID = 111
STRANGER_ID = 999


@dataclass
class FakeMessage:
    """Minimal aiogram Message stand-in recording every reply."""

    user_id: int
    answers: list[str] = field(default_factory=list)

    @property
    def from_user(self) -> object:
        return SimpleNamespace(id=self.user_id)

    async def answer(self, text: str, **kwargs: object) -> None:
        self.answers.append(text)


async def unregistered_settings() -> BridgeSettingsState | None:
    """Bridge state of a fresh install: no chat registered yet."""
    return BridgeSettingsState.defaults()


class StartHandler:
    """Simulates the router dispatch to the real ``/start`` handler."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def __call__(self, event: TelegramObject, data: dict[str, object]) -> object:
        self.calls.append(data)
        await handle_start(cast(Message, event), unregistered_settings)
        return "handled"


async def test_us01_ac011_owner_request_is_handled_and_answered() -> None:
    message = FakeMessage(user_id=OWNER_ID)
    handler = StartHandler()
    middleware = OwnerOnlyMiddleware(frozenset({OWNER_ID}))

    result = await middleware(handler, cast(TelegramObject, message), {})

    assert result == "handled"
    assert len(handler.calls) == 1
    assert message.answers == [ONBOARDING_TEXT]


async def test_us01_ac012_non_owner_receives_no_response() -> None:
    message = FakeMessage(user_id=STRANGER_ID)
    handler = StartHandler()
    middleware = OwnerOnlyMiddleware(frozenset({OWNER_ID}))

    result = await middleware(handler, cast(TelegramObject, message), {})

    assert result is None
    assert handler.calls == []
    assert message.answers == []
