"""Wall post identity helpers: source key and original post URL.

The ``SourceWallPost`` value object lives in ``domain/value_objects.py`` next to the
other normalized sources (avoids a circular import); this module keeps the identity
helpers and re-exports the type.
"""

from __future__ import annotations

from vk_topic_bridge.domain.value_objects import SourceWallPost

__all__ = ["SourceWallPost", "wall_post_url", "wall_source_key"]


def wall_source_key(group_id: int, owner_id: int, post_id: int) -> str:
    """Stable dedup key for one wall post.

    Inputs are validated ints from the ``wall_post_new`` payload; a negative community
    ``owner_id`` is preserved verbatim so the key never collides with message keys.
    """
    return f"{group_id}:{owner_id}:{post_id}"


def wall_post_url(owner_id: int, post_id: int) -> str:
    """Original VK post URL used in the mandatory source link (AC-14.4)."""
    return f"https://vk.com/wall{owner_id}_{post_id}"
