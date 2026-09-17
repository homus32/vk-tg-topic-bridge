"""Chat-access tests: entity resolution, forum flag and error propagation (no network)."""

from __future__ import annotations

import importlib
from types import ModuleType

import pytest
from telethon import functions, hints, types, utils
from telethon.errors import RPCError

from vk_topic_bridge.application.dto.infrastructure import ChatAccessInfo
from vk_topic_bridge.domain.errors import RecoverableInfraError

CHANNEL_ID = 1234567890


def _mtproto() -> ModuleType:
    return importlib.import_module("vk_topic_bridge.infrastructure.telegram.mtproto")


class _FakeTelethonClient:
    def __init__(self, entity: hints.Entity | list[hints.Entity] | Exception) -> None:
        self._entity = entity

    async def is_user_authorized(self) -> bool:
        return True

    async def get_me(self) -> object:
        return {"id": CHANNEL_ID}

    async def get_entity(self, entity: int) -> hints.Entity | list[hints.Entity]:
        if isinstance(self._entity, Exception):
            raise self._entity
        return self._entity

    async def get_input_entity(self, peer: hints.EntityLike) -> types.TypeInputPeer:
        raise AssertionError("chat access must not resolve an input peer")

    async def __call__(self, request: functions.messages.GetForumTopicsRequest) -> object:
        raise AssertionError("chat access must not fetch forum topics")


def _channel(*, forum: bool | None) -> types.Channel:
    return types.Channel(
        id=CHANNEL_ID,
        title="Bridge chat",
        photo=types.ChatPhotoEmpty(),
        date=None,
        forum=forum,
    )


def _plain_chat() -> types.Chat:
    return types.Chat(
        id=42,
        title="Plain chat",
        photo=types.ChatPhotoEmpty(),
        participants_count=2,
        date=None,
        version=0,
    )


async def test_forum_channel_reports_numeric_entity_id_and_forum_flag() -> None:
    mtproto = _mtproto()
    channel = _channel(forum=True)
    adapter = mtproto.TelethonAdapter(_FakeTelethonClient(channel))

    access = await adapter.verify_chat_access(CHANNEL_ID)

    assert access == ChatAccessInfo(entity_id=utils.get_peer_id(channel), is_forum=True)


async def test_channel_without_forum_flag_reports_false() -> None:
    mtproto = _mtproto()
    channel = _channel(forum=None)
    adapter = mtproto.TelethonAdapter(_FakeTelethonClient(channel))

    access = await adapter.verify_chat_access(CHANNEL_ID)

    assert access.entity_id == utils.get_peer_id(channel)
    assert access.is_forum is False


async def test_plain_chat_reports_false_forum() -> None:
    mtproto = _mtproto()
    chat = _plain_chat()
    adapter = mtproto.TelethonAdapter(_FakeTelethonClient(chat))

    access = await adapter.verify_chat_access(CHANNEL_ID)

    assert access.entity_id == utils.get_peer_id(chat)
    assert access.is_forum is False


async def test_unresolvable_entity_raises_recoverable_error() -> None:
    mtproto = _mtproto()
    client = _FakeTelethonClient(ValueError("Cannot find any entity corresponding to -100"))
    adapter = mtproto.TelethonAdapter(client)

    with pytest.raises(RecoverableInfraError, match=str(CHANNEL_ID)):
        await adapter.verify_chat_access(CHANNEL_ID)


async def test_rpc_failure_raises_recoverable_error() -> None:
    mtproto = _mtproto()
    client = _FakeTelethonClient(RPCError(request=None, message="CHANNEL_PRIVATE"))
    adapter = mtproto.TelethonAdapter(client)

    with pytest.raises(RecoverableInfraError, match=str(CHANNEL_ID)):
        await adapter.list_topics(CHANNEL_ID)


async def test_is_authorized_and_get_me_proxy_to_client() -> None:
    mtproto = _mtproto()
    adapter = mtproto.TelethonAdapter(_FakeTelethonClient(_channel(forum=True)))

    assert await adapter.is_authorized() is True
    assert await adapter.get_me() == {"id": CHANNEL_ID}
