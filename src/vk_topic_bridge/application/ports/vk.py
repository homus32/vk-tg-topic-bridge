"""VK-facing port: community identity, Long Poll handshake, messages and reactions."""

from typing import Protocol, runtime_checkable

from vk_topic_bridge.application.dto.infrastructure import LongPollInfo
from vk_topic_bridge.domain.value_objects import Author, SourceMessage


@runtime_checkable
class VkGateway(Protocol):
    """All VK calls needed by the forwarding slice, normalized to domain types."""

    async def get_community_id(self) -> int: ...
    async def check_long_poll(self) -> LongPollInfo: ...
    async def get_full_message(
        self, peer_id: int, conversation_message_id: int
    ) -> SourceMessage: ...
    async def get_author(self, user_id: int) -> Author: ...
    async def set_reaction(self, peer_id: int, conversation_message_id: int) -> None: ...
