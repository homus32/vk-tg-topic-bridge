"""Extended ports added by the finish plan (append-only; existing ports unchanged)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from vk_topic_bridge.domain.publication import (
    OperationOutcome,
    PublicationPlan,
)
from vk_topic_bridge.domain.value_objects import Attachment, Destination


@runtime_checkable
class TelegramPublisherPlan(Protocol):
    """Multi-operation publication over the fail-closed error taxonomy.

    TODO(finish): implemented by ``BotApiPublisher`` alongside the existing
    ``publish``/``send_text``. Per operation: TEXT -> ``send_message`` (HTML — TEXT
    operations are publication chunks, always pre-escaped by composition), PHOTO ->
    ``send_photo`` with ``FSInputFile(operation.media[0].file_path)``, VIDEO ->
    ``send_video``, DOCUMENT -> ``send_document``, MEDIA_GROUP -> ``send_media_group``
    built from ``operation.media`` in order (returns up to 10 message ids). Caption
    handling: ``operation.text`` on a media operation is the pre-escaped HTML caption —
    set as ``caption=`` (``parse_mode=HTML``) on the single item for PHOTO/VIDEO/
    DOCUMENT and on the FIRST InputMedia item only for MEDIA_GROUP. Error
    classification reuses the existing ``_classify`` mapping per call; a failed/
    ambiguous operation does not abort the remaining operations unless the caller
    decides otherwise. The publisher deletes every ``item.file_path`` in
    ``operation.media`` after the operation completes (per-op ``finally``, success or
    classified failure); the use case owns cleanup for files that never reach the
    publisher (crash before ``publish_plan``).
    """

    async def publish_plan(self, plan: PublicationPlan) -> tuple[OperationOutcome, ...]:
        """Execute operations in order; temp files live on ``operation.media``."""
        ...


@runtime_checkable
class TelegramNotifierPort(Protocol):
    """Owner-facing plain-text sender used by ``OwnerNotifier``."""

    async def send_text(
        self, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> int: ...


@runtime_checkable
class VkMediaDownloaderPort(Protocol):
    """Downloads one normalized VK attachment to a local temp file before upload."""

    async def resolve_url(self, attachment: Attachment) -> str: ...
    async def download(self, attachment: Attachment, url: str) -> str: ...


@runtime_checkable
class TopicAvailabilityReader(Protocol):
    """Reads the persisted topic snapshot with availability flags for selectors."""

    async def available_destinations(self, chat_id: int) -> tuple[Destination, ...]: ...


# Kept as a module-level alias so bootstrap wiring can reference one import site.
DestinationProvider = TopicAvailabilityReader
