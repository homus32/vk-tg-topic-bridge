"""Forum-topic mapper tests: `ForumTopics` pages -> `TopicInfo` list (no network).

Real Telethon TL objects are used on the boundary, so the adapter is exercised the
same way it will be against the network, minus the transport.
"""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from datetime import UTC, datetime
from types import ModuleType

from telethon import functions, hints, types
from telethon.tl.types.messages import ForumTopics

from vk_topic_bridge.domain.value_objects import TopicInfo

CHANNEL_ID = 1234567890
PAGE_LIMIT = 100
PAGE_DATE = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _mtproto() -> ModuleType:
    return importlib.import_module("vk_topic_bridge.infrastructure.telegram.mtproto")


def _build_topic(
    topic_id: int,
    *,
    title: str | None = None,
    top_message: int | None = None,
    closed: bool | None = None,
    hidden: bool | None = None,
) -> types.ForumTopic:
    return types.ForumTopic(
        id=topic_id,
        date=PAGE_DATE,
        peer=types.PeerChannel(channel_id=CHANNEL_ID),
        title=title if title is not None else f"Topic {topic_id}",
        icon_color=0,
        top_message=top_message if top_message is not None else topic_id * 10,
        read_inbox_max_id=0,
        read_outbox_max_id=0,
        unread_count=0,
        unread_mentions_count=0,
        unread_reactions_count=0,
        unread_poll_votes_count=0,
        from_id=types.PeerChannel(channel_id=CHANNEL_ID),
        notify_settings=types.PeerNotifySettings(),
        closed=closed,
        hidden=hidden,
    )


def _build_message(message_id: int) -> types.Message:
    return types.Message(
        id=message_id,
        peer_id=types.PeerChannel(channel_id=CHANNEL_ID),
        date=PAGE_DATE,
        message="",
    )


def _build_page(
    topics: Sequence[types.TypeForumTopic],
    messages: Sequence[types.TypeMessage] | None = None,
) -> ForumTopics:
    topic_items: list[types.TypeForumTopic] = list(topics)
    message_items: list[types.TypeMessage] = list(messages or [])
    return ForumTopics(
        count=len(topic_items),
        topics=topic_items,
        messages=message_items,
        chats=[],
        users=[],
        pts=1,
    )


class _FakeTelethonClient:
    """Structural stand-in for the TelegramClient calls the adapter makes."""

    def __init__(self, pages: list[ForumTopics]) -> None:
        self._pages = pages
        self.requests: list[functions.messages.GetForumTopicsRequest] = []

    async def is_user_authorized(self) -> bool:
        return True

    async def get_me(self) -> object:
        return object()

    async def get_entity(self, entity: int) -> hints.Entity | list[hints.Entity]:
        return types.Channel(
            id=CHANNEL_ID,
            title="Bridge chat",
            photo=types.ChatPhotoEmpty(),
            date=None,
            forum=True,
        )

    async def get_input_entity(self, peer: hints.EntityLike) -> types.TypeInputPeer:
        return types.InputPeerChannel(channel_id=CHANNEL_ID, access_hash=0)

    async def __call__(self, request: functions.messages.GetForumTopicsRequest) -> object:
        self.requests.append(request)
        return self._pages.pop(0)


async def test_general_topic_maps_to_none_id_with_general_flag() -> None:
    mtproto = _mtproto()
    client = _FakeTelethonClient([_build_page([_build_topic(1, title="General")])])
    adapter = mtproto.TelethonAdapter(client)

    topics = await adapter.list_topics(CHANNEL_ID)

    assert topics == [
        TopicInfo(topic_id=None, title="General", is_general=True, is_closed=False, is_hidden=False)
    ]


async def test_regular_topic_keeps_numeric_id_and_flags() -> None:
    mtproto = _mtproto()
    client = _FakeTelethonClient(
        [_build_page([_build_topic(7, title="FAQ", closed=True, hidden=True)])]
    )
    adapter = mtproto.TelethonAdapter(client)

    topics = await adapter.list_topics(CHANNEL_ID)

    assert topics == [
        TopicInfo(topic_id=7, title="FAQ", is_general=False, is_closed=True, is_hidden=True)
    ]


async def test_two_pages_are_concatenated_in_order_and_cursor_follows_last_topic() -> None:
    mtproto = _mtproto()
    first_page = [_build_topic(topic_id) for topic_id in range(1, PAGE_LIMIT + 1)]
    second_page = [_build_topic(topic_id) for topic_id in range(PAGE_LIMIT + 1, 151)]
    client = _FakeTelethonClient(
        [
            _build_page(first_page, messages=[_build_message(PAGE_LIMIT * 10)]),
            _build_page(second_page),
        ]
    )
    adapter = mtproto.TelethonAdapter(client)

    topics = await adapter.list_topics(CHANNEL_ID)

    assert len(client.requests) == 2
    first_request, second_request = client.requests
    assert (first_request.offset_id, first_request.offset_topic, first_request.offset_date) == (
        0,
        0,
        None,
    )
    assert (second_request.offset_id, second_request.offset_topic, second_request.offset_date) == (
        PAGE_LIMIT * 10,
        PAGE_LIMIT,
        PAGE_DATE,
    )
    assert second_request.limit == PAGE_LIMIT
    assert [topic.topic_id for topic in topics] == [None, *range(2, 151)]


async def test_repeated_page_stops_pagination_without_reprocessing() -> None:
    mtproto = _mtproto()
    repeated = [_build_topic(topic_id) for topic_id in range(1, PAGE_LIMIT + 1)]
    client = _FakeTelethonClient([_build_page(repeated), _build_page(repeated)])
    adapter = mtproto.TelethonAdapter(client)

    topics = await adapter.list_topics(CHANNEL_ID)

    assert len(client.requests) == 2
    assert len(topics) == PAGE_LIMIT
