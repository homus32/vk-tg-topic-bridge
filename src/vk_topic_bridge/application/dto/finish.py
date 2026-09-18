"""DTOs added by the finish plan (append-only)."""

from __future__ import annotations

from dataclasses import dataclass

from vk_topic_bridge.application.dto.delivery import DeliveryRecord
from vk_topic_bridge.application.dto.settings import DestinationKind

__all__ = [
    "DeliveryReviewEntry",
    "DestinationKind",
    "HistoryGapEvent",
    "delivery_review_entry",
]


@dataclass(frozen=True, slots=True)
class DeliveryReviewEntry:
    """One owner-visible diagnostics row (compact 'Диагностика доставки' view)."""

    delivery_id: int
    status: str
    source_type: str
    source_key: str
    destination_chat_id: int | None
    destination_topic_id: int | None
    attempts: int
    last_error_code: str | None
    last_error: str | None
    created_at: str | None
    ambiguous_at: str | None
    telegram_message_ids: tuple[int, ...] = ()
    review_required: bool = False


def delivery_review_entry(record: DeliveryRecord) -> DeliveryReviewEntry:
    """Project a ledger row into the owner-facing diagnostics row."""
    return DeliveryReviewEntry(
        delivery_id=record.id,
        status=record.publication_status.value,
        source_type=record.source_type,
        source_key=record.source_key,
        destination_chat_id=record.destination_chat_id,
        destination_topic_id=record.destination_topic_id,
        attempts=record.attempts,
        last_error_code=record.last_error_code,
        last_error=record.last_error,
        created_at=record.created_at.isoformat() if record.created_at is not None else None,
        ambiguous_at=record.ambiguous_at.isoformat() if record.ambiguous_at is not None else None,
        telegram_message_ids=record.telegram_message_ids,
        review_required=record.review_required,
    )


@dataclass(frozen=True, slots=True)
class HistoryGapEvent:
    """Owner-notifiable outcome of a VK Long Poll history gap (failed=1/3).

    ``discarded_count`` is always ``None``: VK never provides a reliable count and the
    product must never fabricate one.
    """

    gap_kind: str
    discarded_count: None = None
