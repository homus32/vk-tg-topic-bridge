"""Owner-only gate: every update from outside ``OWNER_IDS`` is silently ignored.

The drop is deliberately invisible: no reply, no keyboard, no error message, so the
bot never acknowledges a stranger's existence (US-01 AC-01.1/AC-01.2).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

logger = logging.getLogger(__name__)


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
        owner_id = getattr(from_user, "id", None)
        chat_id = getattr(getattr(event, "chat", None), "id", None)
        if from_user is None or owner_id not in self._owner_ids:
            logger.debug(
                "telegram update rejected: non-owner",
                extra={"owner_id": owner_id, "chat_id": chat_id, "reason": "unauthorized"},
            )
            return None
        route = getattr(handler, "__name__", type(handler).__name__)
        logger.debug(
            "telegram update routed",
            extra={"owner_id": owner_id, "chat_id": chat_id, "route": route},
        )
        result = await handler(event, data)
        logger.debug(
            "telegram update completed",
            extra={"owner_id": owner_id, "chat_id": chat_id, "route": route},
        )
        return result
