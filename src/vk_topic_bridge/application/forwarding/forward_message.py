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
from vk_topic_bridge.application.errors import TELEGRAM_TOPIC_NOT_FOUND_CODE
from vk_topic_bridge.application.forwarding.composition import (
    append_media_warnings,
    prepend_general_fallback_warning,
)
from vk_topic_bridge.application.forwarding.media_prep import prepare_media
from vk_topic_bridge.application.forwarding.plan_execution import (
    PlanOutcome,
    begin_send,
    execute_plan,
    reserve_delivery,
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
from vk_topic_bridge.domain.value_objects import Destination, Publication, SourceMessage

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
        logger.debug(
            "automatic message forwarding started",
            extra={
                "source_type": source.source_type.value,
                "group_id": source.group_id,
                "peer_id": source.peer_id,
                "conversation_message_id": source.conversation_message_id,
                "source_key": source.source_key,
                "attachment_count": len(source.attachments),
            },
        )
        async with self._uow_factory() as uow:
            state = await uow.bridge_settings.get()
            if state is None or state.telegram_chat_id is None:
                logger.debug(
                    "message forwarding skipped: telegram_chat_not_registered",
                    extra={"peer_id": source.peer_id, "reason": "unregistered"},
                )
                return ForwardOutcome(
                    published=False, skipped=True, reason="unregistered", delivery_id=None
                )

            decision = decide(
                source.text,
                auto_forward_all=state.auto_forward_all,
                auto_forward_hashtags=state.auto_forward_hashtags,
            )
            logger.debug(
                "automatic message forwarding filter evaluated",
                extra={
                    "peer_id": source.peer_id,
                    "outcome": "forward" if decision.forward else "skip",
                    "reason": "matched" if decision.forward else "filtered",
                },
            )
            if not decision.forward:
                return ForwardOutcome(
                    published=False, skipped=True, reason="filtered", delivery_id=None
                )

            kind = state.messages_destination_kind()
            if kind is DestinationKind.UNSET:
                logger.debug(
                    "message forwarding skipped: destination_not_configured",
                    extra={"peer_id": source.peer_id, "reason": "unconfigured"},
                )
                return ForwardOutcome(
                    published=False, skipped=True, reason="unconfigured", delivery_id=None
                )

            topics = await uow.telegram_topics.list(state.telegram_chat_id)
            availability = snapshot_availability(topics)
            ready = derive_feature_readiness(state, availability).messages_auto_ready
            configured_topic_id = state.telegram_messages_topic_id
            configured_topic_label = (
                next(
                    (topic.title for topic in topics if topic.topic_id == configured_topic_id),
                    f"#{configured_topic_id}",
                )
                if configured_topic_id is not None
                else None
            )
            fallback_topic_id: int | None = None
            fallback_reason: str | None = None
            fallback_topic_label: str | None = None
            if kind is DestinationKind.GENERAL:
                thread_id: int | None = None
            elif ready:
                thread_id = configured_topic_id
            else:
                # Configured named topic disappeared/closed/hidden: General fallback.
                if configured_topic_id is not None:
                    fallback_topic_id = configured_topic_id
                    fallback_reason = unavailable_reason(topics, configured_topic_id)
                    fallback_topic_label = configured_topic_label
                thread_id = None
            chat_id = state.telegram_chat_id
            destination = Destination(chat_id=chat_id, message_thread_id=thread_id)
            logger.debug(
                "automatic message forwarding destination selected",
                extra={
                    "chat_id": chat_id,
                    "destination_topic_id": thread_id,
                    "source_key": source.source_key,
                    "outcome": "fallback" if fallback_topic_id is not None else kind.value,
                    "status": "fallback" if fallback_topic_id is not None else "ready",
                    "reason": fallback_reason,
                },
            )

        publication = compose_publication(source, destination)
        media, warnings = await prepare_media(source.attachments, self._downloader)
        publication = replace(
            publication, html_text=append_media_warnings(publication.html_text, warnings)
        )
        if fallback_topic_id is not None:
            publication = replace(
                publication,
                html_text=prepend_general_fallback_warning(
                    publication.html_text,
                    topic_label=fallback_topic_label or f"#{fallback_topic_id}",
                ),
            )
        plan = plan_publication(publication, media)
        logger.debug(
            "automatic message forwarding plan prepared",
            extra={
                "chat_id": chat_id,
                "destination_topic_id": thread_id,
                "operation_count": len(plan.operations),
                "planned_media_count": len(media),
                "warning_count": len(warnings),
            },
        )

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
        logger.debug(
            "automatic message forwarding delivery reserved",
            extra={"delivery_id": record.id, "outcome": "created" if created else "existing"},
        )

        if not created:
            if record.publication_status is PublicationStatus.PUBLISHED:
                logger.debug(
                    "automatic message forwarding reused published delivery",
                    extra={"delivery_id": record.id, "outcome": "already_published"},
                )
                await self._ensure_reaction(source, record.id)
                return ForwardOutcome(
                    published=True,
                    skipped=False,
                    reason="already_published",
                    delivery_id=record.id,
                    message_ids=record.telegram_message_ids,
                )
            if must_not_republish(record.publication_status):
                logger.debug(
                    "automatic message forwarding skipped terminal delivery",
                    extra={
                        "delivery_id": record.id,
                        "outcome": f"already_{record.publication_status.value}",
                    },
                )
                return ForwardOutcome(
                    published=False,
                    skipped=True,
                    reason=f"already_{record.publication_status.value}",
                    delivery_id=record.id,
                )

        delivery_id = record.id
        if not await begin_send(self._uow_factory, delivery_id, _CLAIM_TOKEN):
            logger.debug(
                "automatic message forwarding claim lost",
                extra={"delivery_id": delivery_id, "outcome": "claim_lost"},
            )
            return ForwardOutcome(
                published=False, skipped=True, reason="claim_lost", delivery_id=delivery_id
            )

        outcome = await execute_plan(
            self._uow_factory, delivery_id, _CLAIM_TOKEN, plan, self._plan_publisher
        )
        logger.debug(
            "automatic message forwarding plan completed",
            extra={
                "delivery_id": delivery_id,
                "outcome": "published" if outcome.published else "failed",
                "message_id_count": len(outcome.message_ids),
                "reason": outcome.failure_code,
            },
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
        runtime_stale = (
            not outcome.published
            and outcome.failed_permanent
            and outcome.failure_code == TELEGRAM_TOPIC_NOT_FOUND_CODE
            and configured_topic_id is not None
            and fallback_topic_id is None
        )
        if runtime_stale and media:
            logger.warning(
                "automatic runtime stale-topic fallback skipped for media plan",
                extra={
                    "delivery_id": delivery_id,
                    "destination_topic_id": configured_topic_id,
                    "media_count": len(media),
                },
            )
        stale_topic_id = configured_topic_id
        if runtime_stale and not media and stale_topic_id is not None:
            logger.warning(
                "automatic runtime stale topic detected",
                extra={
                    "delivery_id": delivery_id,
                    "destination_topic_id": stale_topic_id,
                    "reason": outcome.failure_code,
                },
            )
            fallback_delivery_id, fallback_outcome = await self._publish_runtime_general_fallback(
                source,
                publication,
                stale_topic_id,
                configured_topic_label or f"#{stale_topic_id}",
            )
            if fallback_outcome.claim_lost:
                logger.error(
                    "automatic runtime General fallback claim lost",
                    extra={"delivery_id": fallback_delivery_id},
                )
                return ForwardOutcome(
                    published=False,
                    skipped=False,
                    reason="claim_lost",
                    delivery_id=fallback_delivery_id,
                )
            if fallback_outcome.published:
                await self._notify_fallback(stale_topic_id, "stale")
                await self._ensure_reaction(source, fallback_delivery_id)
                logger.info(
                    "automatic runtime stale-topic fallback completed",
                    extra={
                        "delivery_id": fallback_delivery_id,
                        "destination_topic_id": stale_topic_id,
                        "outcome": "published",
                    },
                )
                return ForwardOutcome(
                    published=True,
                    skipped=False,
                    reason="published",
                    delivery_id=fallback_delivery_id,
                    message_ids=fallback_outcome.message_ids,
                )
            await self._notify_attention(fallback_delivery_id, fallback_outcome)
            fallback_reason = "ambiguous" if fallback_outcome.ambiguous else "rejected"
            logger.warning(
                "automatic runtime stale-topic fallback failed",
                extra={"delivery_id": fallback_delivery_id, "outcome": fallback_reason},
            )
            return ForwardOutcome(
                published=False,
                skipped=False,
                reason=fallback_reason,
                delivery_id=fallback_delivery_id,
            )
        if outcome.published:
            if fallback_topic_id is not None:
                logger.warning(
                    "automatic message forwarding fallback to General",
                    extra={
                        "delivery_id": delivery_id,
                        "destination_topic_id": fallback_topic_id,
                        "reason": fallback_reason,
                    },
                )
                await self._notify_fallback(fallback_topic_id, fallback_reason or "missing")
            await self._ensure_reaction(source, delivery_id)
            logger.info(
                "automatic message forwarding completed",
                extra={
                    "delivery_id": delivery_id,
                    "outcome": "published",
                    "message_id_count": len(outcome.message_ids),
                },
            )
            return ForwardOutcome(
                published=True,
                skipped=False,
                reason="published",
                delivery_id=delivery_id,
                message_ids=outcome.message_ids,
            )
        await self._notify_attention(delivery_id, outcome)
        reason = "ambiguous" if outcome.ambiguous else "rejected"
        logger.warning(
            "automatic message forwarding completed with failure",
            extra={"delivery_id": delivery_id, "outcome": reason},
        )
        return ForwardOutcome(
            published=False, skipped=False, reason=reason, delivery_id=delivery_id
        )

    async def _publish_runtime_general_fallback(
        self,
        source: SourceMessage,
        publication: Publication,
        stale_topic_id: int,
        topic_label: str,
    ) -> tuple[int, PlanOutcome]:
        fallback_publication = replace(
            publication,
            message_thread_id=None,
            html_text=prepend_general_fallback_warning(
                publication.html_text,
                topic_label=topic_label,
            ),
        )
        fallback_plan = plan_publication(fallback_publication, ())
        fallback_source_key = f"{source.source_key}:general-fallback"
        fallback_delivery_id = await reserve_delivery(
            self._uow_factory,
            source_type=source.source_type,
            source_key=fallback_source_key,
            destination_chat_id=fallback_publication.chat_id,
            destination_topic_id=None,
            payload_hash=hashlib.sha256(fallback_publication.html_text.encode()).hexdigest(),
            intent="automatic",
        )
        logger.debug(
            "automatic runtime General fallback delivery reserved",
            extra={
                "delivery_id": fallback_delivery_id,
                "destination_topic_id": stale_topic_id,
                "outcome": "fallback",
            },
        )
        if not await begin_send(self._uow_factory, fallback_delivery_id, _CLAIM_TOKEN):
            return fallback_delivery_id, PlanOutcome(
                published=False,
                message_ids=(),
                claim_lost=True,
            )
        outcome = await execute_plan(
            self._uow_factory,
            fallback_delivery_id,
            _CLAIM_TOKEN,
            fallback_plan,
            self._plan_publisher,
        )
        return fallback_delivery_id, outcome

    async def _notify_fallback(self, topic_id: int, reason: str) -> None:
        if self._notifier is None:
            logger.error(
                "fallback owner notification unavailable",
                extra={"destination_topic_id": topic_id, "reason": reason},
            )
            return
        logger.info(
            "fallback owner notification requested",
            extra={"destination_topic_id": topic_id, "reason": reason},
        )
        try:
            await self._notifier.notify_all(
                fallback_notification_text(feature="messages", topic_id=topic_id, reason=reason)
            )
            logger.info(
                "fallback owner notification completed",
                extra={"destination_topic_id": topic_id, "reason": reason},
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
            logger.debug(
                "vk reaction skipped: delivery already claimed",
                extra={"delivery_id": delivery_id, "outcome": "not_claimed"},
            )
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
        logger.debug(
            "vk reaction completed",
            extra={
                "delivery_id": delivery_id,
                "peer_id": source.peer_id,
                "conversation_message_id": source.conversation_message_id,
                "outcome": "succeeded",
            },
        )
