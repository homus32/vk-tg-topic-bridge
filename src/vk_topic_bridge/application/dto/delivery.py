"""DTOs for the delivery ledger, its reservation and the atomic CAS port."""

from dataclasses import dataclass
from datetime import datetime

from vk_topic_bridge.domain.enums import PublicationStatus, ReactionStatus, SourceType


@dataclass(frozen=True, slots=True)
class DeliveryRecord:
    """Decoded ``delivery_records`` row; ``telegram_message_ids`` arrives as a JSON array."""

    id: int
    source_type: str
    source_key: str
    publication_status: PublicationStatus
    reaction_status: ReactionStatus
    claim_token: str | None
    lease_expires_at: datetime | None
    send_started_at: datetime | None
    destination_chat_id: int | None
    destination_topic_id: int | None
    telegram_message_ids: tuple[int, ...]
    attempts: int
    last_error_code: str | None
    last_error: str | None
    payload_hash: str | None
    ambiguous_at: datetime | None
    review_required: bool
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    intent: str = "automatic"


@dataclass(frozen=True, slots=True)
class ReserveRequest:
    """Inputs of an idempotent reservation attempt keyed by ``(source_type, source_key)``."""

    source_type: SourceType
    source_key: str
    destination_chat_id: int | None
    destination_topic_id: int | None
    payload_hash: str | None
    intent: str = "automatic"


@dataclass(frozen=True, slots=True)
class ReserveOutcome:
    """``created=True`` for a fresh insert, otherwise the pre-existing record is returned."""

    created: bool
    record: DeliveryRecord
