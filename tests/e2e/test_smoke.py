"""Opt-in E2E smoke tests: real Bot API, Telethon session and VK identity.

Read-only by design: no message, reaction or topic mutation happens here. Run
explicitly via ``make test-e2e``; the default suite excludes these through the
``-m 'not e2e'`` addopts filter.
"""

from __future__ import annotations

import functools
import re

import pytest
from telethon import TelegramClient
from vkbottle import API

from config import Settings
from vk_topic_bridge.infrastructure.telegram.bot_api_factory import create_bot
from vk_topic_bridge.infrastructure.telegram.proxy import client_connection_kwargs
from vk_topic_bridge.infrastructure.vk.api import VkApiGateway

pytestmark = pytest.mark.e2e

E2E_RUN_ID_PATTERN = r"[0-9]{8}T[0-9]{6}-[0-9a-f]{8}"
AUTHORIZE_HINT = "uv run --locked python authorize_telegram.py"


async def _disconnect(client: TelegramClient) -> None:
    """Telethon annotates `disconnect` as sync, yet returns a coroutine inside a running loop."""
    outcome = client.disconnect()
    if outcome is not None:
        await outcome


async def test_bot_api_get_me(e2e_settings: Settings) -> None:
    """The configured bot token resolves to a real bot identity."""
    bot = create_bot(e2e_settings)
    try:
        me = await bot.get_me()
        assert me.id > 0
        assert me.username is not None
        assert me.username != ""
    finally:
        await bot.session.close()


async def test_telethon_session_authorized(e2e_settings: Settings) -> None:
    """The persisted user session is authorized and resolves a user entity."""
    # `client_connection_kwargs` is type-erased (`dict[str, object]`); `functools.partial`
    # lets its values reach the typed constructor without casts or ignores, the same
    # pattern as `authorize_telegram.py`.
    factory = functools.partial(
        TelegramClient,
        e2e_settings.TELEGRAM_SESSION_PATH,
        e2e_settings.TELEGRAM_API_ID,
        e2e_settings.TELEGRAM_API_HASH.get_secret_value(),
        **client_connection_kwargs(e2e_settings),
    )
    client = factory()
    await client.connect()
    try:
        if not await client.is_user_authorized():
            pytest.skip(f"Telethon session is not authorized; run `{AUTHORIZE_HINT}`")
        assert await client.get_me() is not None
    finally:
        await _disconnect(client)


async def test_vk_identity_and_long_poll(e2e_settings: Settings) -> None:
    """The community token resolves the community and Long Poll is enabled."""
    api = API(token=e2e_settings.VK_GROUP_TOKEN.get_secret_value())
    gateway = VkApiGateway(api, e2e_settings)
    assert await gateway.get_community_id() > 0
    long_poll = await gateway.check_long_poll()
    assert long_poll.enabled is True


def test_e2e_run_id_is_unique(e2e_run_id: str) -> None:
    """The run id has the documented timestamp-plus-random-suffix shape."""
    assert re.fullmatch(E2E_RUN_ID_PATTERN, e2e_run_id) is not None
