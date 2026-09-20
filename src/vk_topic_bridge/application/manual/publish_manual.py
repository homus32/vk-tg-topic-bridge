"""Manual publication use case: one intentional VK->Telegram operation.

Distinct from automatic forwarding: no source-key dedup ledger reuse, no readiness
gate on automatic flags, never a VK 👍 reaction, never a silent General fallback for an
explicitly chosen named topic.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from uuid import uuid4

from vk_topic_bridge.application.forwarding.composition import (
    append_media_warnings,
    compose_manual_publication,
)
from vk_topic_bridge.application.forwarding.media_prep import prepare_media
from vk_topic_bridge.application.forwarding.plan_execution import (
    begin_send,
    execute_plan,
    reserve_delivery,
)
from vk_topic_bridge.application.forwarding.publication_planning import plan_publication
from vk_topic_bridge.application.ports.telegram import TelegramPublisher
from vk_topic_bridge.application.ports.telegram_ex import (
    TelegramPublisherPlan,
    VkMediaDownloaderPort,
)
from vk_topic_bridge.application.ports.unit_of_work import UnitOfWork
from vk_topic_bridge.domain.enums import SourceType
from vk_topic_bridge.domain.value_objects import Author, Destination, SourceMessage

_CLAIM_TOKEN = "manual-publication"
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ManualPublicationRequest:
    """Everything needed for one manual operation chosen in the VK UI."""

    source: SourceMessage
    initiator: Author
    destination: Destination


@dataclass(frozen=True, slots=True)
class ManualPublicationResult:
    """What the VK UI needs to answer after one manual send attempt."""

    published: bool
    message_ids: tuple[int, ...]
    delivery_id: int
    error: str | None = None


class PublishManualMessage:
    """Composes and sends the manual publication; records the delivery.

    Contract: manual-intent source key (``manual:{vk_user_id}:{cmid}:{uuid4}``) so the
    same VK message can be intentionally re-published; no reaction; explicit named
    topic failures surface as user-facing errors (never General fallback).
    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        publisher: TelegramPublisher,
        plan_publisher: TelegramPublisherPlan,
        downloader: VkMediaDownloaderPort | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._publisher = publisher
        self._plan_publisher = plan_publisher
        self._downloader = downloader

    async def execute(self, request: ManualPublicationRequest) -> ManualPublicationResult:
        logger.debug(
            "manual publication started",
            extra={
                "owner_id": request.initiator.user_id,
                "peer_id": request.source.peer_id,
                "conversation_message_id": request.source.conversation_message_id,
                "destination_topic_id": request.destination.message_thread_id,
                "attachment_count": len(request.source.attachments),
            },
        )
        publication = compose_manual_publication(
            request.source, request.initiator, request.destination
        )
        media, warnings = await prepare_media(request.source.attachments, self._downloader)
        publication = replace(
            publication, html_text=append_media_warnings(publication.html_text, warnings)
        )
        plan = plan_publication(publication, media)
        logger.debug(
            "manual publication plan prepared",
            extra={
                "owner_id": request.initiator.user_id,
                "operation_count": len(plan.operations),
                "planned_media_count": len(media),
                "warning_count": len(warnings),
            },
        )
        delivery_id = await reserve_delivery(
            self._uow_factory,
            source_type=SourceType.VK_MESSAGE,
            source_key=(
                f"manual:{request.initiator.user_id}:"
                f"{request.source.conversation_message_id}:{uuid4().hex}"
            ),
            destination_chat_id=request.destination.chat_id,
            destination_topic_id=request.destination.message_thread_id,
            payload_hash=hashlib.sha256(publication.html_text.encode()).hexdigest(),
            intent="manual",
        )
        if not await begin_send(self._uow_factory, delivery_id, _CLAIM_TOKEN):
            logger.warning(
                "manual publication claim lost",
                extra={"owner_id": request.initiator.user_id, "delivery_id": delivery_id},
            )
            return ManualPublicationResult(published=False, message_ids=(), delivery_id=delivery_id)
        outcome = await execute_plan(
            self._uow_factory, delivery_id, _CLAIM_TOKEN, plan, self._plan_publisher
        )
        result = ManualPublicationResult(
            published=outcome.published,
            message_ids=outcome.message_ids,
            delivery_id=delivery_id,
            error=None if outcome.published else "публикация не удалась",
        )
        if result.published:
            logger.info(
                "manual publication completed",
                extra={
                    "owner_id": request.initiator.user_id,
                    "delivery_id": delivery_id,
                    "message_id_count": len(result.message_ids),
                },
            )
        else:
            logger.warning(
                "manual publication completed with failure",
                extra={"owner_id": request.initiator.user_id, "delivery_id": delivery_id},
            )
        return result
