"""Shared media preparation: download attachments before planning.

The frozen flow downloads first, so a failed/unavailable/oversized attachment never
becomes an operation — it becomes a per-item warning line in the publication text
(docs/03 §12.4/12.5). Only successfully downloaded items reach ``plan_publication``.
"""

from __future__ import annotations

from collections.abc import Sequence

from vk_topic_bridge.application.forwarding.composition import (
    MediaFailureReason,
    media_failure_warning,
)
from vk_topic_bridge.application.forwarding.publication_planning import OperationKind
from vk_topic_bridge.application.ports.telegram_ex import VkMediaDownloaderPort
from vk_topic_bridge.domain.enums import AttachmentKind
from vk_topic_bridge.domain.errors import (
    AttachmentDownloadFailed,
    AttachmentTooLargeError,
    MediaUnavailableError,
    RecoverableInfraError,
)
from vk_topic_bridge.domain.policies.attachment_policy import MAX_ATTACHMENT_BYTES
from vk_topic_bridge.domain.publication import PlannedMedia
from vk_topic_bridge.domain.value_objects import Attachment


async def prepare_media(
    attachments: Sequence[Attachment],
    downloader: VkMediaDownloaderPort | None,
) -> tuple[tuple[PlannedMedia, ...], list[str]]:
    """Download supported attachments; failures become warning lines, never operations."""
    if downloader is None:
        return (), []
    planned: list[PlannedMedia] = []
    warnings: list[str] = []
    for attachment in attachments:
        operation_kind = operation_kind_for(attachment.kind)
        if operation_kind is None:
            warnings.append(
                media_failure_warning(
                    attachment.kind, attachment.file_name, MediaFailureReason.UNSUPPORTED
                )
            )
            continue
        size = attachment.size_bytes
        if size is not None and size > MAX_ATTACHMENT_BYTES:
            warnings.append(
                media_failure_warning(
                    attachment.kind, attachment.file_name, MediaFailureReason.TOO_LARGE
                )
            )
            continue
        source_ref = attachment.source_ref
        if not source_ref:
            warnings.append(
                media_failure_warning(
                    attachment.kind, attachment.file_name, MediaFailureReason.UNAVAILABLE
                )
            )
            continue
        try:
            url = await downloader.resolve_url(source_ref, attachment.kind)
            path = await downloader.download(source_ref, url)
        except MediaUnavailableError:
            warnings.append(
                media_failure_warning(
                    attachment.kind, attachment.file_name, MediaFailureReason.UNAVAILABLE
                )
            )
            continue
        except AttachmentTooLargeError, AttachmentDownloadFailed, RecoverableInfraError:
            warnings.append(
                media_failure_warning(
                    attachment.kind, attachment.file_name, MediaFailureReason.DOWNLOAD_FAILED
                )
            )
            continue
        planned.append(
            PlannedMedia(kind=operation_kind, file_path=path, file_name=attachment.file_name)
        )
    return tuple(planned), warnings


def operation_kind_for(kind: AttachmentKind) -> OperationKind | None:
    """Supported attachment kinds map to media operations; unsupported kinds do not."""
    if kind is AttachmentKind.PHOTO:
        return OperationKind.PHOTO
    if kind is AttachmentKind.VIDEO:
        return OperationKind.VIDEO
    if kind is AttachmentKind.DOCUMENT:
        return OperationKind.DOCUMENT
    return None
