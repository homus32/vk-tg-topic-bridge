"""Contract tests for the pure in-memory readiness gate."""

import pytest

from vk_topic_bridge.application.dto.readiness import ReadinessState
from vk_topic_bridge.application.errors import ReadinessError
from vk_topic_bridge.application.ports.readiness import ReadinessPort
from vk_topic_bridge.application.readiness import InMemoryReadinessGate


def test_gate_starts_at_core_ready() -> None:
    assert InMemoryReadinessGate().current() is ReadinessState.CORE_READY


def test_gate_advances_through_all_phases() -> None:
    gate = InMemoryReadinessGate()

    for state in ReadinessState:
        gate.advance(state)
        assert gate.current() is state


def test_gate_ignores_backward_advance() -> None:
    gate = InMemoryReadinessGate()

    gate.advance(ReadinessState.TOPICS_READY)
    gate.advance(ReadinessState.CHAT_REGISTERED)

    assert gate.current() is ReadinessState.TOPICS_READY


def test_require_raises_when_gate_is_below_required_rank() -> None:
    gate = InMemoryReadinessGate()
    gate.advance(ReadinessState.CHAT_REGISTERED)

    with pytest.raises(ReadinessError):
        gate.require(ReadinessState.TOPICS_READY)


def test_require_passes_at_or_below_current_rank() -> None:
    gate = InMemoryReadinessGate()
    gate.advance(ReadinessState.TOPICS_READY)

    gate.require(ReadinessState.TOPICS_READY)
    gate.require(ReadinessState.CORE_READY)

    assert gate.current() is ReadinessState.TOPICS_READY


def test_reset_returns_gate_to_core_ready() -> None:
    gate = InMemoryReadinessGate()
    gate.advance(ReadinessState.FORWARDING_ENABLED)

    gate.reset()

    assert gate.current() is ReadinessState.CORE_READY

    gate.advance(ReadinessState.CHAT_REGISTERED)

    assert gate.current() is ReadinessState.CHAT_REGISTERED


def test_gate_satisfies_readiness_port() -> None:
    gate: ReadinessPort = InMemoryReadinessGate()

    gate.advance(ReadinessState.CHAT_REGISTERED)
    gate.require(ReadinessState.CORE_READY)

    assert gate.current() is ReadinessState.CHAT_REGISTERED
