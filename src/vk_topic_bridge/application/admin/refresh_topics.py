"""Telethon topic discovery for the registered chat — temporary provisioning use case.

An empty topic list is a provisioning error, never a valid empty state: forwarding must
target a topic the owner explicitly selected, and a silent General fallback is invalid
(plan §7, D18). The refresh replaces the persisted topic view in one short transaction.
"""

from collections.abc import Callable

from vk_topic_bridge.application.errors import ProvisioningError
from vk_topic_bridge.application.ports.telegram import TelethonPort
from vk_topic_bridge.application.ports.unit_of_work import UnitOfWork
from vk_topic_bridge.domain.value_objects import TopicInfo


class RefreshTopics:
    """Verifies forum access, discovers topics and atomically replaces the local view."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork], telethon: TelethonPort) -> None:
        self._uow_factory = uow_factory
        self._telethon = telethon

    async def refresh(self, chat_id: int) -> list[TopicInfo]:
        access = await self._telethon.verify_chat_access(chat_id)
        if not access.is_forum:
            raise ProvisioningError(f"chat {chat_id} is not a forum supergroup")

        topics = await self._telethon.list_topics(chat_id)
        if not topics:
            raise ProvisioningError(
                f"chat {chat_id} returned no forum topics; "
                "an empty topic list is a provisioning error"
            )

        async with self._uow_factory() as uow:
            await uow.telegram_topics.replace_all(chat_id, topics)
            await uow.commit()
        return topics
