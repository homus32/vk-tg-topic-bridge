"""DTOs for mutable bridge settings persisted in the singleton row."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Self


class ToggleKind(StrEnum):
    """Auto-forwarding toggle families."""

    ALL = "all"
    HASHTAGS = "hashtags"
    WALL = "wall"


@dataclass(frozen=True, slots=True)
class BridgeSettingsState:
    """Immutable snapshot of ``bridge_settings``; mutations produce new instances."""

    telegram_chat_id: int | None
    telegram_chat_title: str | None
    auto_forward_all: bool
    auto_forward_hashtags: bool
    auto_forward_wall: bool
    telegram_messages_topic_id: int | None
    telegram_wall_topic_id: int | None

    @classmethod
    def defaults(cls) -> Self:
        """Factory state: all toggles on, chat and destinations unset."""
        return cls(
            telegram_chat_id=None,
            telegram_chat_title=None,
            auto_forward_all=True,
            auto_forward_hashtags=True,
            auto_forward_wall=True,
            telegram_messages_topic_id=None,
            telegram_wall_topic_id=None,
        )
