"""Fail-closed automatic forwarding: filter, media-prep, plan, publish once, then react.

Destination policy (frozen draft): an explicit configured General is published directly;
a configured-but-unavailable named topic falls back to General, notifies every owner and
still counts as a successful delivery (👍). A never-configured destination is a silent
no-op. One plan is one delivery: the ledger row is reserved before any Telegram call and
an ambiguous outcome is never retried.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace

from vk_topic_bridge.application.dto.delivery import ReserveRequest
from vk_topic_bridge.application.dto.settings import DestinationKind
from vk_topic_bridge.application.forwarding.composition import append_media_warnings
from vk_topic_bridge.application.forwarding.media_prep import prepare_media
from vk_topic_bridge.application.forwarding.plan_execution import (
    PlanOutcome,
    begin_send,
    execute_plan,
)
from vk_topic_bridge.application.forwarding.publication_planning import plan_publication
from vk_topic_bridge.application.notifications.owner_notifier import (
    NotifierLike,
    attention_notification_text,
    fallback_notification_text,
)
from vk_topic_bridge.application.ports.telegram_ex import (
    TelegramPublisherPlan,
    VkMediaDownloaderPort,
)
from vk_topic_bridge.application.ports.unit_of_work import UnitOfWork
from vk_topic_bridge.application.ports.vk import VkGateway
from vk_topic_bridge.application.readiness_features import (
    derive_feature_readiness,
    snapshot_availability,
    unavailable_reason,
)
from vk_topic_bridge.domain.enums import PublicationStatus
from vk_topic_bridge.domain.policies.delivery_policy import must_not_republish
from vk_topic_bridge.domain.policies.forwarding_policy import compose_publication, decide
from vk_topic_bridge.domain.value_objects import Destination, SourceMessage

logger = logging.getLogger(__name__)

_CLAIM_TOKEN = "message-forward"


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
        plan_publisher: TelegramPublisherPlan,
        vk: VkGateway,
        downloader: VkMediaDownloaderPort | None = None,
        notifier: NotifierLike | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._plan_publisher = plan_publisher
        self._vk = vk
        self._downloader = downloader
        self._notifier = notifier

    async def execute(self, source: SourceMessage) -> ForwardOutcome:
        async with self._uow_factory() as uow:
            state = await uow.bridge_settings.get()
            if state is None or state.telegram_chat_id is None:
                logger.debug("message forwarding skipped: telegram_chat_not_registered")
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

            kind = state.messages_destination_kind()
            if kind is DestinationKind.UNSET:
                logger.debug("message forwarding skipped: destination_not_configured")
                return ForwardOutcome(
                    published=False, skipped=True, reason="unconfigured", delivery_id=None
                )

            topics = await uow.telegram_topics.list(state.telegram_chat_id)
            availability = snapshot_availability(topics)
            ready = derive_feature_readiness(state, availability).messages_auto_ready
            configured_topic_id = state.telegram_messages_topic_id
            fallback_topic_id: int | None = None
            fallback_reason: str | None = None
            if kind is DestinationKind.GENERAL:
                thread_id: int | None = None
            elif ready:
                thread_id = configured_topic_id
            else:
                # Configured named topic disappeared/closed/hidden: General fallback.
                if configured_topic_id is not None:
                    fallback_topic_id = configured_topic_id
                    fallback_reason = unavailable_reason(topics, configured_topic_id)
                thread_id = None
            chat_id = state.telegram_chat_id
            destination = Destination(chat_id=chat_id, message_thread_id=thread_id)

        publication = compose_publication(source, destination)
        media, warnings = await prepare_media(source.attachments, self._downloader)
        publication = replace(
            publication, html_text=append_media_warnings(publication.html_text, warnings)
        )
        plan = plan_publication(publication, media)

        async with self._uow_factory() as uow:
            reservation = await uow.deliveries.reserve(
                ReserveRequest(
                    source_type=source.source_type,
                    source_key=source.source_key,
                    destination_chat_id=chat_id,
                    destination_topic_id=thread_id,
                    payload_hash=hashlib.sha256(publication.html_text.encode()).hexdigest(),
                    intent="automatic",
                )
            )
            await uow.commit()
            created = reservation.created
            record = reservation.record

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
        if not await begin_send(self._uow_factory, delivery_id, _CLAIM_TOKEN):
            return ForwardOutcome(
                published=False, skipped=True, reason="claim_lost", delivery_id=delivery_id
            )

        outcome = await execute_plan(
            self._uow_factory, delivery_id, _CLAIM_TOKEN, plan, self._plan_publisher
        )
        if outcome.claim_lost:
            logger.error("mark_published lost CAS for delivery %s", delivery_id)
            return ForwardOutcome(
                published=False,
                skipped=False,
                reason="claim_lost",
                delivery_id=delivery_id,
                message_ids=outcome.message_ids,
            )
        if outcome.published:
            if fallback_topic_id is not None:
                await self._notify_fallback(fallback_topic_id, fallback_reason or "missing")
            await self._ensure_reaction(source, delivery_id)
            return ForwardOutcome(
                published=True,
                skipped=False,
                reason="published",
                delivery_id=delivery_id,
                message_ids=outcome.message_ids,
            )
        await self._notify_attention(delivery_id, outcome)
        reason = "ambiguous" if outcome.ambiguous else "rejected"
        return ForwardOutcome(
            published=False, skipped=False, reason=reason, delivery_id=delivery_id
        )

    async def _notify_fallback(self, topic_id: int, reason: str) -> None:
        if self._notifier is None:
            return
        try:
            await self._notifier.notify_all(
                fallback_notification_text(feature="messages", topic_id=topic_id, reason=reason)
            )
        except Exception:
            logger.exception("fallback owner notification failed for topic %s", topic_id)

    async def _notify_attention(self, delivery_id: int, outcome: PlanOutcome) -> None:
        if self._notifier is None:
            return
        if not outcome.ambiguous and not outcome.failed_permanent:
            return
        status = "ambiguous" if outcome.ambiguous else "failed_permanent"
        try:
            await self._notifier.notify_all(
                attention_notification_text(status=status, delivery_id=delivery_id)
            )
        except Exception:
            logger.exception("attention owner notification failed for delivery %s", delivery_id)

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
