"""Readiness phases shared by the gate, its port and consuming use cases."""

from enum import StrEnum


class ReadinessState(StrEnum):
    """Ordered startup phases; the process may serve a phase only after reaching it."""

    CORE_READY = "core_ready"
    CHAT_REGISTERED = "chat_registered"
    TOPICS_READY = "topics_ready"
    DESTINATION_CONFIRMED = "destination_confirmed"
    FORWARDING_ENABLED = "forwarding_enabled"

    @property
    def rank(self) -> int:
        """0-based position in declaration order; higher ranks are strictly later phases."""
        return list(ReadinessState).index(self)
