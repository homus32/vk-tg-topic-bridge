"""VK per-user ephemeral FSM states and a small in-memory state store.

State is keyed by ``from_id`` (never peer_id alone), so two DM users never share state;
the target chat/peer for replies is kept in the state payload.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class VkUiState(StrEnum):
    """Ephemeral VK user states (docs/04 §4-5 + frozen addendum)."""

    IDLE = "idle"
    WAIT_DESTINATION = "wait_destination"
    ALIAS_MENU = "alias_menu"
    ALIAS_ADD_WAIT_TOPIC = "alias_add_wait_topic"
    ALIAS_ADD_WAIT_VALUE = "alias_add_wait_value"
    ALIAS_DELETE_WAIT_TOPIC = "alias_delete_wait_topic"


@dataclass(slots=True)
class VkUserSession:
    """One user's ephemeral session payload.

    ``pending_message`` is retained for the legacy destination state;
    ``manual_pending_message`` overlays manual forwarding without replacing an active
    alias FSM; ``pending_topic_id`` carries the selected alias topic. Nothing here is
    ever written to SQLite.
    """

    state: VkUiState = VkUiState.IDLE
    pending_message: object | None = None
    manual_pending_message: object | None = None
    pending_alias_action: str | None = None
    pending_topic_id: int | None = None
    context: dict[str, str] = field(default_factory=dict)


class VkSessionStore:
    """In-memory per-user session holder keyed by ``from_id``.

    Unbounded growth is acceptable for this deployment scale; ``clear`` is called on
    cancel/success/error exits and resets the session to a fresh IDLE instance.
    """

    def __init__(self) -> None:
        self._sessions: dict[int, VkUserSession] = {}

    def get(self, user_id: int) -> VkUserSession:
        session = self._sessions.get(user_id)
        if session is None:
            session = VkUserSession()
            self._sessions[user_id] = session
        return session

    def peek(self, user_id: int) -> VkUserSession | None:
        return self._sessions.get(user_id)

    def set(self, user_id: int, session: VkUserSession) -> None:
        self._sessions[user_id] = session

    def clear(self, user_id: int) -> None:
        self._sessions.pop(user_id, None)
