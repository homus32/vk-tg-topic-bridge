"""Application-level failures raised across port and use-case boundaries."""

from vk_topic_bridge.domain.errors import DomainError


class PublicationAmbiguousError(DomainError):
    """Telegram outcome is unknown after send intent: timeout, reset, cancel or no response."""

    code: str | None

    def __init__(self, message: str = "", code: str | None = None) -> None:
        self.code = code
        super().__init__(message)


class PublicationRejectedError(DomainError):
    """Definitive Bot API rejection that created no message (e.g. message thread not found)."""

    code: str | None

    def __init__(self, message: str = "", code: str | None = None) -> None:
        self.code = code
        super().__init__(message)


TELEGRAM_TOPIC_NOT_FOUND_CODE = "telegram_topic_not_found"


def is_stale_topic_rejection(error: BaseException) -> bool:
    return (
        isinstance(error, PublicationRejectedError) and error.code == TELEGRAM_TOPIC_NOT_FOUND_CODE
    )


class ProvisioningError(DomainError):
    """Chat or topic provisioning precondition failed (empty topic list, missing capabilities)."""


class ReadinessError(DomainError):
    """Operation invoked while the readiness gate is below the required state."""
