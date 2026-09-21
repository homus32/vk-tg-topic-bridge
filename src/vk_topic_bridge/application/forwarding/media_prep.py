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
    MediaWarning,
    media_failure_warning,
    media_link_warning,
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
) -> tuple[tuple[PlannedMedia, ...], list[MediaWarning]]:
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
    warnings: list[MediaWarning] = []
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
            if _append_video_link_warning(attachment, index, warnings):
                continue
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
        if not attachment.source_ref:
            link_url = _video_link(attachment)
            if link_url is not None:
                warnings.append(media_link_warning(attachment.file_name, link_url))
                continue
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
            url = await downloader.resolve_url(attachment)
            path = await downloader.download(attachment, url)
        except MediaUnavailableError as exc:
            if _append_video_link_warning(attachment, index, warnings, exc.fallback_url):
                continue
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
            if _append_video_link_warning(attachment, index, warnings):
                continue
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


def _video_link(attachment: Attachment, fallback_url: str | None = None) -> str | None:
    if attachment.kind is not AttachmentKind.VIDEO:
        return None
    return fallback_url or attachment.link_url


def _append_video_link_warning(
    attachment: Attachment,
    index: int,
    warnings: list[MediaWarning],
    fallback_url: str | None = None,
) -> bool:
    link_url = _video_link(attachment, fallback_url)
    if link_url is None:
        return False
    logger.debug(
        "media attachment link fallback",
        extra={
            "attachment_index": index,
            "attachment_kind": attachment.kind.value,
            "resolution_source": "vk_link",
        },
    )
    warnings.append(media_link_warning(attachment.file_name, link_url))
    return True
