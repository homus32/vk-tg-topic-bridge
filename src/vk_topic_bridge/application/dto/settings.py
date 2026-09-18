"""DTOs for mutable bridge settings persisted in the singleton row."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Self


class ToggleKind(StrEnum):
    """Auto-forwarding toggle families."""

    ALL = "all"
    HASHTAGS = "hashtags"
    WALL = "wall"


class DestinationKind(StrEnum):
    """Three-state destination selector derived from (configured flag, nullable id).

    Draft contract (no sentinel ids): ``UNSET`` = configured False + topic id NULL;
    ``GENERAL`` = explicit configured General (configured True + topic id NULL);
    ``NAMED_TOPIC`` = configured True + concrete topic id. The finish migration 0002
    adds the ``telegram_*_topic_configured`` boolean columns; accessors on
    ``BridgeSettingsState`` derive this kind from the persisted pair.
    """

    UNSET = "unset"
    GENERAL = "general"
    NAMED_TOPIC = "named_topic"


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
    telegram_messages_topic_configured: bool = False
    telegram_wall_topic_configured: bool = False

    def messages_destination_kind(self) -> DestinationKind:
        return _destination_kind(
            self.telegram_messages_topic_configured, self.telegram_messages_topic_id
        )

    def wall_destination_kind(self) -> DestinationKind:
        return _destination_kind(self.telegram_wall_topic_configured, self.telegram_wall_topic_id)

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


def _destination_kind(configured: bool, topic_id: int | None) -> DestinationKind:
    if not configured:
        return DestinationKind.UNSET
    return DestinationKind.GENERAL if topic_id is None else DestinationKind.NAMED_TOPIC
