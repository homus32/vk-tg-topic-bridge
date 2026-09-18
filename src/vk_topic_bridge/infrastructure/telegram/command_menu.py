"""Telegram command-menu synchronization (hints are UX, never authorization).

Scope policy (frozen draft + Bot API research): default/all-user command lists stay
empty; owner-specific scopes are set only for known owner private chats; a
``BotCommandScopeChatMember`` scope is set for an owner/group pair while the
registration master is active and cleared after success/cancel. Backend owner
authorization (middleware + handlers) remains mandatory and independent.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    BotCommandScopeChatMember,
    BotCommandScopeDefault,
)

from vk_topic_bridge.presentation.telegram.commands import (
    owner_private_commands,
    registration_group_commands,
)

logger = logging.getLogger(__name__)


class CommandMenuSynchronizer:
    """Applies ``setMyCommands``/``deleteMyCommands`` per scope; best-effort only."""

    def __init__(self, bot: Bot, owner_ids: frozenset[int]) -> None:
        self._bot = bot
        self._owner_ids = owner_ids

    async def apply_startup(self) -> None:
        """Clear all-user lists and set owner private scopes; failures are logged only."""
        for scope in (
            BotCommandScopeDefault(),
            BotCommandScopeAllPrivateChats(),
            BotCommandScopeAllGroupChats(),
        ):
            await self._best_effort(
                self._bot.delete_my_commands(scope=scope),
                f"clear commands for {type(scope).__name__}",
            )
        for owner_id in sorted(self._owner_ids):
            await self._best_effort(
                self._bot.set_my_commands(
                    commands=owner_private_commands(),
                    scope=BotCommandScopeChat(chat_id=owner_id),
                ),
                f"set owner private commands for {owner_id}",
            )

    async def apply_registration_group(self, chat_id: int, owner_id: int) -> None:
        """Expose ``/register`` for one owner in one group while the master is active."""
        await self._best_effort(
            self._bot.set_my_commands(
                commands=registration_group_commands(),
                scope=BotCommandScopeChatMember(chat_id=chat_id, user_id=owner_id),
            ),
            f"set registration commands for member {owner_id} in {chat_id}",
        )

    async def clear_registration_group(self, chat_id: int, owner_id: int) -> None:
        """Delete the temporary ChatMember scope after success or cancellation."""
        await self._best_effort(
            self._bot.delete_my_commands(
                scope=BotCommandScopeChatMember(chat_id=chat_id, user_id=owner_id)
            ),
            f"clear registration commands for member {owner_id} in {chat_id}",
        )

    async def _best_effort(self, operation: Awaitable[object], description: str) -> None:
        try:
            await operation
        except TelegramAPIError as exc:
            logger.warning("command menu sync failed (%s): %s", description, exc)
        except Exception as exc:
            logger.warning("command menu sync failed (%s): %s", description, exc)
