"""Transport recovery: bounded retry and reconnect around Telethon RPC calls (no network)."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from types import ModuleType

import pytest
from telethon import functions, hints, types
from telethon.tl.types.messages import ForumTopics

from vk_topic_bridge.domain.errors import RecoverableInfraError
from vk_topic_bridge.domain.value_objects import TopicInfo

CHANNEL_ID = 1234567890
PAGE_DATE = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _mtproto(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    module = importlib.import_module("vk_topic_bridge.infrastructure.telegram.mtproto")
    monkeypatch.setattr(module, "_RPC_BACKOFF_SECONDS", 0.0)
    return module


def _channel() -> types.Channel:
    return types.Channel(
        id=CHANNEL_ID,
        title="Bridge chat",
        photo=types.ChatPhotoEmpty(),
        date=None,
        forum=True,
    )


def _page() -> ForumTopics:
    topic = types.ForumTopic(
        id=7,
        date=PAGE_DATE,
        peer=types.PeerChannel(channel_id=CHANNEL_ID),
        title="FAQ",
        icon_color=0,
        top_message=70,
        read_inbox_max_id=0,
        read_outbox_max_id=0,
        unread_count=0,
        unread_mentions_count=0,
        unread_reactions_count=0,
        unread_poll_votes_count=0,
        from_id=types.PeerChannel(channel_id=CHANNEL_ID),
        notify_settings=types.PeerNotifySettings(),
        closed=None,
        hidden=None,
    )
    return ForumTopics(count=1, topics=[topic], messages=[], chats=[], users=[], pts=1)


class _FlakyTelethonClient:
    """Fails the first `fail_first` calls with a transport error, then succeeds."""

    def __init__(self, *, fail_first: int, connected: bool, drop_connection: bool = True) -> None:
        self._fail_first = fail_first
        self._connected = connected
        self._drop_connection = drop_connection
        self.connect_calls = 0

    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        self.connect_calls += 1
        self._connected = True

    async def is_user_authorized(self) -> bool:
        return True

    async def get_me(self) -> object:
        return object()

    async def get_entity(self, entity: int) -> hints.Entity | list[hints.Entity]:
        self._fail_transport()
        return _channel()

    async def get_input_entity(self, peer: hints.EntityLike) -> types.TypeInputPeer:
        self._fail_transport()
        return types.InputPeerChannel(channel_id=CHANNEL_ID, access_hash=0)

    async def __call__(self, request: functions.messages.GetForumTopicsRequest) -> object:
        self._fail_transport()
        return _page()

    def _fail_transport(self) -> None:
        if self._fail_first > 0:
            self._fail_first -= 1
            if self._drop_connection:
                self._connected = False
            raise ConnectionError("Cannot send requests while disconnected")


async def test_transport_failure_triggers_reconnect_and_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mtproto = _mtproto(monkeypatch)
    client = _FlakyTelethonClient(fail_first=1, connected=False)
    adapter = mtproto.TelethonAdapter(client)

    topics = await adapter.list_topics(CHANNEL_ID)

    assert topics == [
        TopicInfo(topic_id=7, title="FAQ", is_general=False, is_closed=False, is_hidden=False)
    ]
    assert client.connect_calls == 1


async def test_persistent_transport_failure_exhausts_bounded_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mtproto = _mtproto(monkeypatch)
    client = _FlakyTelethonClient(fail_first=99, connected=False)
    adapter = mtproto.TelethonAdapter(client)

    with pytest.raises(RecoverableInfraError, match=str(CHANNEL_ID)):
        await adapter.list_topics(CHANNEL_ID)

    assert client.connect_calls == 2


async def test_still_connected_client_is_not_reconnected_for_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mtproto = _mtproto(monkeypatch)
    client = _FlakyTelethonClient(fail_first=1, connected=True, drop_connection=False)
    adapter = mtproto.TelethonAdapter(client)

    topics = await adapter.list_topics(CHANNEL_ID)

    assert topics == [
        TopicInfo(topic_id=7, title="FAQ", is_general=False, is_closed=False, is_hidden=False)
    ]
    assert client.connect_calls == 0
