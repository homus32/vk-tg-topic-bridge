"""Aliasing use-case tests: destination list semantics, alias resolution, CRUD.

In-memory fakes only: no SQLite, no network. The fake alias repository emulates the
production partial-unique General index via a pre-check, mirroring migration 0002.
"""

from __future__ import annotations

from collections.abc import Sequence
from types import TracebackType
from typing import Self

import pytest

from tests.acceptance._ledger import DeliveryLedger
from vk_topic_bridge.application.dto.settings import BridgeSettingsState, ToggleKind
from vk_topic_bridge.application.manual.aliasing import (
    AliasManager,
    AliasResolution,
    ManualForwarding,
)
from vk_topic_bridge.domain.errors import InvalidAlias
from vk_topic_bridge.domain.value_objects import TopicInfo

CHAT_ID = -1001234567890
GENERAL = TopicInfo(
    topic_id=None, title="General", is_general=True, is_closed=False, is_hidden=False
)
NEWS = TopicInfo(topic_id=7, title="Новости", is_general=False, is_closed=False, is_hidden=False)
CLOSED = TopicInfo(topic_id=8, title="Закрытая", is_general=False, is_closed=True, is_hidden=False)
HIDDEN = TopicInfo(topic_id=9, title="Скрытая", is_general=False, is_closed=False, is_hidden=True)


class FakeSettingsRepository:
    def __init__(self, state: BridgeSettingsState) -> None:
        self.state = state

    async def get(self) -> BridgeSettingsState | None:
        return self.state

    async def upsert_chat(self, chat_id: int, title: str | None) -> BridgeSettingsState:
        raise AssertionError("not used")

    async def set_messages_topic(self, topic_id: int | None) -> BridgeSettingsState:
        raise AssertionError("not used")

    async def set_wall_topic(self, topic_id: int | None) -> BridgeSettingsState:
        raise AssertionError("not used")

    async def set_toggle(self, kind: ToggleKind, value: bool) -> BridgeSettingsState:
        raise AssertionError("not used")

    async def reset(self) -> BridgeSettingsState:
        raise AssertionError("not used")


class FakeTopicsRepository:
    def __init__(self, topics: Sequence[TopicInfo]) -> None:
        self.topics = list(topics)

    async def replace_all(self, chat_id: int, topics: Sequence[TopicInfo]) -> None:
        raise AssertionError("not used")

    async def list(self, chat_id: int) -> list[TopicInfo]:
        return list(self.topics)

    async def mark_missing(self, chat_id: int, seen_topic_ids: Sequence[int | None]) -> None:
        raise AssertionError("not used")

    async def delete_chat(self, chat_id: int) -> None:
        raise AssertionError("not used")


class FakeAliasesRepository:
    """Emulates the General partial-unique index; stores the NORMALIZED alias."""

    def __init__(self, rows: Sequence[tuple[int | None, str]] = ()) -> None:
        self.rows: list[tuple[int | None, str]] = list(rows)

    async def list_for_user(self, vk_user_id: int) -> list[tuple[int | None, str]]:
        return list(self.rows)

    async def upsert(
        self, vk_user_id: int, topic_id: int | None, alias: str, alias_normalized: str
    ) -> None:
        if topic_id is None and any(existing is None for existing, _ in self.rows):
            msg = "general alias already exists"
            raise ValueError(msg)
        self.rows = [(tid, a) for tid, a in self.rows if tid != topic_id]
        self.rows.append((topic_id, alias_normalized))

    async def delete_all(self) -> int:
        deleted = len(self.rows)
        self.rows = []
        return deleted

    async def delete(self, vk_user_id: int, topic_id: int | None) -> None:
        self.rows = [(tid, a) for tid, a in self.rows if tid != topic_id]


class FakeUnitOfWork:
    def __init__(
        self,
        *,
        settings: BridgeSettingsState,
        topics: Sequence[TopicInfo],
        aliases: Sequence[tuple[int | None, str]] = (),
    ) -> None:
        self.bridge_settings = FakeSettingsRepository(settings)
        self.telegram_topics = FakeTopicsRepository(topics)
        self.vk_aliases = FakeAliasesRepository(aliases)
        self.deliveries = DeliveryLedger()
        self.commits = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


