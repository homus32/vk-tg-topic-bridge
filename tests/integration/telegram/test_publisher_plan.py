"""Publisher plan tests: exact Bot API calls, caption mapping, temp cleanup, taxonomy.

A recording fake Bot is injected, so no HTTP request is ever attempted. Temp files are
real files under ``tmp_path`` so cleanup can be asserted.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramServerError
from aiogram.methods import SendMediaGroup, SendMessage
from aiogram.types import (
    FSInputFile,
    InputMediaPhoto,
)

from vk_topic_bridge.application.forwarding.publication_planning import plan_publication
from vk_topic_bridge.domain.enums import SourceType
from vk_topic_bridge.domain.publication import (
    OperationKind,
    OperationStatus,
    PlannedMedia,
    PublicationOperation,
    PublicationPlan,
)
from vk_topic_bridge.domain.value_objects import Author, Publication, SourceMessage
from vk_topic_bridge.infrastructure.telegram.publisher import BotApiPublisher

CHAT_ID = -1001234567890
THREAD_ID = 7
MESSAGE_ID = 501


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


def _publication(text: str, thread: int | None = THREAD_ID) -> Publication:
    return Publication(
        chat_id=CHAT_ID,
        message_thread_id=thread,
        html_text=text,
        has_all=False,
        source=_source(),
    )


class FakeMessage:
    def __init__(self, message_id: int) -> None:
        self.message_id = message_id


class FakeBot:
    """Records every Bot API call; per-method configurable errors."""

    def __init__(self) -> None:
        self.errors: dict[str, BaseException] = {}
        self.send_message_calls: list[dict[str, object]] = []
        self.send_photo_calls: list[dict[str, object]] = []
        self.send_video_calls: list[dict[str, object]] = []
        self.send_document_calls: list[dict[str, object]] = []
        self.send_media_group_calls: list[dict[str, object]] = []

    async def send_message(self, **kwargs: object) -> FakeMessage:
        self.send_message_calls.append(kwargs)
        error = self.errors.get("send_message")
        if error is not None:
            raise error
        return FakeMessage(MESSAGE_ID + len(self.send_message_calls) - 1)

    async def send_photo(self, **kwargs: object) -> FakeMessage:
        self.send_photo_calls.append(kwargs)
        error = self.errors.get("send_photo")
        if error is not None:
            raise error
        return FakeMessage(MESSAGE_ID)

    async def send_video(self, **kwargs: object) -> FakeMessage:
        self.send_video_calls.append(kwargs)
        error = self.errors.get("send_video")
        if error is not None:
            raise error
        return FakeMessage(MESSAGE_ID)

    async def send_document(self, **kwargs: object) -> FakeMessage:
        self.send_document_calls.append(kwargs)
        error = self.errors.get("send_document")
        if error is not None:
            raise error
        return FakeMessage(MESSAGE_ID)

    async def send_media_group(self, **kwargs: object) -> list[FakeMessage]:
        self.send_media_group_calls.append(kwargs)
        error = self.errors.get("send_media_group")
        if error is not None:
            raise error
        return [FakeMessage(MESSAGE_ID), FakeMessage(MESSAGE_ID + 1)]


def _publisher(fake: FakeBot) -> BotApiPublisher:
    return BotApiPublisher(cast(Bot, fake))


def _media_files(
    tmp_path: Path, count: int, kind: OperationKind = OperationKind.PHOTO
) -> list[PlannedMedia]:
    items: list[PlannedMedia] = []
    for index in range(count):
        path = tmp_path / f"media-{index}.bin"
        path.write_bytes(b"payload")
        items.append(PlannedMedia(kind=kind, file_path=str(path), file_name=f"file-{index}.bin"))
    return items


# --- TEXT operations ------------------------------------------------------------


async def test_text_operation_calls_send_message_html_and_returns_outcome() -> None:
    fake = FakeBot()
    publisher = _publisher(fake)
    plan = PublicationPlan(
        base=_publication("t"),
        operations=(PublicationOperation(kind=OperationKind.TEXT, text="<b>x</b>", position=0),),
    )

    outcomes = await publisher.publish_plan(plan)

    kwargs = fake.send_message_calls[0]
    assert kwargs["chat_id"] == CHAT_ID
    assert kwargs["message_thread_id"] == THREAD_ID
    assert kwargs["text"] == "<b>x</b>"
    assert kwargs["parse_mode"] is ParseMode.HTML
    assert outcomes[0].status is OperationStatus.PUBLISHED
    assert outcomes[0].message_ids == (MESSAGE_ID,)


async def test_general_destination_omits_thread_id() -> None:
    fake = FakeBot()
    publisher = _publisher(fake)
    plan = plan_publication(_publication("t", thread=None), ())

    await publisher.publish_plan(plan)

    assert "message_thread_id" not in fake.send_message_calls[0]


# --- single media operations ------------------------------------------------------


async def test_single_photo_uses_fs_input_file_and_caption(tmp_path: Path) -> None:
    fake = FakeBot()
    publisher = _publisher(fake)
    media = _media_files(tmp_path, 1)
    plan = plan_publication(_publication("qw"), media)

    outcomes = await publisher.publish_plan(plan)

    kwargs = fake.send_photo_calls[0]
    photo = kwargs["photo"]
    assert isinstance(photo, FSInputFile)
    assert kwargs["caption"] == "qw"
    assert kwargs["parse_mode"] is ParseMode.HTML
    assert outcomes[0].status is OperationStatus.PUBLISHED
    assert not Path(media[0].file_path).exists()


async def test_single_document_uses_send_document(tmp_path: Path) -> None:
    fake = FakeBot()
    publisher = _publisher(fake)
    media = _media_files(tmp_path, 1, kind=OperationKind.DOCUMENT)
    plan = plan_publication(_publication(""), media)

    await publisher.publish_plan(plan)

    assert len(fake.send_document_calls) == 1
    assert fake.send_document_calls[0]["document"] is not None
    assert not Path(media[0].file_path).exists()


# --- media groups ------------------------------------------------------------------


async def test_media_group_maps_items_in_order_with_first_item_caption(tmp_path: Path) -> None:
    fake = FakeBot()
    publisher = _publisher(fake)
    media = _media_files(tmp_path, 3)
    plan = PublicationPlan(
        base=_publication("cap"),
        operations=(
            PublicationOperation(
                kind=OperationKind.MEDIA_GROUP,
                text="cap",
                position=0,
                media=tuple(media),
            ),
        ),
    )

    outcomes = await publisher.publish_plan(plan)

    kwargs = fake.send_media_group_calls[0]
    items = kwargs["media"]
    assert isinstance(items, list)
    assert all(isinstance(item, InputMediaPhoto) for item in items)
    assert items[0].caption == "cap"
    assert items[0].parse_mode == ParseMode.HTML.value
    assert all(item.caption is None for item in items[1:])
    assert outcomes[0].message_ids == (MESSAGE_ID, MESSAGE_ID + 1)
    assert all(not Path(item.file_path).exists() for item in media)


async def test_media_group_without_caption_sends_captionless(tmp_path: Path) -> None:
    fake = FakeBot()
    publisher = _publisher(fake)
    media = _media_files(tmp_path, 2)
    plan = plan_publication(_publication("x" * 2000), media)

    await publisher.publish_plan(plan)

    items = fake.send_media_group_calls[0]["media"]
    assert isinstance(items, list)
    assert all(item.caption is None for item in items)


# --- failure taxonomy per operation --------------------------------------------------


async def test_rejected_operation_is_failed_permanent_and_others_continue(tmp_path: Path) -> None:
    fake = FakeBot()
    fake.errors["send_media_group"] = TelegramBadRequest(
        SendMediaGroup(chat_id=CHAT_ID, media=[]), "Bad Request"
    )
    publisher = _publisher(fake)
    photo_dir = tmp_path / "photos"
    photo_dir.mkdir()
    doc_dir = tmp_path / "docs"
    doc_dir.mkdir()
    photos = _media_files(photo_dir, 2)
    documents = _media_files(doc_dir, 1, kind=OperationKind.DOCUMENT)
    plan = PublicationPlan(
        base=_publication("" * 0),
        operations=(
            PublicationOperation(
                kind=OperationKind.MEDIA_GROUP, text=None, position=0, media=tuple(photos)
            ),
            PublicationOperation(
                kind=OperationKind.DOCUMENT, text=None, position=1, media=(documents[0],)
            ),
        ),
    )

    outcomes = await publisher.publish_plan(plan)

    assert outcomes[0].status is OperationStatus.FAILED_PERMANENT
    assert outcomes[0].error_code == "bot_api_rejected"
    assert outcomes[1].status is OperationStatus.PUBLISHED
    assert not Path(documents[0].file_path).exists()
    assert all(not Path(photo.file_path).exists() for photo in photos)


async def test_ambiguous_operation_maps_to_accepted_unknown(tmp_path: Path) -> None:
    fake = FakeBot()
    fake.errors["send_message"] = TelegramServerError(
        SendMessage(chat_id=CHAT_ID, text="x"), "internal"
    )
    publisher = _publisher(fake)
    plan = plan_publication(_publication("t"), ())

    outcomes = await publisher.publish_plan(plan)

    assert outcomes[0].status is OperationStatus.ACCEPTED_UNKNOWN
    assert outcomes[0].error_code == "bot_api_server"


async def test_unexpected_error_propagates_unchanged() -> None:
    fake = FakeBot()
    fake.errors["send_message"] = ValueError("bug")
    publisher = _publisher(fake)
    plan = plan_publication(_publication("t"), ())

    with pytest.raises(ValueError, match="bug"):
        await publisher.publish_plan(plan)


# --- ordering --------------------------------------------------------------------


async def test_operations_execute_in_plan_order(tmp_path: Path) -> None:
    fake = FakeBot()
    publisher = _publisher(fake)
    media = _media_files(tmp_path, 1)
    plan = plan_publication(_publication("x" * 2000), media)

    outcomes = await publisher.publish_plan(plan)

    assert [outcome.operation.kind for outcome in outcomes] == [
        OperationKind.TEXT,
        OperationKind.PHOTO,
    ]
