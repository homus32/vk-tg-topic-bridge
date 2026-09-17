"""Pure guards for the fail-closed delivery state machine (plan §6)."""

from vk_topic_bridge.domain.enums import PublicationStatus

LEGAL_TRANSITIONS: frozenset[tuple[PublicationStatus, PublicationStatus]] = frozenset(
    {
        (PublicationStatus.RESERVED, PublicationStatus.SEND_STARTED),
        (PublicationStatus.RESERVED, PublicationStatus.FAILED_BEFORE_SEND),
        (PublicationStatus.FAILED_BEFORE_SEND, PublicationStatus.SEND_STARTED),
        (PublicationStatus.SEND_STARTED, PublicationStatus.PUBLISHED),
        (PublicationStatus.SEND_STARTED, PublicationStatus.AMBIGUOUS),
        (PublicationStatus.SEND_STARTED, PublicationStatus.FAILED_PERMANENT),
    }
)

# After any of these statuses a duplicate event must never trigger a republish.
_NO_REPUBLISH_STATUSES = frozenset(
    {
        PublicationStatus.SEND_STARTED,
        PublicationStatus.PUBLISHED,
        PublicationStatus.AMBIGUOUS,
        PublicationStatus.FAILED_PERMANENT,
    }
)

_RETRYABLE_STATUSES = frozenset({PublicationStatus.RESERVED, PublicationStatus.FAILED_BEFORE_SEND})

_TERMINAL_STATUSES = frozenset(
    {
        PublicationStatus.PUBLISHED,
        PublicationStatus.AMBIGUOUS,
        PublicationStatus.FAILED_PERMANENT,
    }
)


def is_legal_transition(current: PublicationStatus, target: PublicationStatus) -> bool:
    return (current, target) in LEGAL_TRANSITIONS


def must_not_republish(status: PublicationStatus) -> bool:
    """Short-circuit guard for duplicate events; ``send_started`` counts as ambiguous."""
    return status in _NO_REPUBLISH_STATUSES


def can_retry(status: PublicationStatus) -> bool:
    """Only a status without recorded network intent may be reclaimed and retried."""
    return status in _RETRYABLE_STATUSES


def is_terminal(status: PublicationStatus) -> bool:
    return status in _TERMINAL_STATUSES
