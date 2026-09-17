"""Owner-only gate: every update from outside ``OWNER_IDS`` is silently ignored.

The drop is deliberately invisible: no reply, no keyboard, no error message, so the
bot never acknowledges a stranger's existence (US-01 AC-01.1/AC-01.2).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject


class OwnerOnlyMiddleware(BaseMiddleware):
    """Passes an event to the wrapped handler only when its sender is an owner."""

    def __init__(self, owner_ids: frozenset[int]) -> None:
        self._owner_ids = owner_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, object]], Awaitable[object]],
        event: TelegramObject,
        data: dict[str, object],
    ) -> object:
        from_user = getattr(event, "from_user", None)
        if from_user is None or getattr(from_user, "id", None) not in self._owner_ids:
            return None
        return await handler(event, data)
