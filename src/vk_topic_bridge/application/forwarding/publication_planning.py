"""Publication planning: composed text + downloaded media -> ordered operations.

Pure application/domain composition: no SDK imports, no I/O. The plan is executed by
the ``TelegramPublisherPlan.publish_plan`` port; per-operation outcomes roll up into a
``PublicationPlanResult`` with partial-success semantics.

Flow contract (frozen): downloads happen BEFORE planning. Attachments that failed to
download never reach the planner — the use case already turned them into per-item
warning lines inside the text (docs/03 §12.4/12.5). The planner only sees successfully
downloaded ``PlannedMedia``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from vk_topic_bridge.application.forwarding.composition import split_text_safely
from vk_topic_bridge.domain.publication import (
    OperationKind,
    PlannedMedia,
    PublicationOperation,
    PublicationPlan,
)
from vk_topic_bridge.domain.value_objects import Publication

_TELEGRAM_TEXT_LIMIT = 4096
_TELEGRAM_CAPTION_LIMIT = 1024
_GROUPABLE_KINDS = frozenset({OperationKind.PHOTO, OperationKind.VIDEO})
_MAX_MEDIA_GROUP_SIZE = 10


def plan_publication(
    publication: Publication, media: Sequence[PlannedMedia] = ()
) -> PublicationPlan:
    """Split one composed publication into ordered Telegram operations.

    Caption branch: full text ≤1024 with media → text becomes the caption of the first
    media operation, no TEXT operations. Otherwise the full text is emitted as TEXT
    operations ≤4096 at safe boundaries and media stays captionless. Consecutive
    PHOTO/VIDEO items form MEDIA_GROUP operations of 2..10 items (freely mixed — the
    Bot API same-type-only rule covers documents and audio, not product media); a
    one-item chunk stays a single PHOTO/VIDEO operation because ``sendMediaGroup``
    requires 2..10 items. Documents never group. Positions are zero-based.
    """
    text = publication.html_text
    operations: list[PublicationOperation] = []

    caption_on_first_media = bool(media) and bool(text) and len(text) <= _TELEGRAM_CAPTION_LIMIT
    if text and not caption_on_first_media:
        for chunk in split_text_safely(text, _TELEGRAM_TEXT_LIMIT):
            operations.append(PublicationOperation(kind=OperationKind.TEXT, text=chunk, position=0))

    for chunk in _chunk_media(media):
        operations.append(
            PublicationOperation(
                kind=chunk[0].kind if len(chunk) == 1 else OperationKind.MEDIA_GROUP,
                text=None,
                position=0,
                media=tuple(chunk),
            )
        )

    if caption_on_first_media:
        operations[0] = replace(operations[0], text=text)

    return PublicationPlan(
        base=publication,
        operations=tuple(
            replace(operation, position=position) for position, operation in enumerate(operations)
        ),
    )


def _chunk_media(media: Sequence[PlannedMedia]) -> list[list[PlannedMedia]]:
    """Chunk media in order: PHOTO/VIDEO runs ≤10, documents one per chunk."""
    chunks: list[list[PlannedMedia]] = []
    run: list[PlannedMedia] = []
    for item in media:
        if item.kind in _GROUPABLE_KINDS:
            run.append(item)
            if len(run) == _MAX_MEDIA_GROUP_SIZE:
                chunks.append(run)
                run = []
            continue
        if run:
            chunks.append(run)
            run = []
        chunks.append([item])
    if run:
        chunks.append(run)
    return chunks
