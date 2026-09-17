"""Telethon user-client adapter: authorization, chat access and forum topics.

Discovery only: this adapter never publishes and never touches the Bot API. The
`TelegramClient` is constructed, connected and disconnected by the caller
(composition root); the adapter only issues queries against it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from telethon import functions, hints, types, utils
from telethon.errors import RPCError
from telethon.tl.types.messages import ForumTopics

from vk_topic_bridge.application.dto.infrastructure import ChatAccessInfo
from vk_topic_bridge.domain.errors import RecoverableInfraError
from vk_topic_bridge.domain.value_objects import TopicInfo

TOPICS_PAGE_LIMIT = 100
GENERAL_TOPIC_ID = 1


class TelethonUserClient(Protocol):
    """Structural view of the `TelegramClient` calls this adapter depends on."""

    async def is_user_authorized(self) -> bool: ...
    async def get_me(self) -> object: ...
    async def get_entity(self, entity: int) -> hints.Entity | list[hints.Entity]: ...
    async def get_input_entity(self, peer: hints.EntityLike) -> types.TypeInputPeer: ...
    async def __call__(self, request: functions.messages.GetForumTopicsRequest) -> object: ...


@dataclass(frozen=True, slots=True)
class _TopicsCursor:
    offset_date: datetime | None = None
    offset_id: int = 0
    offset_topic: int = 0


class TelethonAdapter:
    """`TelethonPort` implementation backed by a caller-owned TelegramClient."""

    def __init__(self, client: TelethonUserClient) -> None:
        self._client = client

    async def is_authorized(self) -> bool:
        return await self._client.is_user_authorized()

    async def get_me(self) -> object:
        return await self._client.get_me()

    async def verify_chat_access(self, chat_id: int) -> ChatAccessInfo:
        entity = await self._resolve_entity(chat_id)
        return ChatAccessInfo(
            entity_id=utils.get_peer_id(entity),
            is_forum=bool(getattr(entity, "forum", False)),
        )

    async def list_topics(self, chat_id: int) -> list[TopicInfo]:
        entity = await self._resolve_entity(chat_id)
        peer = await self._resolve_input_peer(entity)
        topics: list[TopicInfo] = []
        seen_ids: set[int] = set()
        cursor = _TopicsCursor()
        while True:
            page = await self._fetch_topics_page(peer, cursor)
            new_topics = [
                topic
                for topic in page.topics
                if isinstance(topic, types.ForumTopic) and topic.id not in seen_ids
            ]
            if not new_topics:
                break
            topics.extend(_map_topic(topic) for topic in new_topics)
            seen_ids.update(topic.id for topic in new_topics)
            if len(page.topics) < TOPICS_PAGE_LIMIT:
                break
            anchor = new_topics[-1]
            cursor = _TopicsCursor(
                offset_date=_message_date(page.messages, anchor.top_message),
                offset_id=anchor.top_message,
                offset_topic=anchor.id,
            )
        return topics

    async def _resolve_entity(self, chat_id: int) -> hints.Entity:
        try:
            entity = await self._client.get_entity(chat_id)
        except (RPCError, ValueError) as exc:
            raise RecoverableInfraError(
                f"Telegram chat {chat_id} cannot be resolved or accessed"
            ) from exc
        if isinstance(entity, list):
            raise RecoverableInfraError(f"Telegram chat {chat_id} resolved to several entities")
        return entity

    async def _resolve_input_peer(self, entity: hints.Entity) -> types.TypeInputPeer:
        try:
            return await self._client.get_input_entity(entity)
        except (RPCError, ValueError) as exc:
            raise RecoverableInfraError(
                f"Telegram chat entity {entity.id} cannot be accessed"
            ) from exc

    async def _fetch_topics_page(
        self, peer: types.TypeInputPeer, cursor: _TopicsCursor
    ) -> ForumTopics:
        request = functions.messages.GetForumTopicsRequest(
            peer=peer,
            offset_date=cursor.offset_date,
            offset_id=cursor.offset_id,
            offset_topic=cursor.offset_topic,
            limit=TOPICS_PAGE_LIMIT,
        )
        try:
            response = await self._client(request)
        except RPCError as exc:
            raise RecoverableInfraError("Telegram forum topics are unavailable") from exc
        if not isinstance(response, ForumTopics):
            raise RecoverableInfraError("Telegram returned an unexpected forum topics response")
        return response


def _message_date(messages: list[types.TypeMessage], message_id: int) -> datetime | None:
    for message in messages:
        if isinstance(message, (types.Message, types.MessageService)) and message.id == message_id:
            return message.date
    return None


def _map_topic(topic: types.ForumTopic) -> TopicInfo:
    # Telegram uses topic id 1 for General; the domain contract uses None.
    # Accepted only after the HUMAN GATE TG-TOPIC Bot API send into General is proven.
    is_general = topic.id == GENERAL_TOPIC_ID
    return TopicInfo(
        topic_id=None if is_general else topic.id,
        title=topic.title,
        is_general=is_general,
        is_closed=bool(topic.closed),
        is_hidden=bool(topic.hidden),
    )
