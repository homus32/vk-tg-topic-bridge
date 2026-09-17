"""Unit tests for the fail-closed delivery transition guards (plan §6)."""

import pytest

from vk_topic_bridge.domain.enums import PublicationStatus
from vk_topic_bridge.domain.policies import delivery_policy


def test_reserved_to_send_started_is_legal() -> None:
    assert (
        delivery_policy.is_legal_transition(
            PublicationStatus.RESERVED, PublicationStatus.SEND_STARTED
        )
        is True
    )


def test_reserved_to_failed_before_send_is_legal() -> None:
    assert (
        delivery_policy.is_legal_transition(
            PublicationStatus.RESERVED, PublicationStatus.FAILED_BEFORE_SEND
        )
        is True
    )


def test_send_started_to_published_is_legal() -> None:
    assert (
        delivery_policy.is_legal_transition(
            PublicationStatus.SEND_STARTED, PublicationStatus.PUBLISHED
        )
        is True
    )


def test_send_started_to_ambiguous_is_legal() -> None:
    assert (
        delivery_policy.is_legal_transition(
            PublicationStatus.SEND_STARTED, PublicationStatus.AMBIGUOUS
        )
        is True
    )


def test_send_started_to_failed_permanent_is_legal() -> None:
    assert (
        delivery_policy.is_legal_transition(
            PublicationStatus.SEND_STARTED, PublicationStatus.FAILED_PERMANENT
        )
        is True
    )


def test_failed_before_send_can_be_retried() -> None:
    assert (
        delivery_policy.is_legal_transition(
            PublicationStatus.FAILED_BEFORE_SEND, PublicationStatus.SEND_STARTED
        )
        is True
    )


def test_published_cannot_restart_publication() -> None:
    assert (
        delivery_policy.is_legal_transition(
            PublicationStatus.PUBLISHED, PublicationStatus.SEND_STARTED
        )
        is False
    )


def test_ambiguous_cannot_be_auto_promoted_to_published() -> None:
    assert (
        delivery_policy.is_legal_transition(
            PublicationStatus.AMBIGUOUS, PublicationStatus.PUBLISHED
        )
        is False
    )


def test_failed_permanent_cannot_restart_publication() -> None:
    assert (
        delivery_policy.is_legal_transition(
            PublicationStatus.FAILED_PERMANENT, PublicationStatus.RESERVED
        )
        is False
    )


def test_send_started_cannot_go_back_to_reserved() -> None:
    assert (
        delivery_policy.is_legal_transition(
            PublicationStatus.SEND_STARTED, PublicationStatus.RESERVED
        )
        is False
    )


@pytest.mark.parametrize(
    "status",
    [
        PublicationStatus.PUBLISHED,
        PublicationStatus.SEND_STARTED,
        PublicationStatus.AMBIGUOUS,
        PublicationStatus.FAILED_PERMANENT,
    ],
)
def test_duplicate_event_short_circuits_without_republish(status: PublicationStatus) -> None:
    assert delivery_policy.must_not_republish(status) is True
    assert delivery_policy.can_retry(status) is False


@pytest.mark.parametrize(
    "status", [PublicationStatus.RESERVED, PublicationStatus.FAILED_BEFORE_SEND]
)
def test_retryable_statuses_are_reclaimable(status: PublicationStatus) -> None:
    assert delivery_policy.must_not_republish(status) is False
    assert delivery_policy.can_retry(status) is True


@pytest.mark.parametrize(
    "status",
    [
        PublicationStatus.PUBLISHED,
        PublicationStatus.AMBIGUOUS,
        PublicationStatus.FAILED_PERMANENT,
    ],
)
def test_terminal_statuses_have_no_legal_successor(status: PublicationStatus) -> None:
    assert delivery_policy.is_terminal(status) is True


@pytest.mark.parametrize(
    "status",
    [
        PublicationStatus.RESERVED,
        PublicationStatus.SEND_STARTED,
        PublicationStatus.FAILED_BEFORE_SEND,
    ],
)
def test_non_terminal_statuses_have_legal_successors(status: PublicationStatus) -> None:
    assert delivery_policy.is_terminal(status) is False
