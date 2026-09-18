"""US-12: unsupported attachments are named explicitly, one warning each.

AC-12.1 — voice/audio/video-message kinds are unsupported.
AC-12.2 — every skipped attachment gets its own clear warning.
AC-12.3 — several unsupported attachments are not collapsed into one phrase.
"""

from __future__ import annotations

from tests.acceptance._fakes import make_forwarding_harness, make_source
from vk_topic_bridge.domain.enums import AttachmentKind
from vk_topic_bridge.domain.value_objects import Attachment

VOICE = Attachment(
    kind=AttachmentKind.UNSUPPORTED, file_name="voice.ogg", size_bytes=1024, source_ref="-1_20"
)
AUDIO = Attachment(
    kind=AttachmentKind.UNSUPPORTED, file_name="track.mp3", size_bytes=2048, source_ref="-1_21"
)
ROUND_VIDEO = Attachment(
    kind=AttachmentKind.UNSUPPORTED, file_name="circle.mp4", size_bytes=4096, source_ref="-1_22"
)


async def test_us12_ac121_unsupported_kinds_are_skipped() -> None:
    harness = make_forwarding_harness()

    await harness.use_case.execute(make_source("@all голосовое", attachments=(VOICE,)))

    assert harness.downloader.downloaded == []
    kinds = [operation.kind.value for operation in harness.publisher.plans[0].operations]
    assert kinds == ["text"]


async def test_us12_ac122_each_unsupported_attachment_is_named() -> None:
    harness = make_forwarding_harness()

    await harness.use_case.execute(make_source("@all вложения", attachments=(VOICE, AUDIO)))

    html = harness.publisher.plans[0].base.html_text
    assert "voice.ogg" in html
    assert "track.mp3" in html


async def test_us12_ac123_warnings_are_not_collapsed() -> None:
    harness = make_forwarding_harness()

    await harness.use_case.execute(
        make_source("@all вложения", attachments=(VOICE, AUDIO, ROUND_VIDEO))
    )

    html = harness.publisher.plans[0].base.html_text
    assert html.count("не поддерживается") == 3
    lines = [line for line in html.splitlines() if "не поддерживается" in line]
    assert len(lines) == 3
