"""aiogram Bot construction: custom Bot API base and the frozen proxy policy.

The proxy decision itself lives in ``Settings.bot_api_proxy_url()`` (frozen contract);
this module only turns that decision into an ``AiohttpSession``.

The Bot deliberately keeps ``parse_mode`` unset: VK publication text is the only HTML
payload (it is escaped in the domain composer and sent with an explicit parse mode),
while owner-facing replies must reach Telegram as plain text so a literal ``<`` never
becomes an unintended tag.
"""

from __future__ import annotations

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

from config import LOOPBACK_HOSTS, Settings


def is_loopback(host: str) -> bool:
    """Return whether a Bot API host is local and must bypass the SOCKS5 proxy."""
    return host.lower() in LOOPBACK_HOSTS


def create_bot_session(settings: Settings) -> AiohttpSession:
    """Build the HTTP session for the configured Bot API server and proxy policy."""
    proxy = settings.bot_api_proxy_url()
    if settings.TELEGRAM_BOT_API_URL is None:
        return AiohttpSession(proxy=proxy)
    server = TelegramAPIServer.from_base(settings.TELEGRAM_BOT_API_URL)
    return AiohttpSession(api=server, proxy=proxy)


def create_bot(settings: Settings) -> Bot:
    """Build the aiogram Bot; no default parse mode is applied (plain text by default)."""
    return Bot(
        token=settings.TELEGRAM_BOT_TOKEN.get_secret_value(),
        session=create_bot_session(settings),
    )
