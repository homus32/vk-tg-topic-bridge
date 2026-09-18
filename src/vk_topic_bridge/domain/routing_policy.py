"""VK peer routing policy: classify events BEFORE any auto-forward guard.

VK Bots Long Poll peer semantics (frozen draft, verified against VKCOM/vk-api-schema):
user DMs carry a positive user ``peer_id`` equal to ``from_id``; community conversations
carry ``peer_id = 2000000000 + chat_id``. Routing must classify the peer first so a DM
from one user can never consume the source-conversation guard slot of another peer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

COMMUNITY_CONVERSATION_BASE = 2_000_000_000


class PeerRoute(StrEnum):
    """Routing surface of one normalized VK peer."""

    USER_DM = "user_dm"
    COMMUNITY_CONVERSATION = "community_conversation"


@dataclass(frozen=True, slots=True)
class PeerClassification:
    """Route decision for one ``peer_id``; ``chat_id`` is set only for conversations."""

    route: PeerRoute
    chat_id: int | None


def classify_peer(peer_id: int) -> PeerClassification:
    """Classify one VK peer id into its routing surface."""
    if peer_id >= COMMUNITY_CONVERSATION_BASE:
        return PeerClassification(
            route=PeerRoute.COMMUNITY_CONVERSATION,
            chat_id=peer_id - COMMUNITY_CONVERSATION_BASE,
        )
    return PeerClassification(route=PeerRoute.USER_DM, chat_id=None)
