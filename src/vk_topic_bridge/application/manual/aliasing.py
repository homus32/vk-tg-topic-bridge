"""Application-level use cases for manual VK forwarding and alias management.

Manual forwarding is an intentional new operation: it never reuses the automatic
source-key dedup ledger, never silently falls back to General, and never adds a VK
reaction. Alias operations are ordinary short-transaction persistence.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from vk_topic_bridge.application.ports.unit_of_work import UnitOfWork
from vk_topic_bridge.domain.errors import InvalidAlias
from vk_topic_bridge.domain.policies.alias_policy import ensure_alias_available
from vk_topic_bridge.domain.value_objects import TopicInfo


@dataclass(frozen=True, slots=True)
class ManualDestinationOffer:
    """One selectable manual destination: General or a named topic.

    ``available`` is True for General and for topics that are active, not closed and
    not hidden in the persisted snapshot; stale entries remain visible for diagnostics
    with ``available=False``.
    """

    topic: TopicInfo
    available: bool


@dataclass(frozen=True, slots=True)
class ManualDestinationList:
    """What the VK UI shows after one forwarded message or an alias lookup.

    ``chat_id`` is the registered Telegram chat the destinations belong to; the VK UI
    needs it to build the ``Destination`` of a chosen offer.
    """

    chat_registered: bool
    destinations: tuple[ManualDestinationOffer, ...]
    chat_id: int | None = None


@dataclass(frozen=True, slots=True)
class AliasResolution:
    """Outcome of resolving one user alias by normalized text."""

    class Status(StrEnum):
        """FOUND publishes immediately; STALE/UNKNOWN route to the error UI."""

        FOUND = "found"
        STALE = "stale"
        UNKNOWN = "unknown"

    status: Status
    topic: TopicInfo | None = None
    chat_id: int | None = None


@dataclass(frozen=True, slots=True)
class AliasEntry:
    """One alias row joined with its topic title for the alias menu."""

    topic_id: int | None
    topic_title: str
    alias: str | None


def _topic_available(topic: TopicInfo) -> bool:
    return not topic.is_closed and not topic.is_hidden


_DEFAULT_GENERAL = TopicInfo(
    topic_id=None, title="General", is_general=True, is_closed=False, is_hidden=False
)


def _offers(topics: Sequence[TopicInfo]) -> tuple[ManualDestinationOffer, ...]:
    """General first (synthesized when the snapshot lacks it), then named topics."""
    general = [topic for topic in topics if topic.is_general or topic.topic_id is None]
    named = [topic for topic in topics if not (topic.is_general or topic.topic_id is None)]
    general_offer = general[0] if general else _DEFAULT_GENERAL
    offers = [ManualDestinationOffer(topic=general_offer, available=True)]
    offers.extend(
        ManualDestinationOffer(topic=topic, available=_topic_available(topic)) for topic in named
    )
    return tuple(offers)


class ManualForwarding:
    """Reads the manual destination list; publishing itself stays in the caller."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def destination_list(self, requesting_vk_user_id: int) -> ManualDestinationList:
        """General-first destinations; independent of both automatic destination flags."""
        async with self._uow_factory() as uow:
            state = await uow.bridge_settings.get()
            if state is None or state.telegram_chat_id is None:
                return ManualDestinationList(chat_registered=False, destinations=())
            topics = await uow.telegram_topics.list(state.telegram_chat_id)
            chat_id = state.telegram_chat_id
        return ManualDestinationList(
            chat_registered=True, destinations=_offers(topics), chat_id=chat_id
        )

    async def resolve_alias(self, vk_user_id: int, alias_text: str) -> AliasResolution:
        """Resolve by normalized text: FOUND / STALE / UNKNOWN (never title remap)."""
        normalized = alias_text.strip().lower()
        async with self._uow_factory() as uow:
            state = await uow.bridge_settings.get()
            chat_id = state.telegram_chat_id if state is not None else None
            rows = await uow.vk_aliases.list_for_user(vk_user_id)
            topics = await uow.telegram_topics.list(chat_id) if chat_id is not None else []
        match = next(
            (topic_id for topic_id, alias in rows if alias.strip().lower() == normalized),
            _MISSING,
        )
        if match is _MISSING:
            return AliasResolution(status=AliasResolution.Status.UNKNOWN)
        topic = next(
            (
                candidate
                for candidate in topics
                if candidate.topic_id == match and _topic_available(candidate)
            ),
            None,
        )
        if topic is None:
            return AliasResolution(status=AliasResolution.Status.STALE, chat_id=chat_id)
        return AliasResolution(status=AliasResolution.Status.FOUND, topic=topic, chat_id=chat_id)


_MISSING = object()


class AliasManager:
    """CRUD over per-user aliases in single short transactions."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def list_with_topics(self, vk_user_id: int) -> list[AliasEntry]:
        """Every snapshot topic with its current alias (or None), General included."""
        async with self._uow_factory() as uow:
            state = await uow.bridge_settings.get()
            chat_id = state.telegram_chat_id if state is not None else None
            topics = await uow.telegram_topics.list(chat_id) if chat_id is not None else []
            rows = await uow.vk_aliases.list_for_user(vk_user_id)
        by_topic = {topic_id: alias for topic_id, alias in rows}
        return [
            AliasEntry(
                topic_id=topic.topic_id,
                topic_title=topic.title,
                alias=by_topic.get(topic.topic_id),
            )
            for topic in topics
        ]

    async def upsert(self, vk_user_id: int, topic_id: int | None, alias: str) -> None:
        """Validate then persist; the General uniqueness conflict surfaces as InvalidAlias."""
        async with self._uow_factory() as uow:
            rows = await uow.vk_aliases.list_for_user(vk_user_id)
            existing = [existing_alias for tid, existing_alias in rows if tid != topic_id]
            normalized = ensure_alias_available(alias, user_aliases=existing)
            try:
                await uow.vk_aliases.upsert(vk_user_id, topic_id, alias, normalized)
            except ValueError as exc:
                raise InvalidAlias(str(exc)) from exc
            await uow.commit()

    async def delete(self, vk_user_id: int, topic_id: int | None) -> None:
        async with self._uow_factory() as uow:
            await uow.vk_aliases.delete(vk_user_id, topic_id)
            await uow.commit()
