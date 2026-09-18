"""SQLAlchemy implementation of the atomic CAS delivery ledger (plan §6, normative).

Every mutating method is ONE short conditional UPDATE with an explicit ``claim_token``
guard where the protocol passes one; the row is matched exactly when the update reports
a returned row, so no read-before-write race exists. Repositories never commit.
"""

import json
from collections.abc import Sequence

from sqlalchemy import ColumnElement, Result, Update, func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from vk_topic_bridge.application.dto.delivery import (
    DeliveryRecord,
    ReserveOutcome,
    ReserveRequest,
)
from vk_topic_bridge.domain.enums import PublicationStatus, ReactionStatus, SourceType
from vk_topic_bridge.domain.policies.delivery_policy import LEGAL_TRANSITIONS
from vk_topic_bridge.infrastructure.db import models
from vk_topic_bridge.infrastructure.db.models import DeliveryRecord as DeliveryRecordModel

# A reaction is claimable from any non-successful state; `pending` is excluded so a
# concurrent worker cannot steal an in-flight reaction.
_REACTION_CLAIMABLE = (
    models.REACTION_STATUS_NOT_DUE,
    models.REACTION_STATUS_FAILED,
    models.REACTION_STATUS_AMBIGUOUS,
)
_REACTION_PENDING = (
    models.REACTION_STATUS_NOT_DUE,
    models.REACTION_STATUS_PENDING,
    models.REACTION_STATUS_FAILED,
)
_REACTION_MUTABLE = (
    models.REACTION_STATUS_NOT_DUE,
    models.REACTION_STATUS_PENDING,
    models.REACTION_STATUS_FAILED,
    models.REACTION_STATUS_AMBIGUOUS,
)


def _sources_for(target: PublicationStatus) -> tuple[str, ...]:
    """Source statuses allowed to transition into ``target`` (plan §6 rule 3)."""
    return tuple(source.value for source, destination in LEGAL_TRANSITIONS if destination == target)


def _decode_message_ids(raw: str | None) -> tuple[int, ...]:
    if raw is None:
        return ()
    decoded = json.loads(raw)
    if not isinstance(decoded, list):
        return ()
    return tuple(int(value) for value in decoded)


def _to_dto(row: DeliveryRecordModel) -> DeliveryRecord:
    return DeliveryRecord(
        id=row.id,
        source_type=row.source_type,
        source_key=row.source_key,
        publication_status=PublicationStatus(row.publication_status),
        reaction_status=ReactionStatus(row.reaction_status),
        claim_token=row.claim_token,
        lease_expires_at=row.lease_expires_at,
        send_started_at=row.send_started_at,
        destination_chat_id=row.destination_chat_id,
        destination_topic_id=row.destination_topic_id,
        telegram_message_ids=_decode_message_ids(row.telegram_message_ids),
        attempts=row.attempts,
        last_error_code=row.last_error_code,
        last_error=row.last_error,
        payload_hash=row.payload_hash,
        ambiguous_at=row.ambiguous_at,
        review_required=bool(row.review_required),
        created_at=row.created_at,
        updated_at=row.updated_at,
        completed_at=row.completed_at,
        intent=row.intent,
    )


