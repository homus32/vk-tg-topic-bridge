"""Feature-specific readiness for automatic messages, wall and manual forwarding.

Replaces the linear single-track gate usage for forwarding decisions: readiness must
represent per-feature state, because "not configured yet" is a normal product state
(silent skip / clear VK error), not an operational failure.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from vk_topic_bridge.application.dto.settings import BridgeSettingsState, DestinationKind
from vk_topic_bridge.domain.value_objects import TopicInfo


@dataclass(frozen=True, slots=True)
class FeatureReadiness:
    """Per-feature readiness derived from persisted settings.

    ``messages_auto_ready``: chat registered AND the messages destination is usable —
    explicit configured General (kind ``GENERAL``) or an available persisted topic
    (kind ``NAMED_TOPIC`` with availability confirmed by the snapshot callback).
    ``wall_auto_ready``: same for the wall destination. ``manual_forwarding_ready``:
    chat registered AND at least one manual destination can be offered — an explicit
    General destination is configured anywhere, or the snapshot has at least one
    available named topic; it never depends on either automatic flag being set for its
    own feature. An infrastructure failure is NOT modeled here — it stays an
    operational error path.
    """

    messages_auto_ready: bool
    wall_auto_ready: bool
    manual_forwarding_ready: bool


def derive_feature_readiness(
    state: BridgeSettingsState,
    topic_available: Callable[[DestinationKind, int | None], bool],
) -> FeatureReadiness:
    """Pure derivation from the persisted settings snapshot.

    ``topic_available`` answers for a destination kind plus a topic id whether the
    destination is currently usable: ``GENERAL`` is always directly usable (explicit
    configured General, ``configured=True, topic_id=None``); ``NAMED_TOPIC`` consults
    the persisted snapshot (active + not closed + not hidden). The manual-readiness
    branch queries ``NAMED_TOPIC`` with ``topic_id=None`` meaning "does at least one
    available named topic exist". ``UNSET`` never yields a usable destination. The
    explicit-General-vs-unset distinction comes from the configured flag pair in
    ``BridgeSettingsState`` — never from sentinel topic ids. No I/O of its own.
    """
    if state.telegram_chat_id is None:
        return FeatureReadiness(
            messages_auto_ready=False,
            wall_auto_ready=False,
            manual_forwarding_ready=False,
        )

    messages_kind = state.messages_destination_kind()
    wall_kind = state.wall_destination_kind()
    return FeatureReadiness(
        messages_auto_ready=_destination_usable(
            messages_kind, state.telegram_messages_topic_id, topic_available
        ),
        wall_auto_ready=_destination_usable(
            wall_kind, state.telegram_wall_topic_id, topic_available
        ),
        manual_forwarding_ready=(
            messages_kind is DestinationKind.GENERAL
            or wall_kind is DestinationKind.GENERAL
            or topic_available(DestinationKind.NAMED_TOPIC, None)
        ),
    )


def _destination_usable(
    kind: DestinationKind,
    topic_id: int | None,
    topic_available: Callable[[DestinationKind, int | None], bool],
) -> bool:
    if kind is DestinationKind.UNSET:
        return False
    return topic_available(kind, topic_id)


def snapshot_availability(
    topics: Sequence[TopicInfo],
) -> Callable[[DestinationKind, int | None], bool]:
    """Build the ``topic_available`` callback over one persisted topic snapshot.

    Available means present in the snapshot (the repository already filters inactive
    rows) and neither closed nor hidden. ``GENERAL`` is a configured destination by
    itself; ``NAMED_TOPIC`` with no id asks whether any usable named topic exists, which
    is how the manual-readiness branch is answered.
    """
    usable_ids = {topic.topic_id for topic in topics if _usable(topic)}

    def is_available(kind: DestinationKind, topic_id: int | None) -> bool:
        if kind is DestinationKind.GENERAL:
            return True
        if kind is DestinationKind.UNSET:
            return False
        if topic_id is None:
            return any(topic_id_candidate is not None for topic_id_candidate in usable_ids)
        return topic_id in usable_ids

    return is_available


def unavailable_reason(topics: Sequence[TopicInfo], topic_id: int) -> str:
    """Classify why a named destination topic is unusable: ``missing``/``closed``/``hidden``."""
    topic = next((candidate for candidate in topics if candidate.topic_id == topic_id), None)
    if topic is None:
        return "missing"
    if topic.is_closed:
        return "closed"
    if topic.is_hidden:
        return "hidden"
    return "missing"


def _usable(topic: TopicInfo) -> bool:
    return not topic.is_closed and not topic.is_hidden
