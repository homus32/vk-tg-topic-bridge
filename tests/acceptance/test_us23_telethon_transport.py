"""US-23: Telethon transport priority — MTProxy, then SOCKS5, then direct.

A complete MTProxy triplet wins over SOCKS5; SOCKS5 is used when no MTProxy is
configured; otherwise the client connects directly. A partial MTProxy triplet is a
critical configuration error, not a silent downgrade.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from telethon.network.connection import ConnectionTcpMTProxyRandomizedIntermediate

from config import DirectTransport, MtProxyTransport, Socks5Transport
from tests.acceptance._fakes import settings_from_env
from vk_topic_bridge.infrastructure.telegram.proxy import client_connection_kwargs

MTPROXY_SECRET = "dd00000000000000000000000000000000"
SOCKS5_URL = "socks5://127.0.0.1:10809"
MTPROXY_KWARGS = {
    "TELEGRAM_MTPROXY_SERVER": "mtproxy.example.com",
    "TELEGRAM_MTPROXY_PORT": "1443",
    "TELEGRAM_MTPROXY_SECRET": MTPROXY_SECRET,
}


def test_us23_mtproxy_has_priority_when_all_three_parameters_are_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings_from_env(monkeypatch, SOCKS5_PROXY_URL=SOCKS5_URL, **MTPROXY_KWARGS)

    transport = settings.telethon_transport()
    kwargs = client_connection_kwargs(settings)

    assert isinstance(transport, MtProxyTransport)
    assert kwargs["connection"] is ConnectionTcpMTProxyRandomizedIntermediate
    assert kwargs["proxy"] == ("mtproxy.example.com", 1443, MTPROXY_SECRET)
    assert "proxy_type" not in kwargs


def test_us23_socks5_is_used_without_mtproxy(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = settings_from_env(monkeypatch, SOCKS5_PROXY_URL=SOCKS5_URL)

    transport = settings.telethon_transport()
    kwargs = client_connection_kwargs(settings)

    assert isinstance(transport, Socks5Transport)
    assert kwargs["proxy"] == {
        "proxy_type": "socks5",
        "addr": "127.0.0.1",
        "port": 10809,
        "username": None,
        "password": None,
        "rdns": True,
    }
    assert "connection" not in kwargs


def test_us23_direct_connection_without_any_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = settings_from_env(monkeypatch)

    transport = settings.telethon_transport()

    assert isinstance(transport, DirectTransport)
    assert client_connection_kwargs(settings) == {}


@pytest.mark.parametrize(
    "partial",
    [
        pytest.param({"TELEGRAM_MTPROXY_SERVER": "mtproxy.example.com"}, id="server-only"),
        pytest.param({"TELEGRAM_MTPROXY_PORT": "1443"}, id="port-only"),
        pytest.param({"TELEGRAM_MTPROXY_SECRET": MTPROXY_SECRET}, id="secret-only"),
        pytest.param(
            {"TELEGRAM_MTPROXY_SERVER": "mtproxy.example.com", "TELEGRAM_MTPROXY_PORT": "1443"},
            id="server-and-port",
        ),
    ],
)
def test_us23_partial_mtproxy_triplet_is_a_critical_configuration_error(
    monkeypatch: pytest.MonkeyPatch, partial: dict[str, str]
) -> None:
    with pytest.raises(ValidationError) as excinfo:
        settings_from_env(monkeypatch, SOCKS5_PROXY_URL=SOCKS5_URL, **partial)

    assert "MTProxy configuration is all-or-nothing" in str(excinfo.value)
