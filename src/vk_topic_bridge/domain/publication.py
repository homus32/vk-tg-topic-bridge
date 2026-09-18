"""Multi-operation publication model: one logical publication, many Telegram calls.

The frozen draft requires ordered per-operation results with partial-success semantics:
a logical publication is successful when any Telegram message containing text or
warnings was created, even if every media attachment failed. Each operation records its
own fail-closed outcome; ``ambiguous`` is never auto-retried.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from vk_topic_bridge.domain.value_objects import Publication


class OperationKind(StrEnum):
    """One Telegram Bot API call family inside a logical publication."""

    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"
    MEDIA_GROUP = "media_group"


class OperationStatus(StrEnum):
    """Fail-closed outcome of one Telegram call.

    Mapping to the persisted delivery ledger (frozen schema keeps six statuses):
    ``PUBLISHED``/``PARTIALLY_PUBLISHED`` logical states roll up to ``published``;
    ``ACCEPTED_UNKNOWN`` persists as ``ambiguous`` (never auto-retried);
    ``FAILED_RETRYABLE`` persists as ``failed_before_send`` (claim released);
    ``FAILED_PERMANENT`` persists as ``failed_permanent``.
    """

    PUBLISHED = "published"
    PARTIALLY_PUBLISHED = "partially_published"
    ACCEPTED_UNKNOWN = "accepted_unknown"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_PERMANENT = "failed_permanent"


@dataclass(frozen=True, slots=True)
class PublicationOperation:
    """One planned Telegram call; ``text`` is pre-escaped HTML when applicable.

    TODO(finish): ``media`` is empty for TEXT operations and carries the operation's
    files otherwise: exactly 1 item for PHOTO/VIDEO/DOCUMENT, up to 10 for
    MEDIA_GROUP. In the caption branch the full publication text becomes the caption
    of the FIRST media operation: ``text`` holds the pre-escaped HTML caption there
    (publisher maps it to ``caption=`` with ``parse_mode=HTML``; on MEDIA_GROUP only
    the first InputMedia item gets the caption, remaining items are captionless).
    TEXT operations are the only other operations with ``text != None``. The publisher
    deletes every ``item.file_path`` of the operation after it completes.
    """

    kind: OperationKind
    text: str | None
    position: int
    media: tuple[PlannedMedia, ...] = ()


@dataclass(frozen=True, slots=True)
class PlannedMedia:
    """Successfully downloaded media offered to the planner (flow: download first).

    TODO(finish): built by the forwarding use case after the media-prep phase;
    attachments that failed to download never appear here — they became per-item
    warning lines in the publication text instead (docs/03 §12.4/12.5). ``kind`` is
    restricted to PHOTO/VIDEO/DOCUMENT.
    """

    kind: OperationKind
    file_path: str
    file_name: str | None


@dataclass(frozen=True, slots=True)
class OperationOutcome:
    """Confirmed result of one executed operation; ``message_ids`` may be empty."""

    operation: PublicationOperation
    status: OperationStatus
    message_ids: tuple[int, ...]
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class PublicationPlan:
    """Ordered operations derived from one source publication and its attachments."""

    base: Publication
    operations: tuple[PublicationOperation, ...]


@dataclass(frozen=True, slots=True)
class PublicationPlanResult:
    """Roll-up of every executed operation for one logical publication.

    TODO(finish): ``is_delivery_success`` must be ``True`` iff at least one operation
    reached ``PUBLISHED`` or ``PARTIALLY_PUBLISHED`` (text and/or warnings delivered),
    mirroring the owner partial-success decision. Aggregate status rules:
    all operations published -> ``PUBLISHED``; at least one published and at least one
    failed/unknown -> ``PARTIALLY_PUBLISHED``; any ``ACCEPTED_UNKNOWN`` with nothing
    published -> ``ACCEPTED_UNKNOWN``; only retryable failures -> ``FAILED_RETRYABLE``;
    any permanent failure with nothing published -> ``FAILED_PERMANENT``.
    """

    outcomes: tuple[OperationOutcome, ...]

    @property
    def is_delivery_success(self) -> bool:
        return any(
            outcome.status in (OperationStatus.PUBLISHED, OperationStatus.PARTIALLY_PUBLISHED)
            for outcome in self.outcomes
        )
