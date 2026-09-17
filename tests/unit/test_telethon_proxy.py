"""Unit tests for the Telethon transport resolver (MTProxy -> SOCKS5 -> direct).

The resolver must turn the frozen `Settings.telethon_transport()` choice into the
exact kwargs `TelegramClient` expects, without reading the real `.env` and without
opening a connection.
"""

from __future__ import annotations

import importlib
from types import ModuleType

import pytest
from telethon.network.connection import ConnectionTcpMTProxyRandomizedIntermediate

from config import Settings

MTPROXY_SECRET = "dd00000000000000000000000000000000"


def _proxy() -> ModuleType:
    return importlib.import_module("vk_topic_bridge.infrastructure.telegram.proxy")


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    # Required keys come from the conftest dummy environment; the dotenv file is disabled.
    return Settings.model_validate({})


def test_direct_transport_returns_no_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    proxy = _proxy()
    settings = _settings(monkeypatch)

    assert proxy.client_connection_kwargs(settings) == {}


def test_mtproxy_transport_uses_tcp_mtproxy_connection_and_plain_tuple(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _proxy()
    settings = _settings(
        monkeypatch,
        TELEGRAM_MTPROXY_SERVER="127.0.0.1",
        TELEGRAM_MTPROXY_PORT="1443",
        TELEGRAM_MTPROXY_SECRET=MTPROXY_SECRET,
    )

    kwargs = proxy.client_connection_kwargs(settings)

    assert set(kwargs) == {"connection", "proxy"}
    assert kwargs["connection"] is ConnectionTcpMTProxyRandomizedIntermediate
    assert isinstance(kwargs["proxy"], tuple)
    assert kwargs["proxy"] == ("127.0.0.1", 1443, MTPROXY_SECRET)


def test_socks5_transport_builds_telethon_dict_form(monkeypatch: pytest.MonkeyPatch) -> None:
    proxy = _proxy()
    settings = _settings(monkeypatch, SOCKS5_PROXY_URL="socks5://127.0.0.1:10809")

    kwargs = proxy.client_connection_kwargs(settings)

    assert kwargs == {
        "proxy": {
            "proxy_type": "socks5",
            "addr": "127.0.0.1",
            "port": 10809,
            "username": None,
            "password": None,
            "rdns": True,
        }
    }


def test_socks5h_transport_decodes_percent_encoded_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = _proxy()
    settings = _settings(
        monkeypatch,
        SOCKS5_PROXY_URL="socks5h://user%40name:pa%3Ass@proxy.local:1080",
    )

    kwargs = proxy.client_connection_kwargs(settings)

    assert kwargs == {
        "proxy": {
            "proxy_type": "socks5",
            "addr": "proxy.local",
            "port": 1080,
            "username": "user@name",
            "password": "pa:ss",
            "rdns": True,
        }
    }


@pytest.mark.parametrize(
    "url",
    [
        "socks5://",
        "socks5://127.0.0.1",
        "socks5://127.0.0.1:not-a-port",
    ],
)
def test_malformed_socks5_url_raises_value_error(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    proxy = _proxy()
    settings = _settings(monkeypatch, SOCKS5_PROXY_URL=url)

    with pytest.raises(ValueError, match="SOCKS5_PROXY_URL"):
        proxy.client_connection_kwargs(settings)
