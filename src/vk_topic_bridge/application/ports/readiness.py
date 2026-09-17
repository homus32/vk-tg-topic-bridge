"""Readiness port consumed by use cases before serving a phase."""

from typing import Protocol, runtime_checkable

from vk_topic_bridge.application.dto.readiness import ReadinessState


@runtime_checkable
class ReadinessPort(Protocol):
    """Process-local readiness gate; ``require`` raises ``ReadinessError`` when below."""

    def current(self) -> ReadinessState: ...
    def advance(self, state: ReadinessState) -> None: ...
    def require(self, state: ReadinessState) -> None: ...
