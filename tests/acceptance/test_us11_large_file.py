"""US-11: a file over 50 MB is not uploaded and the reason is explained.

AC-11.1 — an oversized document is never uploaded to Telegram.
AC-11.2 — the publication names the file, the 50 MB limit and the VK fallback hint.
"""

from __future__ import annotations

from tests.acceptance._fakes import make_forwarding_harness, make_source
from vk_topic_bridge.domain.enums import AttachmentKind
from vk_topic_bridge.domain.value_objects import Attachment

OVERSIZED = Attachment(
    kind=AttachmentKind.DOCUMENT,
    file_name="huge.zip",
    size_bytes=60 * 1024 * 1024,
    source_ref="-1_77",
)
WITHIN_LIMIT = Attachment(
    kind=AttachmentKind.DOCUMENT,
    file_name="small.zip",
    size_bytes=49 * 1024 * 1024,
    source_ref="-1_78",
)


async def test_us11_ac111_oversized_document_is_never_downloaded_or_uploaded() -> None:
    harness = make_forwarding_harness()

    outcome = await harness.use_case.execute(
        make_source("@all большой файл", attachments=(OVERSIZED,))
    )

    assert outcome.published is True
    assert harness.downloader.downloaded == []
    kinds = [operation.kind.value for operation in harness.publisher.plans[0].operations]
    assert "document" not in kinds


async def test_us11_ac112_publication_explains_name_limit_and_vk_hint() -> None:
    harness = make_forwarding_harness()

    await harness.use_case.execute(make_source("@all большой файл", attachments=(OVERSIZED,)))

    html = harness.publisher.plans[0].base.html_text
    assert "huge.zip" in html
    assert "50 МБ" in html


async def test_us11_ac111_document_within_limit_is_transferred() -> None:
    harness = make_forwarding_harness()

    await harness.use_case.execute(make_source("@all ок файл", attachments=(WITHIN_LIMIT,)))

    assert harness.downloader.downloaded == ["-1_78"]
    kinds = [operation.kind.value for operation in harness.publisher.plans[0].operations]
    assert "document" in kinds