def _settings() -> BridgeSettingsState:
    base = BridgeSettingsState.defaults()
    return BridgeSettingsState(
        telegram_chat_id=CHAT_ID,
        telegram_chat_title="Тест",
        auto_forward_all=base.auto_forward_all,
        auto_forward_hashtags=base.auto_forward_hashtags,
        auto_forward_wall=base.auto_forward_wall,
        telegram_messages_topic_id=base.telegram_messages_topic_id,
        telegram_wall_topic_id=base.telegram_wall_topic_id,
    )


# --- destination_list -----------------------------------------------------------


async def test_destination_list_prepends_general_and_keeps_available_topics() -> None:
    uow = FakeUnitOfWork(settings=_settings(), topics=[NEWS, CLOSED, HIDDEN])
    forwarding = ManualForwarding(lambda: uow)

    result = await forwarding.destination_list(requesting_vk_user_id=555)

    assert result.chat_registered is True
    offered = result.destinations
    assert offered[0].topic == GENERAL
    assert offered[0].available is True
    ordered = [offer.topic.title for offer in offered]
    assert ordered == ["General", "Новости", "Закрытая", "Скрытая"]
    availability = {offer.topic.title: offer.available for offer in offered}
    assert availability["Новости"] is True
    assert availability["Закрытая"] is False
    assert availability["Скрытая"] is False


async def test_destination_list_does_not_depend_on_automatic_destinations() -> None:
    uow = FakeUnitOfWork(settings=_settings(), topics=[NEWS])
    forwarding = ManualForwarding(lambda: uow)

    result = await forwarding.destination_list(requesting_vk_user_id=555)

    assert result.destinations
    kinds = {
        "messages": uow.bridge_settings.state.messages_destination_kind(),
        "wall": uow.bridge_settings.state.wall_destination_kind(),
    }
    assert kinds["messages"].value == "unset"
    assert kinds["wall"].value == "unset"


async def test_destination_list_without_chat_is_not_registered() -> None:
    settings = _settings()
    settings = BridgeSettingsState.defaults()
    uow = FakeUnitOfWork(settings=settings, topics=[NEWS])
    forwarding = ManualForwarding(lambda: uow)

    result = await forwarding.destination_list(requesting_vk_user_id=555)

    assert result.chat_registered is False
    assert result.destinations == ()


# --- resolve_alias ---------------------------------------------------------------


async def test_resolve_alias_found_for_available_topic() -> None:
    uow = FakeUnitOfWork(settings=_settings(), topics=[NEWS], aliases=[(7, "важное")])
    forwarding = ManualForwarding(lambda: uow)

    resolution = await forwarding.resolve_alias(555, "ВАЖНОЕ")

    assert resolution.status is AliasResolution.Status.FOUND
    assert resolution.topic is not None
    assert resolution.topic.topic_id == 7


async def test_stale_alias_is_not_found_when_topic_inactive() -> None:
    uow = FakeUnitOfWork(settings=_settings(), topics=[], aliases=[(7, "важное")])
    forwarding = ManualForwarding(lambda: uow)

    resolution = await forwarding.resolve_alias(555, "важное")

    assert resolution.status is AliasResolution.Status.STALE
    assert resolution.topic is None


async def test_stale_alias_when_topic_closed() -> None:
    uow = FakeUnitOfWork(settings=_settings(), topics=[CLOSED], aliases=[(8, "закрытое")])
    forwarding = ManualForwarding(lambda: uow)

    resolution = await forwarding.resolve_alias(555, "закрытое")

    assert resolution.status is AliasResolution.Status.STALE


async def test_stale_alias_when_topic_hidden() -> None:
    uow = FakeUnitOfWork(settings=_settings(), topics=[HIDDEN], aliases=[(9, "скрытое")])
    forwarding = ManualForwarding(lambda: uow)

    resolution = await forwarding.resolve_alias(555, "скрытое")

    assert resolution.status is AliasResolution.Status.STALE


