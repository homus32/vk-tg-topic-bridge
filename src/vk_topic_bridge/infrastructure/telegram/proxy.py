"""Telethon transport resolution: MTProxy -> SOCKS5 -> direct.

`Settings` already resolved the priority; this module only translates the chosen
transport into the exact keyword arguments `TelegramClient` accepts.
"""

from __future__ import annotations

from typing import assert_never
from urllib.parse import unquote, urlsplit

from telethon.network.connection import ConnectionTcpMTProxyRandomizedIntermediate

from config import (
    DirectTransport,
    MtProxyTransport,
    Settings,
    Socks5Transport,
    TelethonTransport,
)

type TelethonClientKwargs = dict[str, object]

_SOCKS5_SCHEMES = frozenset({"socks5", "socks5h"})


def client_connection_kwargs(settings: Settings) -> TelethonClientKwargs:
    """Build `TelegramClient(..., connection=..., proxy=...)` kwargs for one transport."""
    return _transport_kwargs(settings.telethon_transport())


def _transport_kwargs(transport: TelethonTransport) -> TelethonClientKwargs:
    match transport:
        case MtProxyTransport(host=host, port=port, secret=secret):
            return {
                "connection": ConnectionTcpMTProxyRandomizedIntermediate,
                "proxy": (host, port, secret),
            }
        case Socks5Transport(url=url):
            return {"proxy": _socks5_proxy_config(url)}
        case DirectTransport():
            return {}
        case unreachable:
            assert_never(unreachable)


def _socks5_proxy_config(url: str) -> dict[str, object]:
    parts = urlsplit(url)
    if parts.scheme.lower() not in _SOCKS5_SCHEMES:
        raise ValueError(f"SOCKS5_PROXY_URL must use socks5:// or socks5h://: {url!r}")
    if parts.hostname is None:
        raise ValueError(f"SOCKS5_PROXY_URL must include a host: {url!r}")
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError(f"SOCKS5_PROXY_URL has an invalid port: {url!r}") from exc
    if port is None:
        raise ValueError(f"SOCKS5_PROXY_URL must include a port: {url!r}")
    # Telethon expects this dict form (python_socks), not an aiohttp-socks URL.
    return {
        "proxy_type": "socks5",
        "addr": parts.hostname,
        "port": port,
        "username": unquote(parts.username) if parts.username is not None else None,
        "password": unquote(parts.password) if parts.password is not None else None,
        "rdns": True,
    }
