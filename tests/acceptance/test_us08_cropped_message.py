"""US-08: cropped VK events are completed before any analysis.

AC-08.1 — ``is_cropped = true`` triggers an extra VK API fetch of the full message.
AC-08.2 — ``@all``, hashtags, text, attachments and the Telegram publication are all
formed from the full message, never from the cropped event.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from tests.acceptance._fakes import (
    CONVERSATION_MESSAGE_ID,
    GROUP_ID,
    PEER_ID,
    settings_from_env,
)
from vk_topic_bridge.domain.enums import AttachmentKind, SourceType
from vk_topic_bridge.domain.policies.forwarding_policy import compose_publication
from vk_topic_bridge.domain.value_objects import Attachment, Author, Destination
from vk_topic_bridge.infrastructure.vk.api import VkApiGateway

FULL_TEXT = "@all #анонс Полная версия сообщения с вложением"  # noqa: RUF001
CROPPED_TEXT = "Полная вер"
AUTHOR = Author(user_id=555, first_name="Пётр", last_name="Смирнов", screen_name=None)

CROPPED_EVENT: Mapping[str, object] = {
    "type": "message_new",
    "group_id": GROUP_ID,
    "object": {
        "peer_id": PEER_ID,
        "conversation_message_id": CONVERSATION_MESSAGE_ID,
        "text": CROPPED_TEXT,
        "is_cropped": True,
    },
}


class FakeRawVkApi:
    """VKBottle-style raw API recording every method the gateway calls."""

    def __init__(self, full_message: Mapping[str, object]) -> None:
        self.full_message = full_message
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def request(
        self, method: str, data: dict[str, object], version: str | None = None
    ) -> dict[str, object]:
        _ = version
        self.calls.append((method, data))
        if method == "messages.getByConversationMessageId":
            return {"response": {"items": [dict(self.full_message)]}}
        if method == "users.get":
            return {
                "response": [
                    {
                        "first_name": AUTHOR.first_name,
                        "last_name": AUTHOR.last_name,
                        "screen_name": "petr",
                    }
                ]
            }
        if method == "groups.getById":
            return {"response": {"groups": [{"id": GROUP_ID}]}}
        raise AssertionError(f"unexpected VK method {method}")


def _full_message_payload() -> Mapping[str, object]:
    return {
        "peer_id": PEER_ID,
        "conversation_message_id": CONVERSATION_MESSAGE_ID,
        "from_id": AUTHOR.user_id,
        "text": FULL_TEXT,
        "is_cropped": False,
        "attachments": [
            {"type": "photo", "photo": {"id": 11, "owner_id": -GROUP_ID}},
            {"type": "audio", "audio": {"id": 12, "owner_id": -GROUP_ID, "title": "voice"}},
        ],
    }


async def test_us08_ac081_cropped_event_fetches_the_full_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeRawVkApi(_full_message_payload())
    gateway = VkApiGateway(api, settings_from_env(monkeypatch))

    source = await gateway.normalize_event(
        CROPPED_EVENT,
        Author(user_id=1, first_name="Cropped", last_name="Author", screen_name=None),
    )

    methods = [method for method, _ in api.calls]
    assert "messages.getByConversationMessageId" in methods
    assert source.text == FULL_TEXT
    assert source.text != CROPPED_TEXT


async def test_us08_ac082_analysis_and_publication_use_the_full_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeRawVkApi(_full_message_payload())
    gateway = VkApiGateway(api, settings_from_env(monkeypatch))

    source = await gateway.normalize_event(
        CROPPED_EVENT,
        Author(user_id=1, first_name="Cropped", last_name="Author", screen_name=None),
    )

    assert source.has_all is True
    assert source.has_hashtag is True
    assert source.text == FULL_TEXT
    assert [attachment.kind for attachment in source.attachments] == [
        AttachmentKind.PHOTO,
        AttachmentKind.UNSUPPORTED,
    ]
    assert source.attachments[0] == Attachment(
        kind=AttachmentKind.PHOTO,
        file_name=None,
        size_bytes=None,
        source_ref=f"-{GROUP_ID}_11",
        owner_id=-GROUP_ID,
        media_id=11,
    )

    publication = compose_publication(source, Destination(chat_id=-100, message_thread_id=7))
    assert publication.html_text.split("\n\n")[1] == FULL_TEXT
    assert publication.html_text.endswith("#извк #извкважно")


async def test_us08_non_cropped_event_skips_the_extra_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeRawVkApi(_full_message_payload())
    gateway = VkApiGateway(api, settings_from_env(monkeypatch))
    plain_event: Mapping[str, object] = {
        "type": "message_new",
        "group_id": GROUP_ID,
        "object": {
            "peer_id": PEER_ID,
            "conversation_message_id": CONVERSATION_MESSAGE_ID,
            "text": "обычное сообщение #тег",
            "is_cropped": False,
        },
    }

    source = await gateway.normalize_event(plain_event, AUTHOR)

    assert [method for method, _ in api.calls] == []
    assert source.source_type is SourceType.VK_MESSAGE
    assert source.text == "обычное сообщение #тег"
    assert source.has_hashtag is True
