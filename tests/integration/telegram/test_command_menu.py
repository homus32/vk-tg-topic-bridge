"""Command-menu scope tests: scope intents, owner lists, failure isolation."""

from __future__ import annotations

from typing import Any, cast

from aiogram.types import BotCommandScopeChat, BotCommandScopeChatMember

from vk_topic_bridge.infrastructure.telegram.command_menu import CommandMenuSynchronizer
from vk_topic_bridge.presentation.telegram.commands import (
    CANCEL_COMMAND,
    REGISTER_COMMAND,
    START_COMMAND,
    owner_private_commands,
    registration_group_commands,
)

OWNER_ID = 111
OTHER_OWNER_ID = 222
CHAT_ID = -1001234567890


class RecordingBot:
    def __init__(self) -> None:
        self.set_calls: list[dict[str, Any]] = []
        self.delete_calls: list[dict[str, Any]] = []

    async def set_my_commands(self, **kwargs: Any) -> bool:
        self.set_calls.append(kwargs)
        return True

    async def delete_my_commands(self, **kwargs: Any) -> bool:
        self.delete_calls.append(kwargs)
        return True

    async def me(self) -> object:
        from types import SimpleNamespace

        return SimpleNamespace(username="bridge_bot")


async def test_apply_startup_clears_all_scopes_and_sets_owner_scopes() -> None:
    bot = RecordingBot()
    sync = CommandMenuSynchronizer(cast("Any", bot), frozenset({OWNER_ID, OTHER_OWNER_ID}))

    await sync.apply_startup()

    assert len(bot.delete_calls) == 3
    scopes_set = [call["scope"] for call in bot.set_calls]
    assert scopes_set == [
        BotCommandScopeChat(chat_id=OWNER_ID),
        BotCommandScopeChat(chat_id=OTHER_OWNER_ID),
    ]
    names = [command.command for call in bot.set_calls for command in call["commands"]]
    assert names == [START_COMMAND, CANCEL_COMMAND, START_COMMAND, CANCEL_COMMAND]


async def test_owner_private_commands_are_start_and_cancel() -> None:
    names = [command.command for command in owner_private_commands()]
    assert names == [START_COMMAND, CANCEL_COMMAND]


async def test_registration_group_commands_are_register_only() -> None:
    names = [command.command for command in registration_group_commands()]
    assert names == [REGISTER_COMMAND]


async def test_apply_and_clear_registration_group_scope() -> None:
    bot = RecordingBot()
    sync = CommandMenuSynchronizer(cast("Any", bot), frozenset({OWNER_ID}))

    await sync.apply_registration_group(CHAT_ID, OWNER_ID)
    await sync.clear_registration_group(CHAT_ID, OWNER_ID)

    assert bot.set_calls[0]["scope"] == BotCommandScopeChatMember(chat_id=CHAT_ID, user_id=OWNER_ID)
    assert [command.command for command in bot.set_calls[0]["commands"]] == [REGISTER_COMMAND]
    assert bot.delete_calls[0]["scope"] == BotCommandScopeChatMember(
        chat_id=CHAT_ID, user_id=OWNER_ID
    )


async def test_scope_values_do_not_leak_default_scope() -> None:
    bot = RecordingBot()
    sync = CommandMenuSynchronizer(cast("Any", bot), frozenset({OWNER_ID}))

    await sync.apply_startup()

    types_set = {call["scope"].type for call in bot.set_calls}
    assert types_set == {"chat"}
    types_deleted = {call["scope"].type for call in bot.delete_calls}
    assert types_deleted == {"default", "all_private_chats", "all_group_chats"}


async def test_menu_sync_failures_never_raise() -> None:
    class BrokenBot:
        async def set_my_commands(self, **kwargs: object) -> bool:
            raise RuntimeError("bot api down")

        async def delete_my_commands(self, **kwargs: object) -> bool:
            raise RuntimeError("bot api down")

    sync = CommandMenuSynchronizer(cast("Any", BrokenBot()), frozenset({OWNER_ID}))

    await sync.apply_startup()
    await sync.apply_registration_group(CHAT_ID, OWNER_ID)
    await sync.clear_registration_group(CHAT_ID, OWNER_ID)
