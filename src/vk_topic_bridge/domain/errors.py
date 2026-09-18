"""Domain error taxonomy: validation, recoverable infrastructure and fatal startup."""

from enum import StrEnum


class DomainError(Exception):
    """Base class for every domain-level failure."""


class InvalidAlias(DomainError):
    """Alias is empty, malformed, reserved or already used by the same user."""


class TopicNotFound(DomainError):
    """Requested Telegram topic does not exist for the registered chat."""


class UnsupportedAttachment(DomainError):
    """Attachment kind cannot be handled by the bridge."""


class AttachmentTooLargeError(DomainError):
    """Attachment exceeds the 50 MB policy limit; skipped with a per-item warning."""


class RecoverableInfraError(DomainError):
    """External dependency failed; the use case decides fallback or partial success."""


class AttachmentDownloadFailed(RecoverableInfraError):
    """Attachment download failed; publication continues with a warning item."""


class MediaUnavailableError(RecoverableInfraError):
    """One attachment has no downloadable resource (e.g. a video without files)."""


class TargetTopicUnavailable(RecoverableInfraError):
    """Destination topic is temporarily unavailable for publication."""


class VKProfileLookupFailed(RecoverableInfraError):
    """VK profile lookup failed; publication may continue without a profile link."""


class FatalStartupReason(StrEnum):
    """Why the process must refuse to start polling."""

    INVALID_SETTINGS = "invalid_settings"
    DB_UNAVAILABLE = "db_unavailable"
    MIGRATION_FAILED = "migration_failed"
    BOT_API_UNREACHABLE = "bot_api_unreachable"
    TELETHON_UNAUTHORIZED = "telethon_unauthorized"
    TELETHON_CHAT_ACCESS = "telethon_chat_access"
    TOPICS_UNAVAILABLE = "topics_unavailable"
    VK_IDENTITY = "vk_identity"
    VK_LONGPOLL_DISABLED = "vk_longpoll_disabled"


class FatalStartupError(DomainError):
    """Startup cannot proceed; polling must not start."""

    reason: FatalStartupReason

    def __init__(self, reason: FatalStartupReason, detail: str = "") -> None:
        self.reason = reason
        super().__init__(reason.value if not detail else f"{reason.value}: {detail}")
