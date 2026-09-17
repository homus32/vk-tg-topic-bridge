"""Fail-closed forwarding use case: filter, reserve, publish once, then react."""

import asyncio
import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from vk_topic_bridge.application.dto.delivery import ReserveRequest
from vk_topic_bridge.application.dto.readiness import ReadinessState
from vk_topic_bridge.application.errors import (
    PublicationAmbiguousError,
    PublicationRejectedError,
    ReadinessError,
)
from vk_topic_bridge.application.ports.readiness import ReadinessPort
from vk_topic_bridge.application.ports.telegram import TelegramPublisher
from vk_topic_bridge.application.ports.unit_of_work import UnitOfWork
from vk_topic_bridge.application.ports.vk import VkGateway
from vk_topic_bridge.domain.enums import PublicationStatus
from vk_topic_bridge.domain.policies.delivery_policy import must_not_republish
from vk_topic_bridge.domain.policies.forwarding_policy import compose_publication, decide
from vk_topic_bridge.domain.value_objects import Destination, Publication, SourceMessage

logger = logging.getLogger(__name__)

_CLAIM_LEASE_SECONDS = 60


@dataclass(frozen=True, slots=True)
class ForwardOutcome:
    published: bool
    skipped: bool
    reason: str
    delivery_id: int | None
    message_ids: tuple[int, ...] = ()


class ForwardVkMessage:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], UnitOfWork],
        publisher: TelegramPublisher,
        vk: VkGateway,
        readiness: ReadinessPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._publisher = publisher
        self._vk = vk
        self._readiness = readiness

    async def execute(self, source: SourceMessage) -> ForwardOutcome:
        if not self._forwarding_enabled():
            return ForwardOutcome(
                published=False, skipped=True, reason="readiness", delivery_id=None
            )

        publication: Publication
        async with self._uow_factory() as uow:
            state = await uow.bridge_settings.get()
            if state is None or state.telegram_chat_id is None:
                return ForwardOutcome(
                    published=False, skipped=True, reason="unregistered", delivery_id=None
                )
            decision = decide(
                source.text,
                auto_forward_all=state.auto_forward_all,
                auto_forward_hashtags=state.auto_forward_hashtags,
            )
            if not decision.forward:
                return ForwardOutcome(
                    published=False, skipped=True, reason="filtered", delivery_id=None
                )

            destination = Destination(
                chat_id=state.telegram_chat_id,
                message_thread_id=state.telegram_messages_topic_id,
            )
            publication = compose_publication(source, destination)
            payload_hash = hashlib.sha256(publication.html_text.encode()).hexdigest()
            outcome = await uow.deliveries.reserve(
                ReserveRequest(
                    source_type=source.source_type,
                    source_key=source.source_key,
                    destination_chat_id=state.telegram_chat_id,
                    destination_topic_id=state.telegram_messages_topic_id,
                    payload_hash=payload_hash,
                )
            )
            await uow.commit()
            created = outcome.created
            record = outcome.record

        if not created:
            if record.publication_status is PublicationStatus.PUBLISHED:
                await self._ensure_reaction(source, record.id)
                return ForwardOutcome(
                    published=True,
                    skipped=False,
                    reason="already_published",
                    delivery_id=record.id,
                    message_ids=record.telegram_message_ids,
                )
            if must_not_republish(record.publication_status):
                return ForwardOutcome(
                    published=False,
                    skipped=True,
                    reason=f"already_{record.publication_status.value}",
                    delivery_id=record.id,
                )

        delivery_id = record.id
        claim_token = uuid4().hex
        async with self._uow_factory() as uow:
            claimed = await uow.deliveries.claim_reserved(
                delivery_id, claim_token, _CLAIM_LEASE_SECONDS
            )
            await uow.commit()
        if not claimed:
            return ForwardOutcome(
                published=False, skipped=True, reason="claim_lost", delivery_id=delivery_id
            )

        async with self._uow_factory() as uow:
            send_started = await uow.deliveries.mark_send_started(delivery_id, claim_token)
            await uow.commit()
        if not send_started:
            return ForwardOutcome(
                published=False, skipped=True, reason="claim_lost", delivery_id=delivery_id
            )

        try:
            result = await self._publisher.publish(publication)
        except PublicationAmbiguousError as exc:
            logger.warning("publication ambiguous for delivery %s code=%s", delivery_id, exc.code)
            await self._persist_ambiguous(delivery_id, claim_token, exc.code, str(exc))
            return ForwardOutcome(
                published=False, skipped=False, reason="ambiguous", delivery_id=delivery_id
            )
        except asyncio.CancelledError:
            await self._persist_ambiguous(delivery_id, claim_token, "cancelled", "cancelled")
            raise
        except PublicationRejectedError as exc:
            await self._persist_failed_permanent(delivery_id, claim_token, exc.code, str(exc))
            return ForwardOutcome(
                published=False, skipped=False, reason="rejected", delivery_id=delivery_id
            )

        async with self._uow_factory() as uow:
            marked = await uow.deliveries.mark_published(
                delivery_id, claim_token, result.message_ids
            )
            await uow.commit()
        if not marked:
            logger.warning("mark_published lost CAS for delivery %s", delivery_id)

        await self._ensure_reaction(source, delivery_id)
        return ForwardOutcome(
            published=True,
            skipped=False,
            reason="published",
            delivery_id=delivery_id,
            message_ids=result.message_ids,
        )

    def _forwarding_enabled(self) -> bool:
        try:
            self._readiness.require(ReadinessState.FORWARDING_ENABLED)
        except ReadinessError:
            return False
        return True

    async def _ensure_reaction(self, source: SourceMessage, delivery_id: int) -> None:
        async with self._uow_factory() as uow:
            claimed = await uow.deliveries.claim_reaction(delivery_id)
            await uow.commit()
        if not claimed:
            return

        try:
            await self._vk.set_reaction(source.peer_id, source.conversation_message_id)
        except Exception as exc:
            logger.warning("reaction failed for delivery %s: %s", delivery_id, exc)
            async with self._uow_factory() as uow:
                await uow.deliveries.mark_reaction_failed(delivery_id, type(exc).__name__, str(exc))
                await uow.commit()
            return

        async with self._uow_factory() as uow:
            await uow.deliveries.mark_reaction_succeeded(delivery_id)
            await uow.commit()

    async def _persist_ambiguous(
        self, delivery_id: int, claim_token: str, code: str | None, message: str | None
    ) -> None:
        async with self._uow_factory() as uow:
            await uow.deliveries.mark_publication_ambiguous(delivery_id, claim_token, code, message)
            await uow.commit()

    async def _persist_failed_permanent(
        self, delivery_id: int, claim_token: str, code: str | None, message: str | None
    ) -> None:
        async with self._uow_factory() as uow:
            await uow.deliveries.mark_failed_permanent(delivery_id, claim_token, code, message)
            await uow.commit()
