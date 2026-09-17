"""Alias policy: normalization, reserved names and per-user uniqueness."""

from collections.abc import Sequence

from vk_topic_bridge.domain.errors import InvalidAlias

# Permanent keyboard and menu buttons of the VK bot (docs/04-fsm-and-ui.md §1-§5).
RESERVED_ALIASES = frozenset(
    {
        "начать",
        "помощь",
        "помоги",
        "help",
        "алиасы",
        "добавить",
        "изменить",
        "удалить",
        "← назад",
        "отмена",
        "да",
        "обновить список",
    }
)


def normalize_alias(raw: str) -> str:
    """Lowercase, trim and reject aliases with whitespace; comparison is case-insensitive."""
    normalized = raw.strip().lower()
    if not normalized:
        raise InvalidAlias("alias must not be empty")
    if any(char.isspace() for char in normalized):
        raise InvalidAlias("alias must not contain whitespace")
    return normalized


def ensure_alias_available(raw: str, *, user_aliases: Sequence[str]) -> str:
    normalized = normalize_alias(raw)
    if normalized in RESERVED_ALIASES:
        raise InvalidAlias(f"alias {raw!r} collides with a system command or button")
    if normalized in {alias.strip().lower() for alias in user_aliases}:
        raise InvalidAlias(f"alias {raw!r} is already used by this user")
    return normalized