async def test_unknown_alias_is_unknown() -> None:
    uow = FakeUnitOfWork(settings=_settings(), topics=[NEWS], aliases=[])
    forwarding = ManualForwarding(lambda: uow)

    resolution = await forwarding.resolve_alias(555, "нет-такого")

    assert resolution.status is AliasResolution.Status.UNKNOWN


async def test_general_alias_resolves_to_general_destination() -> None:
    uow = FakeUnitOfWork(settings=_settings(), topics=[GENERAL], aliases=[(None, "общий")])
    forwarding = ManualForwarding(lambda: uow)

    resolution = await forwarding.resolve_alias(555, "общий")

    assert resolution.status is AliasResolution.Status.FOUND
    assert resolution.topic is not None
    assert resolution.topic.topic_id is None
    assert resolution.topic.is_general is True


async def test_stale_alias_is_never_remapped_by_title() -> None:
    renamed = TopicInfo(
        topic_id=77, title="Новости", is_general=False, is_closed=False, is_hidden=False
    )
    uow = FakeUnitOfWork(settings=_settings(), topics=[renamed], aliases=[(7, "важное")])
    forwarding = ManualForwarding(lambda: uow)

    resolution = await forwarding.resolve_alias(555, "важное")

    assert resolution.status is AliasResolution.Status.STALE


# --- AliasManager ------------------------------------------------------------------


async def test_list_with_topics_joins_alias_with_topic_title() -> None:
    uow = FakeUnitOfWork(
        settings=_settings(), topics=[GENERAL, NEWS], aliases=[(None, "общий"), (7, "важное")]
    )
    manager = AliasManager(lambda: uow)

    entries = await manager.list_with_topics(555)

    assert [(entry.topic_title, entry.alias) for entry in entries] == [
        ("General", "общий"),
        ("Новости", "важное"),
    ]


async def test_list_with_topics_shows_none_alias_for_unaliased_topic() -> None:
    uow = FakeUnitOfWork(settings=_settings(), topics=[NEWS], aliases=[])
    manager = AliasManager(lambda: uow)

    entries = await manager.list_with_topics(555)

    assert len(entries) == 1
    assert entries[0].alias is None


async def test_upsert_validates_against_user_aliases() -> None:
    uow = FakeUnitOfWork(settings=_settings(), topics=[NEWS], aliases=[(7, "важное")])
    manager = AliasManager(lambda: uow)

    with pytest.raises(InvalidAlias):
        await manager.upsert(555, topic_id=8, alias="ВАЖНОЕ")

    assert uow.vk_aliases.rows == [(7, "важное")]


async def test_upsert_rejects_reserved_alias() -> None:
    uow = FakeUnitOfWork(settings=_settings(), topics=[NEWS], aliases=[])
    manager = AliasManager(lambda: uow)

    with pytest.raises(InvalidAlias):
        await manager.upsert(555, topic_id=7, alias="Помощь")


async def test_upsert_stores_normalized_alias() -> None:
    uow = FakeUnitOfWork(settings=_settings(), topics=[NEWS], aliases=[])
    manager = AliasManager(lambda: uow)

    await manager.upsert(555, topic_id=7, alias="Вaжное")

    assert uow.vk_aliases.rows == [(7, "вaжное")]


async def test_general_alias_conflict_surfaces_as_invalid_alias() -> None:
    uow = FakeUnitOfWork(settings=_settings(), topics=[GENERAL], aliases=[(None, "общий")])
    manager = AliasManager(lambda: uow)

    with pytest.raises(InvalidAlias):
        await manager.upsert(555, topic_id=None, alias="второй")


async def test_delete_removes_alias_row() -> None:
    uow = FakeUnitOfWork(settings=_settings(), topics=[NEWS], aliases=[(7, "важное")])
    manager = AliasManager(lambda: uow)

    await manager.delete(555, topic_id=7)

    assert uow.vk_aliases.rows == []
