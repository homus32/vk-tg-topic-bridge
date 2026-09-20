"""Admin use cases completing the Telegram Admin UI surface."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from vk_topic_bridge.application.errors import ProvisioningError
from vk_topic_bridge.application.ports.telegram import TelegramAdminPort, TelethonPort
from vk_topic_bridge.application.ports.unit_of_work import UnitOfWork
from vk_topic_bridge.domain.value_objects import TopicInfo

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DestinationConfirmationResult:
    """Outcome of a proof-gated destination selection including General."""

    persisted: bool
    message_id: int | None
    general_selected: bool


class SelectDestinationV2:
    """Proof-gated selection of the messages or wall destination, General allowed.

    Three-state contract: ``(configured=False, NULL)`` = unset, ``(configured=True,
    NULL)`` = explicit General, ``(configured=True, N)`` = named topic; no sentinel ids.
    A named topic is proof-sent first; General has no thread id and is persisted
    directly.
    """

    def __init__(self, uow_factory: Callable[[], UnitOfWork], admin: TelegramAdminPort) -> None:
        self._uow_factory = uow_factory
        self._admin = admin

    async def execute(
        self, chat_id: int, topic: TopicInfo, kind: str, run_id: str
    ) -> DestinationConfirmationResult:
        if kind not in ("messages", "wall"):
            raise ProvisioningError(f"unknown destination kind {kind!r}")
        general_selected = topic.is_general and topic.topic_id is None
        message_id: int | None = None
        if not general_selected:
            if topic.topic_id is None:
                raise ProvisioningError(
                    f"topic {topic.title!r} has no thread id and is not marked as General"
                )
            confirmation_text = f"destination check for run {run_id} (topic {topic.topic_id!r})"
            message_id = await self._admin.send_test_into_topic(
                chat_id, topic.topic_id, confirmation_text
            )
            if message_id <= 0:
                raise ProvisioningError(
                    f"test send into chat {chat_id} topic {topic.topic_id!r} returned no message id"
                )

        async with self._uow_factory() as uow:
            if kind == "messages":
                await uow.bridge_settings.set_messages_topic(topic.topic_id)
            else:
                await uow.bridge_settings.set_wall_topic(topic.topic_id)
            await uow.commit()
        logger.info(
            "telegram destination changed",
            extra={
                "chat_id": chat_id,
                "destination_topic_id": topic.topic_id,
                "operation": kind,
                "outcome": "general" if general_selected else "named_topic",
            },
        )
        return DestinationConfirmationResult(
            persisted=True,
            message_id=message_id,
            general_selected=general_selected,
        )


@dataclass(frozen=True, slots=True)
class ChangeChatOutcome:
    """Result of the confirmed factory reset (US-21)."""

    chat_cleared: bool
    aliases_deleted: int


class ResetBridge:
    """Transactional factory reset: chat, destinations, topics, aliases, toggles."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def execute(self) -> ChangeChatOutcome:
        """One transaction: settings reset, old snapshot removed, aliases deleted."""
        async with self._uow_factory() as uow:
            state = await uow.bridge_settings.get()
            chat_id = state.telegram_chat_id if state is not None else None
            await uow.bridge_settings.reset()
            if chat_id is not None:
                await uow.telegram_topics.delete_chat(chat_id)
            aliases_deleted = await uow.vk_aliases.delete_all()
            await uow.commit()
        logger.info("telegram bridge reset completed", extra={"chat_id": chat_id})
        return ChangeChatOutcome(chat_cleared=True, aliases_deleted=aliases_deleted)


class RefreshTopicsV2:
    """Existing refresh plus availability metadata persistence."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork], telethon: TelethonPort) -> None:
        self._uow_factory = uow_factory
        self._telethon = telethon

    async def refresh(self, chat_id: int) -> list[TopicInfo]:
        """Discover topics and persist the snapshot including is_closed/is_hidden."""
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
        logger.info(
            "telegram topics refreshed",
            extra={"chat_id": chat_id, "topic_count": len(topics)},
        )
        return topics
