"""DTOs describing VK Long Poll connectivity and Telethon chat access."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LongPollInfo:
    """Long Poll server coordinates returned by the VK handshake."""

    server: str
    key: str
    ts: str
    enabled: bool
    wall_post_new_enabled: bool


@dataclass(frozen=True, slots=True)
class ChatAccessInfo:
    """Telethon view of the registered chat: stable entity id and forum flag."""

    entity_id: int
    is_forum: bool
