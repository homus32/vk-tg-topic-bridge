"""Command definitions and scope intents (data only; execution lives in
infrastructure.telegram.command_menu)."""

from __future__ import annotations

from dataclasses import dataclass

from aiogram.types import BotCommand

START_COMMAND = "start"
CANCEL_COMMAND = "cancel"
REGISTER_COMMAND = "register"

START_DESCRIPTION = "Открыть меню и клавиатуру"
CANCEL_DESCRIPTION = "Отменить текущее действие"
REGISTER_DESCRIPTION = "Зарегистрировать этот чат"


def owner_private_commands() -> list[BotCommand]:
    """Commands hinted in an owner's private chat (owner-scoped, not default-scoped)."""
    return [
        BotCommand(command=START_COMMAND, description=START_DESCRIPTION),
        BotCommand(command=CANCEL_COMMAND, description=CANCEL_DESCRIPTION),
    ]


def registration_group_commands() -> list[BotCommand]:
    """Temporary ``BotCommandScopeChatMember`` list while the registration master is active."""
    return [BotCommand(command=REGISTER_COMMAND, description=REGISTER_DESCRIPTION)]


@dataclass(frozen=True, slots=True)
class OwnerCommand:
    """One owner-facing command with its scope intent."""

    command: str
    description: str
    private_scope: bool
    group_registration_scope: bool
