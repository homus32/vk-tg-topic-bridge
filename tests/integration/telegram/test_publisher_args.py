"""Publisher tests: exact Bot API call arguments, fail-closed error mapping, capabilities.

A recording fake Bot is injected, so no HTTP request is ever attempted.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import cast

import aiohttp
import pytest
from aiogram import Bot
from aiogram.enums import ChatMemberStatus, ParseMode
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramConflictError,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
    TelegramUnauthorizedError,
)
from aiogram.methods import SendMessage
from aiogram.types import (
    ChatMemberAdministrator,
    ChatMemberBanned,
    ChatMemberLeft,
    ChatMemberMember,
    ChatMemberRestricted,
    ChatMemberUnion,
    LinkPreviewOptions,
    User,
)

from vk_topic_bridge.application.errors import (
    PublicationAmbiguousError,
    PublicationRejectedError,
)
from vk_topic_bridge.application.ports.telegram import TelegramAdminPort, TelegramPublisher
from vk_topic_bridge.domain.enums import SourceType
from vk_topic_bridge.domain.value_objects import Author, Publication, SourceMessage

BOT_ID = 77
CHAT_ID = -1001234567890
MESSAGE_ID = 501


def _user() -> User:
    return User(id=BOT_ID, is_bot=True, first_name="Bridge")


def _source() -> SourceMessage:
    return SourceMessage(
        source_type=SourceType.VK_MESSAGE,
        source_key="42:2000000001:17",
        group_id=42,
        peer_id=2000000001,
        conversation_message_id=17,
        author=Author(user_id=1, first_name="Иван", last_name="Петров", screen_name="ivan"),
        text="привет",
        has_all=False,
        has_hashtag=False,
        attachments=(),
    )


def _publication(thread_id: int | None) -> Publication:
    return Publication(
        chat_id=CHAT_ID,
        message_thread_id=thread_id,
        html_text="<b>Иван Петров</b> (https://vk.com/id1)\nпривет\n#извк",  # noqa: RUF001
        has_all=False,
        source=_source(),
    )


class FakeMessage:
    """Minimal stand-in exposing the only attribute the publisher reads."""

    def __init__(self, message_id: int) -> None:
        self.message_id = message_id


class FakeBot:
    """Records every Bot API call and replays a configured result or exception."""

    def __init__(
        self,
        *,
        error: BaseException | None = None,
        member: ChatMemberUnion | None = None,
    ) -> None:
        self.error = error
        self.member = member
        self.send_message_calls: list[dict[str, object]] = []
        self.get_chat_member_calls: list[tuple[int, int]] = []

    async def send_message(self, **kwargs: object) -> FakeMessage:
        self.send_message_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return FakeMessage(MESSAGE_ID)

    async def get_me(self) -> User:
        return _user()

    async def get_chat_member(self, chat_id: int, user_id: int) -> ChatMemberUnion:
        self.get_chat_member_calls.append((chat_id, user_id))
        assert self.member is not None
        return self.member


def _publisher(fake: FakeBot) -> tuple[TelegramPublisher, TelegramAdminPort]:
    from vk_topic_bridge.infrastructure.telegram.publisher import BotApiAdminPort, BotApiPublisher

    bot = cast(Bot, fake)
    return BotApiPublisher(bot), BotApiAdminPort(bot)


def _restricted(**overrides: bool) -> ChatMemberRestricted:
    values: dict[str, object] = {
        "user": _user(),
        "is_member": True,
        "until_date": datetime(1970, 1, 1, tzinfo=UTC),
        "can_send_messages": True,
        "can_send_audios": True,
        "can_send_documents": True,
        "can_send_photos": True,
        "can_send_videos": True,
        "can_send_video_notes": True,
        "can_send_voice_notes": True,
        "can_send_polls": True,
        "can_send_other_messages": True,
        "can_add_web_page_previews": True,
        "can_react_to_messages": True,
        "can_edit_tag": True,
        "can_change_info": True,
        "can_invite_users": True,
        "can_pin_messages": True,
        "can_manage_topics": True,
    }
    values.update(overrides)
    return ChatMemberRestricted.model_validate(values)


def _administrator(**overrides: bool) -> ChatMemberAdministrator:
    values: dict[str, object] = {
        "user": _user(),
        "can_be_edited": True,
        "is_anonymous": False,
        "can_manage_chat": True,
        "can_delete_messages": True,
        "can_manage_video_chats": True,
        "can_restrict_members": True,
        "can_promote_members": True,
        "can_change_info": True,
        "can_invite_users": True,
        "can_post_stories": True,
        "can_edit_stories": True,
        "can_delete_stories": True,
        "can_send_welcome_messages": True,
    }
    values.update(overrides)
    return ChatMemberAdministrator.model_validate(values)


def _send_error() -> SendMessage:
    return SendMessage(chat_id=CHAT_ID, text="hi")


# --- publish: arguments -------------------------------------------------------


async def test_publish_omits_message_thread_id_for_general_topic() -> None:
    fake = FakeBot()
    publisher, _ = _publisher(fake)

    result = await publisher.publish(_publication(None))

    kwargs = fake.send_message_calls[0]
    assert "message_thread_id" not in kwargs
    assert kwargs["chat_id"] == CHAT_ID
    assert result.chat_id == CHAT_ID
    assert result.message_thread_id is None
    assert result.message_ids == (MESSAGE_ID,)


async def test_publish_passes_message_thread_id_for_topic_destination() -> None:
    fake = FakeBot()
    publisher, _ = _publisher(fake)

    result = await publisher.publish(_publication(7))

    kwargs = fake.send_message_calls[0]
    assert kwargs["message_thread_id"] == 7
    assert result.message_thread_id == 7


async def test_publish_sends_composed_html_and_disables_link_previews() -> None:
    fake = FakeBot()
    publisher, _ = _publisher(fake)
    publication = _publication(7)

    await publisher.publish(publication)

    kwargs = fake.send_message_calls[0]
    assert kwargs["text"] == publication.html_text
    preview = kwargs["link_preview_options"]
    assert isinstance(preview, LinkPreviewOptions)
    assert preview.is_disabled is True


# --- send_text / admin --------------------------------------------------------


async def test_send_text_omits_thread_for_general_and_returns_message_id() -> None:
    fake = FakeBot()
    publisher, _ = _publisher(fake)

    message_id = await publisher.send_text(CHAT_ID, "<b>ok</b>")

    kwargs = fake.send_message_calls[0]
    assert "message_thread_id" not in kwargs
    assert message_id == MESSAGE_ID


async def test_send_text_passes_thread_for_topic() -> None:
    fake = FakeBot()
    publisher, _ = _publisher(fake)

    await publisher.send_text(CHAT_ID, "text", message_thread_id=7)

    assert fake.send_message_calls[0]["message_thread_id"] == 7


async def test_send_test_into_topic_delegates_to_send_text() -> None:
    fake = FakeBot()
    _, admin = _publisher(fake)

    message_id = await admin.send_test_into_topic(CHAT_ID, 7, "<b>test</b>")

    kwargs = fake.send_message_calls[0]
    assert kwargs["message_thread_id"] == 7
    assert kwargs["text"] == "<b>test</b>"
    assert message_id == MESSAGE_ID


async def test_get_me_returns_bot_id() -> None:
    fake = FakeBot()
    _, admin = _publisher(fake)

    assert await admin.get_me() == BOT_ID


# --- capabilities -------------------------------------------------------------


async def test_capabilities_all_true_for_administrator_without_send_flags() -> None:
    fake = FakeBot(member=_administrator())
    _, admin = _publisher(fake)

    capabilities = await admin.get_chat_capabilities(CHAT_ID)

    assert fake.get_chat_member_calls == [(CHAT_ID, BOT_ID)]
    assert capabilities.can_send_text is True
    assert capabilities.can_send_photo is True
    assert capabilities.can_send_video is True
    assert capabilities.can_send_document is True
    assert capabilities.missing == ()


async def test_capabilities_default_to_allowed_for_plain_member() -> None:
    fake = FakeBot(member=ChatMemberMember(user=_user()))
    _, admin = _publisher(fake)

    capabilities = await admin.get_chat_capabilities(CHAT_ID)

    assert capabilities.missing == ()


async def test_capabilities_ignore_manage_topics_for_restricted_member() -> None:
    fake = FakeBot(member=_restricted(can_manage_topics=False))
    _, admin = _publisher(fake)

    capabilities = await admin.get_chat_capabilities(CHAT_ID)

    assert capabilities.missing == ()
    assert "can_manage_topics" not in capabilities.missing


async def test_capabilities_report_missing_in_stable_order() -> None:
    fake = FakeBot(
        member=_restricted(can_send_messages=False, can_send_videos=False, can_send_documents=False)
    )
    _, admin = _publisher(fake)

    capabilities = await admin.get_chat_capabilities(CHAT_ID)

    assert capabilities.can_send_text is False
    assert capabilities.can_send_photo is True
    assert capabilities.can_send_video is False
    assert capabilities.can_send_document is False
    assert capabilities.missing == ("can_send_text", "can_send_video", "can_send_document")


@pytest.mark.parametrize(
    "member",
    [
        ChatMemberLeft(user=_user()),
        ChatMemberBanned(user=_user(), until_date=datetime(1970, 1, 1, tzinfo=UTC)),
    ],
)
async def test_capabilities_deny_everything_for_absent_member(member: ChatMemberUnion) -> None:
    fake = FakeBot(member=member)
    _, admin = _publisher(fake)

    capabilities = await admin.get_chat_capabilities(CHAT_ID)

    assert capabilities.missing == (
        "can_send_text",
        "can_send_photo",
        "can_send_video",
        "can_send_document",
    )


def test_restricted_status_is_detected_by_value() -> None:
    assert _restricted().status == ChatMemberStatus.RESTRICTED


# --- error mapping ------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError(),
        TelegramNetworkError(_send_error(), "connection reset"),
        TelegramServerError(_send_error(), "internal"),
        TelegramRetryAfter(_send_error(), "flood", 5),
        aiohttp.ClientError("client failure"),
        aiohttp.ClientConnectionError("connection dropped"),
    ],
)
async def test_ambiguous_failures_map_to_publication_ambiguous(error: BaseException) -> None:
    fake = FakeBot(error=error)
    publisher, _ = _publisher(fake)

    with pytest.raises(PublicationAmbiguousError) as raised:
        await publisher.publish(_publication(7))

    assert isinstance(raised.value.code, str)
    assert raised.value.code


@pytest.mark.parametrize(
    "error",
    [
        TelegramBadRequest(_send_error(), "Bad Request: message thread not found"),
        TelegramForbiddenError(_send_error(), "Forbidden: bot was blocked"),
        TelegramUnauthorizedError(_send_error(), "Unauthorized"),
        TelegramConflictError(_send_error(), "Conflict"),
    ],
)
async def test_definitive_rejections_map_to_publication_rejected(error: BaseException) -> None:
    fake = FakeBot(error=error)
    publisher, _ = _publisher(fake)

    with pytest.raises(PublicationRejectedError) as raised:
        await publisher.publish(_publication(7))

    assert isinstance(raised.value.code, str)
    assert raised.value.code


async def test_send_text_maps_rejections_too() -> None:
    fake = FakeBot(error=TelegramBadRequest(_send_error(), "Bad Request: chat not found"))
    publisher, _ = _publisher(fake)

    with pytest.raises(PublicationRejectedError):
        await publisher.send_text(CHAT_ID, "hi")


@pytest.mark.parametrize(
    "description",
    [
        "Bad Request: message thread not found",
        "Bad Request: TOPIC_CLOSED",
    ],
)
async def test_unavailable_topic_rejection_has_stale_topic_code(description: str) -> None:
    fake = FakeBot(error=TelegramBadRequest(_send_error(), description))
    publisher, _ = _publisher(fake)

    with pytest.raises(PublicationRejectedError) as raised:
        await publisher.publish(_publication(7))

    assert raised.value.code == "telegram_topic_not_found"


async def test_unrelated_bad_request_does_not_get_stale_topic_code() -> None:
    fake = FakeBot(error=TelegramBadRequest(_send_error(), "Bad Request: chat not found"))
    publisher, _ = _publisher(fake)

    with pytest.raises(PublicationRejectedError) as raised:
        await publisher.publish(_publication(7))

    assert raised.value.code == "bot_api_rejected"


async def test_long_error_message_is_truncated() -> None:
    fake = FakeBot(error=TelegramBadRequest(_send_error(), "x" * 5000))
    publisher, _ = _publisher(fake)

    with pytest.raises(PublicationRejectedError) as raised:
        await publisher.publish(_publication(None))

    assert len(str(raised.value)) <= 300


async def test_cancelled_error_propagates_unchanged() -> None:
    cancelled = asyncio.CancelledError("caller cancelled")
    fake = FakeBot(error=cancelled)
    publisher, _ = _publisher(fake)

    with pytest.raises(asyncio.CancelledError) as raised:
        await publisher.publish(_publication(7))

    assert raised.value is cancelled


# --- structural conformance ---------------------------------------------------


async def test_adapters_satisfy_frozen_ports() -> None:
    fake = FakeBot(member=ChatMemberMember(user=_user()))
    publisher, admin = _publisher(fake)

    assert isinstance(publisher, TelegramPublisher)
    assert isinstance(admin, TelegramAdminPort)


# --- parse-mode contract at the Bot API boundary --------------------------------

PLAIN_REPLY = "Укажите номер темы: /set_topic <номер>. Список тем — /topics."


async def test_owner_facing_text_is_sent_without_parse_mode() -> None:
    """Owner replies must not be parsed as HTML: '<' in text stays literal."""
    fake = FakeBot()
    publisher, _ = _publisher(fake)

    await publisher.send_text(CHAT_ID, PLAIN_REPLY, message_thread_id=7)

    kwargs = fake.send_message_calls[0]
    assert kwargs["text"] == PLAIN_REPLY
    assert kwargs["parse_mode"] is None


async def test_publication_is_sent_with_html_parse_mode() -> None:
    """The escaped VK publication (author link) requires HTML parsing."""
    fake = FakeBot()
    publisher, _ = _publisher(fake)
    publication = _publication(7)

    await publisher.publish(publication)

    kwargs = fake.send_message_calls[0]
    assert kwargs["text"] == publication.html_text
    assert kwargs["parse_mode"] is ParseMode.HTML


async def test_no_default_parse_mode_bot_sends_raw_brackets_verbatim() -> None:
    """Guard the root cause: the Bot must not carry a global HTML default."""
    from config import Settings
    from vk_topic_bridge.infrastructure.telegram.bot_api_factory import create_bot

    settings = Settings.model_validate({})
    bot = create_bot(settings)
    try:
        assert bot.default.parse_mode is None
    finally:
        await bot.session.close()
