"""Telegram-facing ports: Bot API publication, admin checks and Telethon discovery."""

from typing import Protocol, runtime_checkable

from vk_topic_bridge.application.dto.infrastructure import ChatAccessInfo
from vk_topic_bridge.domain.value_objects import (
    ChatCapabilities,
    Publication,
    PublicationResult,
    TopicInfo,
)


@runtime_checkable
class TelegramPublisher(Protocol):
    """Bot API publication port.

    ``publish`` raises ``PublicationAmbiguousError`` when the outcome is unknown after
    send intent (timeout/reset/cancel/no response) and ``PublicationRejectedError`` for a
    definitive rejection that created no message. ``send_text`` is used for owner
    notifications and destination confirmation.
    """

    async def publish(self, publication: Publication) -> PublicationResult: ...
    async def send_text(
        self, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> int: ...


@runtime_checkable
class TelegramAdminPort(Protocol):
    """Bot API identity and capability checks used by provisioning use cases."""

    async def get_me(self) -> int: ...
    async def get_chat_capabilities(self, chat_id: int) -> ChatCapabilities: ...
    async def send_test_into_topic(
        self, chat_id: int, message_thread_id: int | None, text: str
    ) -> int: ...


@runtime_checkable
class TelethonPort(Protocol):
    """User-client (Telethon) discovery of chat access and forum topics."""

    async def get_me(self) -> object: ...
    async def is_authorized(self) -> bool: ...
    async def verify_chat_access(self, chat_id: int) -> ChatAccessInfo: ...
    async def list_topics(self, chat_id: int) -> list[TopicInfo]: ...
