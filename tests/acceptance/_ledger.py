"""Stateful in-memory delivery ledger for acceptance tests.

Mirrors the CAS rules of ``DeliveryRepository`` (plan §6): claim tokens, lease
liveness, illegal-transition rejection, and send intent committed before any send.
No network and no SQLite are involved.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from vk_topic_bridge.application.dto.delivery import (
    DeliveryRecord,
    ReserveOutcome,
    ReserveRequest,
)
from vk_topic_bridge.domain.enums import PublicationStatus, ReactionStatus, SourceType

_RETRYABLE = (PublicationStatus.RESERVED, PublicationStatus.FAILED_BEFORE_SEND)
_NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


def blank_record(source_type: str, source_key: str) -> DeliveryRecord:
    """Fresh ``reserved`` row before any claim or send intent."""
    return DeliveryRecord(
        id=0,
        source_type=source_type,
        source_key=source_key,
        publication_status=PublicationStatus.RESERVED,
        reaction_status=ReactionStatus.NOT_DUE,
        claim_token=None,
        lease_expires_at=None,
        send_started_at=None,
        destination_chat_id=None,
        destination_topic_id=None,
        telegram_message_ids=(),
        attempts=0,
        last_error_code=None,
        last_error=None,
        payload_hash=None,
        ambiguous_at=None,
        review_required=False,
        created_at=_NOW,
        updated_at=_NOW,
        completed_at=None,
    )


def ledger_key(source_type: SourceType, source_key: str) -> str:
    return f"{source_type.value}:{source_key}"


class DeliveryLedger:
    """In-memory ``DeliveryRepository`` with the real CAS semantics."""

    def __init__(self) -> None:
        self.records: dict[str, DeliveryRecord] = {}
        self.deny_send_started = False
        self._next_id = 1

    def seed(
        self,
        *,
        status: PublicationStatus,
        source_key: str = "111:222:333",
        claim_token: str | None = None,
        lease_expires_at: datetime | None = None,
        reaction_status: ReactionStatus = ReactionStatus.NOT_DUE,
        message_ids: tuple[int, ...] = (),
    ) -> DeliveryRecord:
        record = replace(
            blank_record(SourceType.VK_MESSAGE.value, source_key),
            id=self._next_id,
            publication_status=status,
            reaction_status=reaction_status,
            claim_token=claim_token,
            lease_expires_at=lease_expires_at,
            telegram_message_ids=message_ids,
        )
        self._next_id += 1
        self.records[ledger_key(SourceType.VK_MESSAGE, source_key)] = record
        return record

    def record_for(self, source_key: str) -> DeliveryRecord:
        """Return the stored row for a message source key, failing the test if absent."""
        record = self.records.get(ledger_key(SourceType.VK_MESSAGE, source_key))
        assert record is not None, f"delivery record {source_key!r} must exist"
        return record

    async def reserve(self, request: ReserveRequest) -> ReserveOutcome:
        key = ledger_key(request.source_type, request.source_key)
        existing = self.records.get(key)
        if existing is not None:
            return ReserveOutcome(created=False, record=existing)
        record = replace(
            blank_record(request.source_type.value, request.source_key),
            id=self._next_id,
            destination_chat_id=request.destination_chat_id,
            destination_topic_id=request.destination_topic_id,
            payload_hash=request.payload_hash,
        )
        self._next_id += 1
        self.records[key] = record
        return ReserveOutcome(created=True, record=record)

    async def claim_reserved(self, delivery_id: int, claim_token: str, lease_seconds: int) -> bool:
        key, record = self._find(delivery_id)
        if record.publication_status not in _RETRYABLE:
            return False
        if record.claim_token is not None and self._lease_is_live(record):
            return False
        self._write(
            key,
            replace(
                record,
                claim_token=claim_token,
                lease_expires_at=datetime.now(UTC) + timedelta(seconds=lease_seconds),
                attempts=record.attempts + 1,
            ),
        )
        return True

    async def mark_send_started(self, delivery_id: int, claim_token: str) -> bool:
        if self.deny_send_started:
            return False
        key, record = self._find(delivery_id)
        if record.claim_token != claim_token or record.publication_status not in _RETRYABLE:
            return False
        self._write(
            key,
            replace(
                record,
                publication_status=PublicationStatus.SEND_STARTED,
                send_started_at=datetime.now(UTC),
            ),
        )
        return True

    async def mark_published(
        self, delivery_id: int, claim_token: str, message_ids: Sequence[int]
    ) -> bool:
        key, record = self._find(delivery_id)
        if record.claim_token != claim_token:
            return False
        if record.publication_status is not PublicationStatus.SEND_STARTED:
            return False
        self._write(
            key,
            replace(
                record,
                publication_status=PublicationStatus.PUBLISHED,
                telegram_message_ids=tuple(message_ids),
                completed_at=datetime.now(UTC),
            ),
        )
        return True

    async def mark_publication_ambiguous(
        self, delivery_id: int, claim_token: str, code: str | None, message: str | None
    ) -> bool:
        key, record = self._find(delivery_id)
        if record.claim_token != claim_token:
            return False
        if record.publication_status is not PublicationStatus.SEND_STARTED:
            return False
        self._write(
            key,
            replace(
                record,
                publication_status=PublicationStatus.AMBIGUOUS,
                ambiguous_at=datetime.now(UTC),
                review_required=True,
                last_error_code=code,
                last_error=message,
            ),
        )
        return True

    async def mark_failed_before_send(
        self, delivery_id: int, claim_token: str, code: str | None, message: str | None
    ) -> bool:
        key, record = self._find(delivery_id)
        if record.claim_token != claim_token or record.publication_status not in _RETRYABLE:
            return False
        self._write(
            key,
            replace(
                record,
                publication_status=PublicationStatus.FAILED_BEFORE_SEND,
                last_error_code=code,
                last_error=message,
            ),
        )
        return True

    async def mark_failed_permanent(
        self, delivery_id: int, claim_token: str, code: str | None, message: str | None
    ) -> bool:
        key, record = self._find(delivery_id)
        if record.claim_token != claim_token:
            return False
        if record.publication_status is not PublicationStatus.SEND_STARTED:
            return False
        self._write(
            key,
            replace(
                record,
                publication_status=PublicationStatus.FAILED_PERMANENT,
                last_error_code=code,
                last_error=message,
                completed_at=datetime.now(UTC),
            ),
        )
        return True

    async def claim_reaction(self, delivery_id: int) -> bool:
        key, record = self._find(delivery_id)
        if record.publication_status is not PublicationStatus.PUBLISHED:
            return False
        if record.reaction_status not in (ReactionStatus.NOT_DUE, ReactionStatus.FAILED):
            return False
        self._write(key, replace(record, reaction_status=ReactionStatus.PENDING))
        return True

    async def mark_reaction_succeeded(self, delivery_id: int) -> bool:
        key, record = self._find(delivery_id)
        if record.reaction_status is not ReactionStatus.PENDING:
            return False
        self._write(key, replace(record, reaction_status=ReactionStatus.SUCCEEDED))
        return True

    async def mark_reaction_failed(
        self, delivery_id: int, code: str | None, message: str | None
    ) -> bool:
        key, record = self._find(delivery_id)
        if record.reaction_status is not ReactionStatus.PENDING:
            return False
        self._write(
            key,
            replace(
                record,
                reaction_status=ReactionStatus.FAILED,
                last_error_code=code,
                last_error=message,
            ),
        )
        return True

    async def get(self, source_type: SourceType, source_key: str) -> DeliveryRecord | None:
        return self.records.get(ledger_key(source_type, source_key))

    async def list_pending_reactions(self) -> list[DeliveryRecord]:
        return [
            record
            for record in self.records.values()
            if record.reaction_status is ReactionStatus.PENDING
        ]

    async def list_ambiguous(self) -> list[DeliveryRecord]:
        return [
            record
            for record in self.records.values()
            if record.publication_status is PublicationStatus.AMBIGUOUS
        ]

    def _find(self, delivery_id: int) -> tuple[str, DeliveryRecord]:
        for key, record in self.records.items():
            if record.id == delivery_id:
                return key, record
        raise KeyError(f"unknown delivery id {delivery_id}")

    def _write(self, key: str, record: DeliveryRecord) -> None:
        self.records[key] = record

    @staticmethod
    def _lease_is_live(record: DeliveryRecord) -> bool:
        return record.lease_expires_at is not None and record.lease_expires_at > datetime.now(UTC)
