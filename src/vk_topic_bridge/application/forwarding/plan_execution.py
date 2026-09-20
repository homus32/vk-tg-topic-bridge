"""Shared fail-closed execution of one publication plan against the delivery ledger.

Both the manual publication and the wall pipeline reserve a delivery, commit send
intent before any Bot API call, and roll per-operation outcomes up into exactly one
persisted status. An ambiguous outcome is never retried (frozen fail-closed policy).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass

from vk_topic_bridge.application.dto.delivery import ReserveRequest
from vk_topic_bridge.application.errors import PublicationAmbiguousError
from vk_topic_bridge.application.ports.telegram_ex import TelegramPublisherPlan
from vk_topic_bridge.application.ports.unit_of_work import UnitOfWork
from vk_topic_bridge.domain.enums import SourceType
from vk_topic_bridge.domain.errors import DomainError
from vk_topic_bridge.domain.publication import (
    OperationOutcome,
    OperationStatus,
    PublicationPlan,
)

DEFAULT_CLAIM_LEASE_SECONDS = 60
_WINNING_STATUSES = (OperationStatus.PUBLISHED, OperationStatus.PARTIALLY_PUBLISHED)
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PlanOutcome:
    """Roll-up of one executed plan; ``ambiguous`` is the fail-closed review path.

    ``failed_permanent`` marks a terminal rejection/total failure so automatic
    callers can raise an owner-attention notification (manual callers ignore it).
    ``claim_lost`` means the publication CAS went to a competing worker: the send is
    unconfirmed, so no caller may claim success or react.
    """

    published: bool
    message_ids: tuple[int, ...]
    ambiguous: bool = False
    failed_permanent: bool = False
    claim_lost: bool = False


async def reserve_delivery(
    uow_factory: Callable[[], UnitOfWork],
    *,
    source_type: SourceType,
    source_key: str,
    destination_chat_id: int | None,
    destination_topic_id: int | None,
    payload_hash: str | None,
    intent: str,
) -> int:
    """Insert the delivery row and commit before any network call; returns its id."""
    logger.debug(
        "delivery reservation started",
        extra={
            "source_type": source_type.value,
            "destination_topic_id": destination_topic_id,
            "outcome": intent,
        },
    )
    async with uow_factory() as uow:
        reservation = await uow.deliveries.reserve(
            ReserveRequest(
                source_type=source_type,
                source_key=source_key,
                destination_chat_id=destination_chat_id,
                destination_topic_id=destination_topic_id,
                payload_hash=payload_hash,
                intent=intent,
            )
        )
        await uow.commit()
        delivery_id = reservation.record.id
    logger.debug("delivery reservation completed", extra={"delivery_id": delivery_id})
    return delivery_id


async def begin_send(
    uow_factory: Callable[[], UnitOfWork],
    delivery_id: int,
    claim_token: str,
    *,
    lease_seconds: int = DEFAULT_CLAIM_LEASE_SECONDS,
) -> bool:
    """Claim and commit send intent; False when another attempt owns the delivery."""
    logger.debug("delivery claim started", extra={"delivery_id": delivery_id})
    async with uow_factory() as uow:
        claimed = await uow.deliveries.claim_reserved(delivery_id, claim_token, lease_seconds)
        await uow.commit()
    if not claimed:
        logger.debug(
            "delivery claim rejected",
            extra={"delivery_id": delivery_id, "outcome": "claim_lost"},
        )
        return False
    async with uow_factory() as uow:
        started = await uow.deliveries.mark_send_started(delivery_id, claim_token)
        await uow.commit()
    if not started:
        logger.debug(
            "delivery send start rejected",
            extra={"delivery_id": delivery_id, "outcome": "claim_lost"},
        )
        return False
    logger.debug("delivery send started", extra={"delivery_id": delivery_id})
    return started


async def execute_plan(
    uow_factory: Callable[[], UnitOfWork],
    delivery_id: int,
    claim_token: str,
    plan: PublicationPlan,
    publisher: TelegramPublisherPlan,
) -> PlanOutcome:
    """Send the plan and persist the roll-up; a rejection never aborts silently."""
    logger.debug(
        "publication plan execution started",
        extra={"delivery_id": delivery_id, "operation_count": len(plan.operations)},
    )
    try:
        outcomes = await publisher.publish_plan(plan)
    except PublicationAmbiguousError as error:
        logger.warning(
            "publication plan became ambiguous",
            extra={"delivery_id": delivery_id, "reason": error.code},
        )
        async with uow_factory() as uow:
            await uow.deliveries.mark_publication_ambiguous(
                delivery_id, claim_token, error.code, str(error)
            )
            await uow.commit()
        return PlanOutcome(published=False, message_ids=(), ambiguous=True)
    except asyncio.CancelledError:
        # A cancelled send may already have reached Telegram: persist ambiguity before
        # propagating so a restart never re-publishes an unconfirmed delivery.
        async with uow_factory() as uow:
            await uow.deliveries.mark_publication_ambiguous(
                delivery_id, claim_token, "cancelled", "cancelled"
            )
            await uow.commit()
        logger.warning(
            "publication plan cancelled and marked ambiguous",
            extra={"delivery_id": delivery_id, "reason": "cancelled"},
        )
        raise
    except DomainError as error:
        logger.warning(
            "publication plan rejected",
            extra={"delivery_id": delivery_id, "reason": getattr(error, "code", None)},
        )
        async with uow_factory() as uow:
            await uow.deliveries.mark_failed_permanent(
                delivery_id, claim_token, getattr(error, "code", None), str(error)
            )
            await uow.commit()
        return PlanOutcome(published=False, message_ids=(), failed_permanent=True)
    result = await _finalize(uow_factory, delivery_id, claim_token, outcomes)
    logger.debug(
        "publication plan execution completed",
        extra={
            "delivery_id": delivery_id,
            "outcome": "published" if result.published else "failed",
            "message_id_count": len(result.message_ids),
        },
    )
    return result


async def _finalize(
    uow_factory: Callable[[], UnitOfWork],
    delivery_id: int,
    claim_token: str,
    outcomes: tuple[OperationOutcome, ...],
) -> PlanOutcome:
    message_ids = tuple(message_id for outcome in outcomes for message_id in outcome.message_ids)
    published = any(outcome.status in _WINNING_STATUSES for outcome in outcomes)
    ambiguous = any(outcome.status is OperationStatus.ACCEPTED_UNKNOWN for outcome in outcomes)
    logger.debug(
        "publication plan outcomes collected",
        extra={
            "delivery_id": delivery_id,
            "operation_count": len(outcomes),
            "message_id_count": len(message_ids),
            "outcome": "ambiguous" if ambiguous else "published" if published else "failed",
        },
    )
    async with uow_factory() as uow:
        if published:
            marked = await uow.deliveries.mark_published(delivery_id, claim_token, message_ids)
        elif ambiguous:
            marked = await uow.deliveries.mark_publication_ambiguous(
                delivery_id, claim_token, None, "unconfirmed operations"
            )
        else:
            marked = await uow.deliveries.mark_failed_permanent(
                delivery_id, claim_token, None, "all operations failed"
            )
        await uow.commit()
    if published and not marked:
        # A competing worker won the publication CAS: this send is unconfirmed, so the
        # reaction and the success outcome must not claim it.
        return PlanOutcome(published=False, message_ids=message_ids, claim_lost=True)
    return PlanOutcome(
        published=published,
        message_ids=message_ids if published else (),
        ambiguous=ambiguous,
        failed_permanent=not published and not ambiguous,
    )
