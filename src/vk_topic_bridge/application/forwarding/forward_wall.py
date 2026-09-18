"""Automatic wall-post forwarding: community wall post -> wall destination.

Mirrors ``ForwardVkMessage`` but is a separate pipeline: the ``auto_forward_wall``
toggle makes it unconditional (no @all/hashtag rules), the dedup key is the wall source
key, and no VK reaction is possible because a wall post has no conversation message id.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace

from vk_topic_bridge.application.dto.delivery import ReserveRequest
from vk_topic_bridge.application.dto.settings import DestinationKind
from vk_topic_bridge.application.forwarding.composition import (
    append_media_warnings,
    compose_wall_publication,
)
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
from vk_topic_bridge.application.readiness_features import (
    derive_feature_readiness,
    snapshot_availability,
    unavailable_reason,
)
from vk_topic_bridge.domain.enums import PublicationStatus, SourceType
from vk_topic_bridge.domain.policies.delivery_policy import must_not_republish
from vk_topic_bridge.domain.value_objects import Destination, SourceWallPost

logger = logging.getLogger(__name__)

_CLAIM_TOKEN = "wall-forward"


@dataclass(frozen=True, slots=True)
class WallForwardOutcome:
    """Result of one wall-post forward attempt."""

    published: bool
    skipped: bool
    reason: str
    delivery_id: int | None = None
    message_ids: tuple[int, ...] = ()


class ForwardWallPost:
    """Forwards one normalized wall post to the wall destination, fail-closed."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], UnitOfWork],
        plan_publisher: TelegramPublisherPlan,
        downloader: VkMediaDownloaderPort | None = None,
        notifier: NotifierLike | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._plan_publisher = plan_publisher
        self._downloader = downloader
        self._notifier = notifier

    async def execute(self, wall_post: SourceWallPost) -> WallForwardOutcome:
        async with self._uow_factory() as uow:
            state = await uow.bridge_settings.get()
            if state is None or state.telegram_chat_id is None:
                logger.debug("wall forwarding skipped: telegram_chat_not_registered")
                return WallForwardOutcome(published=False, skipped=True, reason="unregistered")
            if not state.auto_forward_wall:
                return WallForwardOutcome(published=False, skipped=True, reason="filtered")
            kind = state.wall_destination_kind()
            if kind is DestinationKind.UNSET:
                logger.debug("wall forwarding skipped: destination_not_configured")
                return WallForwardOutcome(published=False, skipped=True, reason="unconfigured")

            topics = await uow.telegram_topics.list(state.telegram_chat_id)
            availability = snapshot_availability(topics)
            ready = derive_feature_readiness(state, availability).wall_auto_ready
            fallback_topic_id: int | None = None
            fallback_reason: str | None = None
            if kind is DestinationKind.GENERAL:
                thread_id: int | None = None
            elif ready:
                thread_id = state.telegram_wall_topic_id
            else:
                fallback_topic_id = state.telegram_wall_topic_id
                fallback_reason = (
                    unavailable_reason(topics, fallback_topic_id)
                    if fallback_topic_id is not None
                    else "missing"
                )
                thread_id = None
            chat_id = state.telegram_chat_id
            destination = Destination(chat_id=chat_id, message_thread_id=thread_id)

        publication = compose_wall_publication(wall_post, destination)
        media, warnings = await prepare_media(wall_post.attachments, self._downloader)
        publication = replace(
            publication, html_text=append_media_warnings(publication.html_text, warnings)
        )
        plan = plan_publication(publication, media)

        async with self._uow_factory() as uow:
            reservation = await uow.deliveries.reserve(
                ReserveRequest(
                    source_type=SourceType.VK_WALL,
                    source_key=wall_post.source_key,
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
                return WallForwardOutcome(
                    published=True,
                    skipped=False,
                    reason="already_published",
                    delivery_id=record.id,
                    message_ids=record.telegram_message_ids,
                )
            if must_not_republish(record.publication_status):
                return WallForwardOutcome(
                    published=False,
                    skipped=True,
                    reason=f"already_{record.publication_status.value}",
                    delivery_id=record.id,
                )

        delivery_id = record.id
        if not await begin_send(self._uow_factory, delivery_id, _CLAIM_TOKEN):
            return WallForwardOutcome(
                published=False, skipped=True, reason="claim_lost", delivery_id=delivery_id
            )
        outcome = await execute_plan(
            self._uow_factory, delivery_id, _CLAIM_TOKEN, plan, self._plan_publisher
        )
        if outcome.published:
            if fallback_topic_id is not None:
                await self._notify_fallback(fallback_topic_id, fallback_reason or "missing")
            # No VK 👍 for wall posts: a wall post has no conversation_message_id.
            return WallForwardOutcome(
                published=True,
                skipped=False,
                reason="published",
                delivery_id=delivery_id,
                message_ids=outcome.message_ids,
            )
        await self._notify_attention(delivery_id, outcome)
        reason = "ambiguous" if outcome.ambiguous else "rejected"
        return WallForwardOutcome(
            published=False, skipped=False, reason=reason, delivery_id=delivery_id
        )

    async def _notify_fallback(self, topic_id: int, reason: str) -> None:
        if self._notifier is None:
            return
        try:
            await self._notifier.notify_all(
                fallback_notification_text(feature="wall", topic_id=topic_id, reason=reason)
            )
        except Exception:
            logger.exception("wall fallback owner notification failed for topic %s", topic_id)

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
            logger.exception("wall attention owner notification failed for %s", delivery_id)
