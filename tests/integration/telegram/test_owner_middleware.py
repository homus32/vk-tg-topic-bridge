"""US-01: the owner gate silently drops every non-owner update and never replies."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from aiogram.types import TelegramObject

from vk_topic_bridge.presentation.telegram.middlewares import OwnerOnlyMiddleware

OWNER_ID = 111
STRANGER_ID = 999


class RecordingHandler:
    """Fake wrapped handler: records each call and returns a marker result."""

    def __init__(self) -> None:
        self.calls: list[tuple[TelegramObject, dict[str, object]]] = []

    async def __call__(self, event: TelegramObject, data: dict[str, object]) -> object:
        self.calls.append((event, data))
        return "handled"


def _event(user_id: int | None) -> TelegramObject:
    return cast(TelegramObject, SimpleNamespace(from_user=SimpleNamespace(id=user_id)))


def _event_without_sender() -> TelegramObject:
    return cast(TelegramObject, SimpleNamespace(from_user=None))


async def test_non_owner_event_is_silently_dropped() -> None:
    handler = RecordingHandler()
    middleware = OwnerOnlyMiddleware(frozenset({OWNER_ID}))

    result = await middleware(handler, _event(STRANGER_ID), {})

    assert result is None
    assert len(handler.calls) == 0


async def test_owner_event_reaches_handler() -> None:
    handler = RecordingHandler()
    middleware = OwnerOnlyMiddleware(frozenset({OWNER_ID}))
    event = _event(OWNER_ID)

    result = await middleware(handler, event, {"marker": 1})

    assert result == "handled"
    assert len(handler.calls) == 1
    assert handler.calls[0] == (event, {"marker": 1})


async def test_event_without_sender_is_silently_dropped() -> None:
    handler = RecordingHandler()
    middleware = OwnerOnlyMiddleware(frozenset({OWNER_ID}))

    result = await middleware(handler, _event_without_sender(), {})

    assert result is None
    assert len(handler.calls) == 0
