"""Pure in-memory readiness gate; no I/O, safe to share within one process."""

from vk_topic_bridge.application.dto.readiness import ReadinessState
from vk_topic_bridge.application.errors import ReadinessError


class InMemoryReadinessGate:
    """Monotonic gate: ``advance`` never moves backwards, ``reset`` is explicit."""

    def __init__(self) -> None:
        self._state = ReadinessState.CORE_READY

    def current(self) -> ReadinessState:
        return self._state

    def advance(self, state: ReadinessState) -> None:
        if state.rank > self._state.rank:
            self._state = state

    def require(self, state: ReadinessState) -> None:
        if self._state.rank < state.rank:
            raise ReadinessError(f"readiness {self._state.value} is below required {state.value}")

    def reset(self) -> None:
        self._state = ReadinessState.CORE_READY
