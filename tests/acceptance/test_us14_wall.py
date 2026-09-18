"""US-14: wall post forwarding.

AC-14.1 — a new wall post is published to the configured wall destination.
AC-14.2 — only text/photo/video/document travel.
AC-14.3 — unsupported wall attachments get warnings, the post still publishes.
AC-14.4 — the publication always contains #изстенывк and the original post link.
"""

from __future__ import annotations

from tests.acceptance._fakes import (
    WALL_OWNER_ID,
    WALL_POST_ID,
    make_wall_harness,
    make_wall_post,
)
from vk_topic_bridge.domain.enums import AttachmentKind
from vk_topic_bridge.domain.value_objects import Attachment

WALL_TOPIC_ID = 12
WALL_URL = f"https://vk.com/wall{WALL_OWNER_ID}_{WALL_POST_ID}"


async def test_us14_ac141_wall_post_publishes_to_wall_destination() -> None:
    harness = make_wall_harness(wall_topic_id=WALL_TOPIC_ID)

    outcome = await harness.use_case.execute(make_wall_post("новость сообщества"))

    assert outcome.published is True
    plan = harness.publisher.plans[0]
    assert plan.base.message_thread_id == WALL_TOPIC_ID
    record = harness.ledger.wall_record_for(make_wall_post().source_key)
    assert record.destination_topic_id == WALL_TOPIC_ID


async def test_us14_ac142_supported_wall_media_travels() -> None:
    harness = make_wall_harness()
    photo = Attachment(kind=AttachmentKind.PHOTO, file_name=None, size_bytes=1, source_ref="-9_1")
    document = Attachment(
        kind=AttachmentKind.DOCUMENT, file_name="doc.pdf", size_bytes=2, source_ref="-9_2"
    )

    outcome = await harness.use_case.execute(
        make_wall_post("с медиа", attachments=(photo, document))  # noqa: RUF001
    )

    assert outcome.published is True
    kinds = [operation.kind.value for operation in harness.publisher.plans[0].operations]
    assert "photo" in kinds
    assert "document" in kinds


async def test_us14_ac143_unsupported_wall_attachment_warns_but_publishes() -> None:
    harness = make_wall_harness()
    voice = Attachment(
        kind=AttachmentKind.UNSUPPORTED, file_name="voice.ogg", size_bytes=1, source_ref="-9_3"
    )

    outcome = await harness.use_case.execute(make_wall_post("текст", attachments=(voice,)))

    assert outcome.published is True
    assert "voice.ogg" in harness.publisher.plans[0].base.html_text


async def test_us14_ac144_publication_contains_tag_and_original_link() -> None:
    harness = make_wall_harness()

    await harness.use_case.execute(make_wall_post("новость"))

    html = harness.publisher.plans[0].base.html_text
    assert "#изстенывк" in html
    assert WALL_URL in html


async def test_us14_ac144_link_stays_when_wall_text_is_empty() -> None:
    harness = make_wall_harness()

    await harness.use_case.execute(make_wall_post(""))

    html = harness.publisher.plans[0].base.html_text
    assert WALL_URL in html
    assert "#изстенывк" in html
