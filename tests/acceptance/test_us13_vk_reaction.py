"""US-13: 👍 on the original VK message exactly when a publication was created.

AC-13.1 — successful publication ⇒ reaction is set.
AC-13.2 — partial attachment success (some attachments skipped) still reacts.
AC-13.3 — no publication ⇒ no reaction.
"""

from __future__ import annotations

from tests.acceptance._fakes import (
    CONVERSATION_MESSAGE_ID,
    PEER_ID,
    SOURCE_KEY,
    make_forwarding_harness,
    make_source,
)
from vk_topic_bridge.application.errors import PublicationAmbiguousError, PublicationRejectedError
from vk_topic_bridge.domain.enums import AttachmentKind
from vk_topic_bridge.domain.value_objects import Attachment

EXPECTED_REACTION = (PEER_ID, CONVERSATION_MESSAGE_ID)

SKIPPED_ATTACHMENT = Attachment(
    kind=AttachmentKind.UNSUPPORTED, file_name="voice.ogg", size_bytes=1024, source_ref="-1_9"
)
PHOTO_ATTACHMENT = Attachment(
    kind=AttachmentKind.PHOTO, file_name=None, size_bytes=None, source_ref="-1_10"
)


async def test_us13_ac131_successful_publication_sets_the_reaction() -> None:
    harness = make_forwarding_harness()

    outcome = await harness.use_case.execute(make_source("@all важное"))

    assert outcome.published is True
    assert harness.vk.reaction_calls == [EXPECTED_REACTION]
    record = harness.ledger.record_for(SOURCE_KEY)
    assert record.reaction_status.value == "succeeded"


async def test_us13_ac132_partial_attachment_success_still_reacts() -> None:
    harness = make_forwarding_harness()
    source = make_source(
        "#новость с вложениями",
        attachments=(PHOTO_ATTACHMENT, SKIPPED_ATTACHMENT),
    )

    outcome = await harness.use_case.execute(source)

    assert outcome.published is True
    assert len(harness.publisher.publications) == 1
    assert harness.vk.reaction_calls == [EXPECTED_REACTION]


async def test_us13_ac133_failed_publication_sets_no_reaction() -> None:
    harness = make_forwarding_harness(
        publisher_error=PublicationRejectedError("message thread not found", code="thread")
    )

    outcome = await harness.use_case.execute(make_source("@all важное"))

    assert outcome.published is False
    assert harness.vk.reaction_calls == []
    assert harness.ledger.record_for(SOURCE_KEY).reaction_status.value == "not_due"


async def test_us13_ac133_ambiguous_publication_sets_no_reaction() -> None:
    harness = make_forwarding_harness(publisher_error=PublicationAmbiguousError("timeout"))

    outcome = await harness.use_case.execute(make_source("@all важное"))

    assert outcome.reason == "ambiguous"
    assert harness.vk.reaction_calls == []
    assert harness.ledger.record_for(SOURCE_KEY).reaction_status.value == "not_due"


async def test_us13_ac133_filtered_message_sets_no_reaction() -> None:
    harness = make_forwarding_harness(auto_forward_all=False, auto_forward_hashtags=False)

    outcome = await harness.use_case.execute(make_source("@all #важное"))

    assert outcome.skipped is True
    assert harness.vk.reaction_calls == []
    assert harness.ledger.records == {}


async def test_us13_reaction_failure_does_not_undo_the_publication() -> None:
    harness = make_forwarding_harness(vk_error=RuntimeError("reaction rejected"))

    outcome = await harness.use_case.execute(make_source("@all важное"))

    assert outcome.published is True
    assert len(harness.publisher.publications) == 1
    assert harness.vk.reaction_calls == [EXPECTED_REACTION]
    assert harness.ledger.record_for(SOURCE_KEY).reaction_status.value == "failed"


async def test_us13_duplicate_delivery_does_not_repeat_the_reaction() -> None:
    harness = make_forwarding_harness()
    source = make_source("@all важное")

    await harness.use_case.execute(source)
    await harness.use_case.execute(source)

    assert harness.vk.reaction_calls == [EXPECTED_REACTION]
    assert len(harness.publisher.publications) == 1
