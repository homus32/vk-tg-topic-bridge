"""US-24: local Bot API traffic bypasses SOCKS5, Telethon stays independent.

AC-24.1 — a loopback ``TELEGRAM_BOT_API_URL`` means no SOCKS5 for Bot API requests.
AC-24.2 — Telethon's transport choice does not depend on ``TELEGRAM_BOT_API_URL``.
AC-24.3 — a remote Bot API endpoint may use the configured SOCKS5.
"""

from __future__ import annotations

import pytest
from aiogram.client.telegram import PRODUCTION

from config import MtProxyTransport, Socks5Transport
from tests.acceptance._fakes import settings_from_env
from vk_topic_bridge.infrastructure.telegram.bot_api_factory import create_bot_session, is_loopback

SOCKS5_URL = "socks5://127.0.0.1:10809"
MTPROXY_KWARGS = {
    "TELEGRAM_MTPROXY_SERVER": "mtproxy.example.com",
    "TELEGRAM_MTPROXY_PORT": "1443",
    "TELEGRAM_MTPROXY_SECRET": "dd00000000000000000000000000000000",
}


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("http://localhost:8081", id="localhost"),
        pytest.param("http://127.0.0.1:8081", id="ipv4-loopback"),
        pytest.param("http://[::1]:8081", id="ipv6-loopback"),
    ],
)
def test_us24_ac241_loopback_bot_api_has_no_socks5(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    settings = settings_from_env(monkeypatch, TELEGRAM_BOT_API_URL=url, SOCKS5_PROXY_URL=SOCKS5_URL)

    session = create_bot_session(settings)

    assert session.proxy is None
    assert session.api.base.startswith(url)


def test_us24_ac243_remote_bot_api_uses_socks5(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = settings_from_env(
        monkeypatch,
        TELEGRAM_BOT_API_URL="https://bot.example.com",
        SOCKS5_PROXY_URL=SOCKS5_URL,
    )

    session = create_bot_session(settings)

    assert session.proxy == SOCKS5_URL
    assert session.api.base.startswith("https://bot.example.com")


def test_us24_ac241_official_api_without_proxy_has_none(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = settings_from_env(monkeypatch)

    session = create_bot_session(settings)

    assert session.api.base == PRODUCTION.base
    assert session.proxy is None


def test_us24_ac242_loopback_bot_api_does_not_change_telethon_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loopback = settings_from_env(
        monkeypatch, TELEGRAM_BOT_API_URL="http://127.0.0.1:8081", SOCKS5_PROXY_URL=SOCKS5_URL
    )

    assert loopback.bot_api_proxy_url() is None
    assert isinstance(loopback.telethon_transport(), Socks5Transport)


def test_us24_ac242_telethon_uses_mtproxy_even_when_bot_api_is_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings_from_env(
        monkeypatch,
        TELEGRAM_BOT_API_URL="http://localhost:8081",
        SOCKS5_PROXY_URL=SOCKS5_URL,
        **MTPROXY_KWARGS,
    )

    assert settings.bot_api_proxy_url() is None
    transport = settings.telethon_transport()
    assert isinstance(transport, MtProxyTransport)
    assert transport.host == "mtproxy.example.com"


def test_us24_loopback_detection_covers_only_local_hosts() -> None:
    assert is_loopback("localhost") is True
    assert is_loopback("127.0.0.1") is True
    assert is_loopback("::1") is True
    assert is_loopback("api.telegram.org") is False
    assert is_loopback("192.168.1.10") is False
