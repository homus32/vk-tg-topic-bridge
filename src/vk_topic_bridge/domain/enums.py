"""Domain enums: event kinds, delivery lifecycle and attachment kinds."""

from enum import StrEnum


class SourceType(StrEnum):
    """External event family a delivery record belongs to."""

    VK_MESSAGE = "vk_message"
    VK_WALL = "vk_wall"


class PublicationStatus(StrEnum):
    """Fail-closed Telegram publication lifecycle (plan §6)."""

    RESERVED = "reserved"
    SEND_STARTED = "send_started"
    PUBLISHED = "published"
    AMBIGUOUS = "ambiguous"
    FAILED_BEFORE_SEND = "failed_before_send"
    FAILED_PERMANENT = "failed_permanent"


class ReactionStatus(StrEnum):
    """VK 👍 lifecycle, strictly after a confirmed publication."""

    NOT_DUE = "not_due"
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    AMBIGUOUS = "ambiguous"


class AttachmentKind(StrEnum):
    """Attachment-neutral classification kept compatible with the Stage 9 downloader."""

    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"
    UNSUPPORTED = "unsupported"
