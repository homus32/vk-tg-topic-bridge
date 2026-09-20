"""Shared media preparation: download attachments before planning.

The frozen flow downloads first, so a failed/unavailable/oversized attachment never
becomes an operation — it becomes a per-item warning line in the publication text
(docs/03 §12.4/12.5). Only successfully downloaded items reach ``plan_publication``.
"""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)


async def prepare_media(
    attachments: Sequence[Attachment],
    downloader: VkMediaDownloaderPort | None,
) -> tuple[tuple[PlannedMedia, ...], list[str]]:
    """Download supported attachments; failures become warning lines, never operations."""
    if downloader is None:
        if attachments:
            logger.debug(
                "media preparation skipped: downloader_not_configured",
                extra={"attachment_count": len(attachments), "reason": "downloader_missing"},
            )
        return (), []
    logger.debug("media preparation started", extra={"attachment_count": len(attachments)})
    planned: list[PlannedMedia] = []
    warnings: list[str] = []
    for index, attachment in enumerate(attachments):
        operation_kind = operation_kind_for(attachment.kind)
        if operation_kind is None:
            logger.debug(
                "media attachment skipped: unsupported_kind",
                extra={
                    "attachment_index": index,
                    "attachment_kind": attachment.kind.value,
                    "reason": "unsupported",
                },
            )
            warnings.append(
                media_failure_warning(
                    attachment.kind, attachment.file_name, MediaFailureReason.UNSUPPORTED
                )
            )
            continue
        size = attachment.size_bytes
        if size is not None and size > MAX_ATTACHMENT_BYTES:
            logger.debug(
                "media attachment skipped: too_large",
                extra={
                    "attachment_index": index,
                    "attachment_kind": attachment.kind.value,
                    "reason": "too_large",
                },
            )
            warnings.append(
                media_failure_warning(
                    attachment.kind, attachment.file_name, MediaFailureReason.TOO_LARGE
                )
            )
            continue
        source_ref = attachment.source_ref
        if not source_ref:
            logger.debug(
                "media attachment skipped: source_unavailable",
                extra={
                    "attachment_index": index,
                    "attachment_kind": attachment.kind.value,
                    "reason": "unavailable",
                },
            )
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
            logger.debug(
                "media attachment unavailable",
                extra={
                    "attachment_index": index,
                    "attachment_kind": attachment.kind.value,
                    "reason": "unavailable",
                },
            )
            warnings.append(
                media_failure_warning(
                    attachment.kind, attachment.file_name, MediaFailureReason.UNAVAILABLE
                )
            )
            continue
        except AttachmentTooLargeError, AttachmentDownloadFailed, RecoverableInfraError:
            logger.debug(
                "media attachment download failed",
                extra={
                    "attachment_index": index,
                    "attachment_kind": attachment.kind.value,
                    "reason": "download_failed",
                },
            )
            warnings.append(
                media_failure_warning(
                    attachment.kind, attachment.file_name, MediaFailureReason.DOWNLOAD_FAILED
                )
            )
            continue
        logger.debug(
            "media attachment downloaded",
            extra={
                "attachment_index": index,
                "attachment_kind": attachment.kind.value,
                "operation_kind": operation_kind.value,
            },
        )
        planned.append(
            PlannedMedia(kind=operation_kind, file_path=path, file_name=attachment.file_name)
        )
    if warnings:
        logger.warning(
            "media preparation completed with warnings",
            extra={
                "attachment_count": len(attachments),
                "planned_media_count": len(planned),
                "warning_count": len(warnings),
            },
        )
    else:
        logger.debug(
            "media preparation completed",
            extra={
                "attachment_count": len(attachments),
                "planned_media_count": len(planned),
                "warning_count": 0,
            },
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