class DeliveryRepositoryImpl:
    """CAS ledger adapter; the caller owns commit and therefore the visibility boundary."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def reserve(self, request: ReserveRequest) -> ReserveOutcome:
        insert_stmt = (
            sqlite_insert(DeliveryRecordModel)
            .values(
                source_type=request.source_type.value,
                source_key=request.source_key,
                publication_status=models.PUBLICATION_STATUS_RESERVED,
                reaction_status=models.REACTION_STATUS_NOT_DUE,
                intent=request.intent,
                destination_chat_id=request.destination_chat_id,
                destination_topic_id=request.destination_topic_id,
                payload_hash=request.payload_hash,
            )
            .on_conflict_do_nothing(index_elements=["source_type", "source_key"])
            .returning(DeliveryRecordModel.id)
        )
        insert_result: Result[tuple[int]] = await self._session.execute(insert_stmt)
        new_id = insert_result.scalar_one_or_none()
        if new_id is not None:
            row = await self._session.get(DeliveryRecordModel, new_id)
            assert row is not None
            return ReserveOutcome(created=True, record=_to_dto(row))

        existing = await self._session.execute(
            select(DeliveryRecordModel)
            .where(
                DeliveryRecordModel.source_type == request.source_type.value,
                DeliveryRecordModel.source_key == request.source_key,
            )
            .execution_options(populate_existing=True)
        )
        return ReserveOutcome(created=False, record=_to_dto(existing.scalar_one()))

    async def claim_reserved(self, delivery_id: int, claim_token: str, lease_seconds: int) -> bool:
        stmt = (
            update(DeliveryRecordModel)
            .where(
                DeliveryRecordModel.id == delivery_id,
                DeliveryRecordModel.publication_status.in_(
                    (
                        models.PUBLICATION_STATUS_RESERVED,
                        models.PUBLICATION_STATUS_FAILED_BEFORE_SEND,
                    )
                ),
                # A claim is only stealable when its lease is absent or already expired.
                (
                    DeliveryRecordModel.claim_token.is_(None)
                    | DeliveryRecordModel.lease_expires_at.is_(None)
                    | (DeliveryRecordModel.lease_expires_at <= func.current_timestamp())
                ),
            )
            .values(
                publication_status=models.PUBLICATION_STATUS_RESERVED,
                claim_token=claim_token,
                lease_expires_at=func.datetime("now", f"+{lease_seconds} seconds"),
                attempts=DeliveryRecordModel.attempts + 1,
                updated_at=func.current_timestamp(),
            )
            .returning(DeliveryRecordModel.id)
        )
        return await self._cas(stmt)

    async def mark_send_started(self, delivery_id: int, claim_token: str) -> bool:
        target = PublicationStatus.SEND_STARTED
        stmt = (
            update(DeliveryRecordModel)
            .where(*self._claim_guard(delivery_id, claim_token, target))
            .values(
                publication_status=target.value,
                send_started_at=func.current_timestamp(),
                updated_at=func.current_timestamp(),
            )
            .returning(DeliveryRecordModel.id)
        )
        return await self._cas(stmt)

    async def mark_published(
        self, delivery_id: int, claim_token: str, message_ids: Sequence[int]
    ) -> bool:
        target = PublicationStatus.PUBLISHED
        stmt = (
            update(DeliveryRecordModel)
            .where(*self._claim_guard(delivery_id, claim_token, target))
            .values(
                publication_status=target.value,
                reaction_status=models.REACTION_STATUS_NOT_DUE,
                telegram_message_ids=json.dumps(list(message_ids)),
                completed_at=func.current_timestamp(),
                updated_at=func.current_timestamp(),
            )
            .returning(DeliveryRecordModel.id)
        )
        return await self._cas(stmt)

    async def mark_publication_ambiguous(
        self, delivery_id: int, claim_token: str, code: str | None, message: str | None
    ) -> bool:
        target = PublicationStatus.AMBIGUOUS
        stmt = (
            update(DeliveryRecordModel)
            .where(*self._claim_guard(delivery_id, claim_token, target))
            .values(
                publication_status=target.value,
                ambiguous_at=func.current_timestamp(),
                review_required=True,
                last_error_code=code,
                last_error=message,
                updated_at=func.current_timestamp(),
            )
            .returning(DeliveryRecordModel.id)
        )
        return await self._cas(stmt)

    async def mark_failed_before_send(
        self, delivery_id: int, claim_token: str, code: str | None, message: str | None
    ) -> bool:
        target = PublicationStatus.FAILED_BEFORE_SEND
        stmt = (
            update(DeliveryRecordModel)
            .where(*self._claim_guard(delivery_id, claim_token, target))
            .values(
                publication_status=target.value,
                # No network intent was recorded, so the claim is released for a safe retry.
                claim_token=None,
                lease_expires_at=None,
                last_error_code=code,
                last_error=message,
                updated_at=func.current_timestamp(),
            )
            .returning(DeliveryRecordModel.id)
        )
        return await self._cas(stmt)

    async def mark_failed_permanent(
        self, delivery_id: int, claim_token: str, code: str | None, message: str | None
    ) -> bool:
        target = PublicationStatus.FAILED_PERMANENT
        stmt = (
            update(DeliveryRecordModel)
            .where(*self._claim_guard(delivery_id, claim_token, target))
            .values(
                publication_status=target.value,
                last_error_code=code,
                last_error=message,
                updated_at=func.current_timestamp(),
            )
            .returning(DeliveryRecordModel.id)
        )
        return await self._cas(stmt)

    async def claim_reaction(self, delivery_id: int) -> bool:
        stmt = (
            update(DeliveryRecordModel)
            .where(
                DeliveryRecordModel.id == delivery_id,
                DeliveryRecordModel.publication_status == models.PUBLICATION_STATUS_PUBLISHED,
                DeliveryRecordModel.reaction_status.in_(_REACTION_CLAIMABLE),
            )
            .values(
                reaction_status=models.REACTION_STATUS_PENDING,
                updated_at=func.current_timestamp(),
            )
            .returning(DeliveryRecordModel.id)
        )
        return await self._cas(stmt)

    async def mark_reaction_succeeded(self, delivery_id: int) -> bool:
        stmt = (
            update(DeliveryRecordModel)
            .where(
                DeliveryRecordModel.id == delivery_id,
                DeliveryRecordModel.publication_status == models.PUBLICATION_STATUS_PUBLISHED,
                DeliveryRecordModel.reaction_status.in_(_REACTION_MUTABLE),
            )
            .values(
                reaction_status=models.REACTION_STATUS_SUCCEEDED,
                updated_at=func.current_timestamp(),
            )
            .returning(DeliveryRecordModel.id)
        )
        return await self._cas(stmt)

    async def mark_reaction_failed(
        self, delivery_id: int, code: str | None, message: str | None
    ) -> bool:
        stmt = (
            update(DeliveryRecordModel)
            .where(
                DeliveryRecordModel.id == delivery_id,
                DeliveryRecordModel.publication_status == models.PUBLICATION_STATUS_PUBLISHED,
                DeliveryRecordModel.reaction_status.in_(_REACTION_MUTABLE),
            )
            # Reaction failure is log-only and never touches publication_status.
            .values(
                reaction_status=models.REACTION_STATUS_FAILED,
                last_error_code=code,
                last_error=message,
                updated_at=func.current_timestamp(),
            )
            .returning(DeliveryRecordModel.id)
        )
        return await self._cas(stmt)

    async def get(self, source_type: SourceType, source_key: str) -> DeliveryRecord | None:
        result = await self._session.execute(
            select(DeliveryRecordModel)
            .where(
                DeliveryRecordModel.source_type == source_type.value,
                DeliveryRecordModel.source_key == source_key,
            )
            .execution_options(populate_existing=True)
        )
        row = result.scalar_one_or_none()
        return None if row is None else _to_dto(row)

    async def list_pending_reactions(self) -> list[DeliveryRecord]:
        result = await self._session.execute(
            select(DeliveryRecordModel)
            .where(
                DeliveryRecordModel.publication_status == models.PUBLICATION_STATUS_PUBLISHED,
                DeliveryRecordModel.reaction_status.in_(_REACTION_PENDING),
            )
            .order_by(DeliveryRecordModel.id)
            .execution_options(populate_existing=True)
        )
        return [_to_dto(row) for row in result.scalars()]

    async def list_ambiguous(self) -> list[DeliveryRecord]:
        result = await self._session.execute(
            select(DeliveryRecordModel)
            .where(DeliveryRecordModel.publication_status == models.PUBLICATION_STATUS_AMBIGUOUS)
            .order_by(DeliveryRecordModel.id)
            .execution_options(populate_existing=True)
        )
        return [_to_dto(row) for row in result.scalars()]

    async def list_failed_terminal(self, limit: int = 20) -> list[DeliveryRecord]:
        result = await self._session.execute(
            select(DeliveryRecordModel)
            .where(
                DeliveryRecordModel.publication_status.in_(
                    (
                        models.PUBLICATION_STATUS_FAILED_PERMANENT,
                        models.PUBLICATION_STATUS_AMBIGUOUS,
                    )
                )
            )
            .order_by(DeliveryRecordModel.updated_at.desc(), DeliveryRecordModel.id.desc())
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        return [_to_dto(row) for row in result.scalars()]

    async def mark_reviewed(self, delivery_id: int) -> bool:
        stmt = (
            update(DeliveryRecordModel)
            .where(
                DeliveryRecordModel.id == delivery_id,
                DeliveryRecordModel.publication_status == models.PUBLICATION_STATUS_AMBIGUOUS,
                DeliveryRecordModel.review_required.is_(True),
            )
            .values(review_required=False, updated_at=func.current_timestamp())
            .returning(DeliveryRecordModel.id)
        )
        return await self._cas(stmt)

    def _claim_guard(
        self, delivery_id: int, claim_token: str, target: PublicationStatus
    ) -> tuple[ColumnElement[bool], ...]:
        return (
            DeliveryRecordModel.id == delivery_id,
            DeliveryRecordModel.claim_token == claim_token,
            DeliveryRecordModel.publication_status.in_(_sources_for(target)),
        )

    async def _cas(self, stmt: Update) -> bool:
        result: Result[tuple[int]] = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None


__all__ = ["DeliveryRepositoryImpl"]
