"""aiogram Bot API publisher and admin adapter.

Error taxonomy is fail-closed: anything that cannot prove the Bot API created no message
(timeouts, connection failures, 5xx, flood control, unknown API errors) is reported as
``PublicationAmbiguousError`` so the delivery ledger never auto-republishes. Only
definitive 4xx rejections that created no message are ``PublicationRejectedError``.
"""

from __future__ import annotations

import asyncio
import re

import aiohttp
from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramConflictError,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
    TelegramUnauthorizedError,
)
from aiogram.types import LinkPreviewOptions, Message

from vk_topic_bridge.application.errors import (
    PublicationAmbiguousError,
    PublicationRejectedError,
)
from vk_topic_bridge.domain.value_objects import (
    ChatCapabilities,
    Destination,
    Publication,
    PublicationResult,
)

_ERROR_TEXT_LIMIT = 200
_TOKEN_PATTERN = re.compile(r"\d{5,}:[A-Za-z0-9_-]{20,}")

# Bot API flag -> public capability name, in the frozen reporting order.
_CAPABILITY_FLAGS: tuple[tuple[str, str], ...] = (
    ("can_send_text", "can_send_messages"),
    ("can_send_photo", "can_send_photos"),
    ("can_send_video", "can_send_videos"),
    ("can_send_document", "can_send_documents"),
)

# Failed or hanging calls: the message may exist, so they must not be retried blindly.
_AMBIGUOUS_FAILURES: tuple[type[BaseException], ...] = (
    TimeoutError,
    aiohttp.ClientError,
    TelegramRetryAfter,
    TelegramNetworkError,
    TelegramServerError,
)

# Definitive rejections that created no message.
_REJECTED_FAILURES: tuple[type[BaseException], ...] = (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramUnauthorizedError,
    TelegramConflictError,
)

_AMBIGUOUS_CODES = {
    TimeoutError: "bot_api_timeout",
    TelegramRetryAfter: "bot_api_retry_after",
    TelegramNetworkError: "bot_api_network",
    TelegramServerError: "bot_api_server",
}


def _safe_error_text(exc: BaseException) -> str:
    """Render an error for logs without leaking a bot token embedded in a URL."""
    text = _TOKEN_PATTERN.sub("<redacted-token>", str(exc))
    return " ".join(text.split())[:_ERROR_TEXT_LIMIT]


def _classify(exc: BaseException) -> PublicationAmbiguousError | PublicationRejectedError:
    """Map a failed Bot API call onto the frozen fail-closed error taxonomy."""
    if isinstance(exc, _REJECTED_FAILURES):
        return PublicationRejectedError(_safe_error_text(exc), code="bot_api_rejected")
    if isinstance(exc, _AMBIGUOUS_FAILURES):
        code = _AMBIGUOUS_CODES.get(type(exc), "bot_api_connection")
        return PublicationAmbiguousError(_safe_error_text(exc), code=code)
    if isinstance(exc, TelegramAPIError):
        # Unknown API error: cannot prove that no message was created, so fail closed.
        return PublicationAmbiguousError(_safe_error_text(exc), code="bot_api_error")
    raise exc


async def _send_message(bot: Bot, destination: Destination, text: str) -> Message:
    """Call ``sendMessage``; the General topic is addressed by omitting the thread id.

    The two calls are deliberately separate: passing ``message_thread_id=None`` is not
    equivalent to omitting the field for all Bot API servers.
    """
    preview = LinkPreviewOptions(is_disabled=True)
    try:
        if destination.message_thread_id is None:
            return await bot.send_message(
                chat_id=destination.chat_id,
                text=text,
                link_preview_options=preview,
            )
        return await bot.send_message(
            chat_id=destination.chat_id,
            text=text,
            message_thread_id=destination.message_thread_id,
            link_preview_options=preview,
        )
    except asyncio.CancelledError:
        # Cancellation semantics belong to the caller: it marks the outcome ambiguous.
        raise
    except BaseException as exc:
        raise _classify(exc) from exc


class BotApiPublisher:
    """``TelegramPublisher`` port over aiogram's ``Bot.send_message``."""

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def publish(self, publication: Publication) -> PublicationResult:
        destination = Destination(publication.chat_id, publication.message_thread_id)
        message = await _send_message(self._bot, destination, publication.html_text)
        return PublicationResult(
            chat_id=publication.chat_id,
            message_thread_id=publication.message_thread_id,
            message_ids=(message.message_id,),
        )

    async def send_text(
        self,
        chat_id: int,
        text: str,
        message_thread_id: int | None = None,
    ) -> int:
        destination = Destination(chat_id, message_thread_id)
        message = await _send_message(self._bot, destination, text)
        return message.message_id


class BotApiAdminPort:
    """``TelegramAdminPort`` port: identity, chat capabilities and topic smoke sends.

    Capability defaults: a permission flag that aiogram exposes as ``None`` (non-admin
    and non-restricted chat members carry no ``can_send_*`` fields at all) is treated as
    allowed; only an explicit ``False`` denies it. Members whose status is ``left`` or
    ``kicked`` deny every capability regardless of flags. ``can_manage_topics`` is not a
    publication capability and never appears in ``missing``.
    """

    _ABSENT_STATUSES = frozenset({ChatMemberStatus.LEFT, ChatMemberStatus.KICKED})

    def __init__(self, bot: Bot) -> None:
        self._bot = bot
        self._publisher = BotApiPublisher(bot)

    async def get_me(self) -> int:
        return (await self._bot.get_me()).id

    async def get_chat_capabilities(self, chat_id: int) -> ChatCapabilities:
        bot_id = (await self._bot.get_me()).id
        member = await self._bot.get_chat_member(chat_id, bot_id)
        absent = member.status in self._ABSENT_STATUSES
        allowed = {
            public_name: not absent and getattr(member, telegram_name, None) is not False
            for public_name, telegram_name in _CAPABILITY_FLAGS
        }
        return ChatCapabilities(
            can_send_text=allowed["can_send_text"],
            can_send_photo=allowed["can_send_photo"],
            can_send_video=allowed["can_send_video"],
            can_send_document=allowed["can_send_document"],
            missing=tuple(name for name, _ in _CAPABILITY_FLAGS if not allowed[name]),
        )

    async def send_test_into_topic(
        self,
        chat_id: int,
        message_thread_id: int | None,
        text: str,
    ) -> int:
        return await self._publisher.send_text(chat_id, text, message_thread_id)
