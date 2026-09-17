"""Factory tests: Bot/session wiring, custom Bot API base and the frozen proxy policy.

No Telegram call is performed: a session only becomes a real HTTP client on first use.
"""

from __future__ import annotations

import importlib
from types import ModuleType

import pytest
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import PRODUCTION
from aiogram.enums import ParseMode

from config import Settings

BOT_TOKEN = "123456:TEST-BOT-TOKEN"
SOCKS5_URL = "socks5://127.0.0.1:10809"


def _factory() -> ModuleType:
    return importlib.import_module("vk_topic_bridge.infrastructure.telegram.bot_api_factory")


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    # The autouse fixture disables the dotenv file, so only the patched env is read.
    return Settings.model_validate({})


def test_loopback_hosts_are_recognized() -> None:
    factory = _factory()

    assert factory.is_loopback("localhost")
    assert factory.is_loopback("127.0.0.1")
    assert factory.is_loopback("::1")


def test_remote_hosts_are_not_loopback() -> None:
    factory = _factory()

    assert not factory.is_loopback("api.telegram.org")
    assert not factory.is_loopback("bot.example.com")


def test_loopback_custom_base_has_no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = _factory()
    settings = _settings(
        monkeypatch,
        TELEGRAM_BOT_API_URL="http://127.0.0.1:8081",
        SOCKS5_PROXY_URL=SOCKS5_URL,
    )

    session = factory.create_bot_session(settings)

    assert session.api.base.startswith("http://127.0.0.1:8081")
    assert session.proxy is None


def test_remote_custom_base_uses_socks5_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = _factory()
    settings = _settings(
        monkeypatch,
        TELEGRAM_BOT_API_URL="https://bot.example.com",
        SOCKS5_PROXY_URL=SOCKS5_URL,
    )

    session = factory.create_bot_session(settings)

    assert session.api.base.startswith("https://bot.example.com")
    assert session.proxy == SOCKS5_URL


def test_absent_url_falls_back_to_official_api(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = _factory()
    settings = _settings(monkeypatch)

    session = factory.create_bot_session(settings)

    assert session.api.base == PRODUCTION.base
    assert session.proxy is None


async def test_create_bot_uses_token_custom_server_and_html_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _factory()
    settings = _settings(
        monkeypatch,
        TELEGRAM_BOT_TOKEN=BOT_TOKEN,
        TELEGRAM_BOT_API_URL="http://127.0.0.1:8081",
    )

    bot = factory.create_bot(settings)

    assert bot.token == BOT_TOKEN
    assert isinstance(bot.session, AiohttpSession)
    assert bot.session.api.base.startswith("http://127.0.0.1:8081")
    assert bot.default.parse_mode is ParseMode.HTML
    await bot.session.close()
