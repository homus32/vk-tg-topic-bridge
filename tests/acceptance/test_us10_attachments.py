"""US-10: attachments travel with the message.

AC-10.1 — photo/video/document up to 50 MB are supported.
AC-10.2 — one attachment failure does not cancel the text or the other attachments.
AC-10.3 — every impossible attachment gets its own warning line in the publication.
"""

from __future__ import annotations

from tests.acceptance._fakes import make_forwarding_harness, make_source
from vk_topic_bridge.domain.enums import AttachmentKind
from vk_topic_bridge.domain.value_objects import Attachment

PHOTO = Attachment(kind=AttachmentKind.PHOTO, file_name=None, size_bytes=1024, source_ref="-1_10")
VIDEO = Attachment(kind=AttachmentKind.VIDEO, file_name=None, size_bytes=2048, source_ref="-1_11")
DOCUMENT = Attachment(
    kind=AttachmentKind.DOCUMENT, file_name="report.pdf", size_bytes=4096, source_ref="-1_12"
)


async def test_us10_ac101_supported_attachments_become_media_operations() -> None:
    harness = make_forwarding_harness()

    outcome = await harness.use_case.execute(
        make_source("@all с вложениями", attachments=(PHOTO, VIDEO, DOCUMENT))
    )

    assert outcome.published is True
    assert harness.downloader.downloaded == ["-1_10", "-1_11", "-1_12"]
    kinds = [operation.kind.value for operation in harness.publisher.plans[0].operations]
    assert "media_group" in kinds
    assert "document" in kinds


async def test_us10_ac102_one_failed_attachment_does_not_cancel_the_rest() -> None:
    harness = make_forwarding_harness(downloader_fail_refs=frozenset({"-1_11"}))

    outcome = await harness.use_case.execute(
        make_source("@all с вложениями", attachments=(PHOTO, VIDEO, DOCUMENT))
    )

    assert outcome.published is True
    html = harness.publisher.plans[0].base.html_text
    assert "не удалось перенести" in html
    assert harness.downloader.downloaded == ["-1_10", "-1_12"]


async def test_us10_ac103_each_failed_attachment_gets_its_own_line() -> None:
    harness = make_forwarding_harness(downloader_fail_refs=frozenset({"-1_1", "-1_2"}))
    first = Attachment(
        kind=AttachmentKind.PHOTO, file_name="a.jpg", size_bytes=1, source_ref="-1_1"
    )
    second = Attachment(
        kind=AttachmentKind.DOCUMENT, file_name="b.pdf", size_bytes=2, source_ref="-1_2"
    )

    await harness.use_case.execute(make_source("@all медиа", attachments=(first, second)))

    html = harness.publisher.plans[0].base.html_text
    assert "a.jpg" in html
    assert "b.pdf" in html
    assert html.count("не удалось перенести") == 2
