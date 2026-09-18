"""Pure contract tests for feature-specific readiness derivation (plan task 3).

Availability callback convention (frozen by the skeleton docstring):
- ``GENERAL``: the explicit configured General is always directly usable.
- ``NAMED_TOPIC`` + concrete id: snapshot must contain the topic and it must be
  active, not closed and not hidden.
- ``NAMED_TOPIC`` + ``None``: "at least one available named topic exists" — this is
  the query the manual-readiness branch uses to learn whether any manual destination
  besides an explicit General exists.
"""

from collections.abc import Callable
from dataclasses import replace

from vk_topic_bridge.application.dto.settings import BridgeSettingsState, DestinationKind
from vk_topic_bridge.application.readiness_features import derive_feature_readiness


def _state(**overrides: object) -> BridgeSettingsState:
    base = BridgeSettingsState(
        telegram_chat_id=-100123,
        telegram_chat_title="Chat",
        auto_forward_all=True,
        auto_forward_hashtags=True,
        auto_forward_wall=True,
        telegram_messages_topic_id=None,
        telegram_wall_topic_id=None,
        telegram_messages_topic_configured=False,
        telegram_wall_topic_configured=False,
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def _availability(available_ids: frozenset[int]) -> Callable[[DestinationKind, int | None], bool]:
    """Snapshot-backed availability: explicit ids plus the "any topic" query."""

    def check(kind: DestinationKind, topic_id: int | None) -> bool:
        if kind is DestinationKind.GENERAL:
            return True
        if kind is DestinationKind.NAMED_TOPIC:
            if topic_id is None:
                return bool(available_ids)
            return topic_id in available_ids
        return False

    return check


def test_unregistered_chat_blocks_everything() -> None:
    state = _state(
        telegram_chat_id=None,
        telegram_messages_topic_configured=True,
        telegram_wall_topic_configured=True,
    )

    readiness = derive_feature_readiness(state, _availability(frozenset({5})))

    assert not readiness.messages_auto_ready
    assert not readiness.wall_auto_ready
    assert not readiness.manual_forwarding_ready


def test_unset_destinations_keep_manual_ready_via_available_topic() -> None:
    state = _state()

    readiness = derive_feature_readiness(state, _availability(frozenset({5})))

    assert not readiness.messages_auto_ready
    assert not readiness.wall_auto_ready
    assert readiness.manual_forwarding_ready


def test_explicit_general_configured_is_ready_without_snapshot_topics() -> None:
    state = _state(
        telegram_messages_topic_configured=True,
        telegram_wall_topic_configured=True,
    )

    readiness = derive_feature_readiness(state, _availability(frozenset()))

    assert readiness.messages_auto_ready
    assert readiness.wall_auto_ready
    assert readiness.manual_forwarding_ready


def test_named_messages_topic_requires_availability() -> None:
    available = _state(
        telegram_messages_topic_id=7,
        telegram_messages_topic_configured=True,
    )
    stale = replace(available, telegram_messages_topic_id=8)

    ready = derive_feature_readiness(available, _availability(frozenset({7})))
    not_ready = derive_feature_readiness(stale, _availability(frozenset({7})))

    assert ready.messages_auto_ready
    assert not not_ready.messages_auto_ready


def test_stale_named_topic_is_not_auto_ready() -> None:
    state = _state(
        telegram_messages_topic_id=7,
        telegram_messages_topic_configured=True,
    )

    readiness = derive_feature_readiness(state, _availability(frozenset()))

    assert not readiness.messages_auto_ready


def test_manual_ready_without_auto_destination() -> None:
    state = _state()

    readiness = derive_feature_readiness(state, _availability(frozenset({9})))

    assert not readiness.messages_auto_ready
    assert not readiness.wall_auto_ready
    assert readiness.manual_forwarding_ready


def test_manual_not_ready_when_only_stale_topic_and_no_general() -> None:
    state = _state(
        telegram_messages_topic_id=7,
        telegram_messages_topic_configured=True,
    )

    readiness = derive_feature_readiness(state, _availability(frozenset()))

    assert not readiness.messages_auto_ready
    assert not readiness.manual_forwarding_ready


def test_wall_stale_does_not_affect_messages_feature() -> None:
    state = _state(
        telegram_messages_topic_id=7,
        telegram_messages_topic_configured=True,
        telegram_wall_topic_id=9,
        telegram_wall_topic_configured=True,
    )

    readiness = derive_feature_readiness(state, _availability(frozenset({7})))

    assert readiness.messages_auto_ready
    assert not readiness.wall_auto_ready
    assert readiness.manual_forwarding_ready


def test_explicit_general_wall_keeps_manual_ready_despite_stale_messages() -> None:
    state = _state(
        telegram_messages_topic_id=7,
        telegram_messages_topic_configured=True,
        telegram_wall_topic_configured=True,
    )

    readiness = derive_feature_readiness(state, _availability(frozenset()))

    assert not readiness.messages_auto_ready
    assert readiness.wall_auto_ready
    assert readiness.manual_forwarding_ready
