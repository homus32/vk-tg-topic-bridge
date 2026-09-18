"""Integration tests for the SQLAlchemy repositories and the UnitOfWork (plan §4/§5)."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vk_topic_bridge.application.dto.settings import BridgeSettingsState, ToggleKind
from vk_topic_bridge.domain.value_objects import TopicInfo
from vk_topic_bridge.infrastructure.db.repositories.bridge_settings import (
    BridgeSettingsRepositoryImpl,
)
from vk_topic_bridge.infrastructure.db.repositories.delivery import DeliveryRepositoryImpl
from vk_topic_bridge.infrastructure.db.repositories.telegram_topics import (
    TelegramTopicsRepositoryImpl,
)
from vk_topic_bridge.infrastructure.db.repositories.unit_of_work import SqlAlchemyUnitOfWork
from vk_topic_bridge.infrastructure.db.repositories.vk_aliases import VkAliasRepositoryImpl

CHAT_ID = -1001234567890
SessionFactory = async_sessionmaker[AsyncSession]


async def _scalar(session_factory: SessionFactory, sql: str, **params: object) -> object:
    async with session_factory() as db_session:
        result = await db_session.execute(text(sql), params)
        return result.scalar_one()


def _topic(
    topic_id: int | None,
    title: str,
    *,
    is_general: bool = False,
    is_closed: bool = False,
    is_hidden: bool = False,
) -> TopicInfo:
    return TopicInfo(
        topic_id=topic_id,
        title=title,
        is_general=is_general,
        is_closed=is_closed,
        is_hidden=is_hidden,
    )


async def test_settings_get_returns_none_when_singleton_is_absent(session: AsyncSession) -> None:
    assert await BridgeSettingsRepositoryImpl(session).get() is None


async def test_settings_upsert_chat_creates_singleton_row(
    session: AsyncSession, session_factory: SessionFactory
) -> None:
    state = await BridgeSettingsRepositoryImpl(session).upsert_chat(CHAT_ID, "Bridge chat")
    await session.commit()

    assert state.telegram_chat_id == CHAT_ID
    assert state.telegram_chat_title == "Bridge chat"
    assert await _scalar(session_factory, "SELECT count(*) FROM bridge_settings") == 1
    assert await _scalar(session_factory, "SELECT id FROM bridge_settings") == 1


async def test_settings_mutators_create_row_and_persist(
    session: AsyncSession, session_factory: SessionFactory
) -> None:
    repo = BridgeSettingsRepositoryImpl(session)

    await repo.set_messages_topic(11)
    await repo.set_wall_topic(22)
    await repo.set_toggle(ToggleKind.ALL, False)
    await repo.set_toggle(ToggleKind.HASHTAGS, False)
    await session.commit()

    async with session_factory() as fresh:
        state = await BridgeSettingsRepositoryImpl(fresh).get()

    assert state is not None
    assert state.telegram_messages_topic_id == 11
    assert state.telegram_wall_topic_id == 22
    assert state.auto_forward_all is False
    assert state.auto_forward_hashtags is False
    assert state.auto_forward_wall is True


async def test_settings_reset_restores_defaults(
    session: AsyncSession, session_factory: SessionFactory
) -> None:
    repo = BridgeSettingsRepositoryImpl(session)
    await repo.upsert_chat(CHAT_ID, "Bridge chat")
    await repo.set_messages_topic(5)
    await repo.set_toggle(ToggleKind.WALL, False)
    await session.commit()

    reset_state = await repo.reset()
    await session.commit()

    assert reset_state == BridgeSettingsState.defaults()
    async with session_factory() as fresh:
        assert await BridgeSettingsRepositoryImpl(fresh).get() == BridgeSettingsState.defaults()


async def test_topics_replace_all_upserts_and_lists(session: AsyncSession) -> None:
    repo = TelegramTopicsRepositoryImpl(session)

    await repo.replace_all(CHAT_ID, [_topic(5, "Five"), _topic(9, "Nine")])
    await session.commit()

    listed = await repo.list(CHAT_ID)
    assert [(topic.topic_id, topic.title) for topic in listed] == [(5, "Five"), (9, "Nine")]


async def test_topics_replace_all_deactivates_unseen_without_deleting(
    session: AsyncSession, session_factory: SessionFactory
) -> None:
    repo = TelegramTopicsRepositoryImpl(session)
    await repo.replace_all(CHAT_ID, [_topic(1, "One"), _topic(2, "Two")])
    await session.commit()

    await repo.replace_all(CHAT_ID, [_topic(2, "Two"), _topic(3, "Three")])
    await session.commit()

    listed = await repo.list(CHAT_ID)
    assert {topic.title for topic in listed} == {"Two", "Three"}
    assert await _scalar(session_factory, "SELECT count(*) FROM telegram_topics") == 3
    assert (
        await _scalar(session_factory, "SELECT count(*) FROM telegram_topics WHERE is_active = 0")
        == 1
    )


async def test_topics_replace_all_repeated_general_refresh_does_not_raise(
    session: AsyncSession, session_factory: SessionFactory
) -> None:
    repo = TelegramTopicsRepositoryImpl(session)
    general = _topic(None, "General", is_general=True)

    await repo.replace_all(CHAT_ID, [general, _topic(5, "Five")])
    await session.commit()
    await repo.replace_all(CHAT_ID, [general, _topic(5, "Five")])
    await session.commit()

    general_count = await _scalar(
        session_factory,
        "SELECT count(*) FROM telegram_topics WHERE is_general = 1 AND telegram_chat_id = :chat",
        chat=CHAT_ID,
    )
    assert general_count == 1


async def test_topics_mark_missing_deactivates_only_unseen(session: AsyncSession) -> None:
    repo = TelegramTopicsRepositoryImpl(session)
    await repo.replace_all(CHAT_ID, [_topic(1, "One"), _topic(2, "Two")])
    await session.commit()

    await repo.mark_missing(CHAT_ID, [2])
    await session.commit()

    listed = await repo.list(CHAT_ID)
    assert [topic.topic_id for topic in listed] == [2]


async def test_alias_upsert_list_and_delete(session: AsyncSession) -> None:
    repo = VkAliasRepositoryImpl(session)
    await repo.upsert(7, 5, "Новости", "новости")
    await repo.upsert(7, None, "Общее", "общее")
    await session.commit()

    assert await repo.list_for_user(7) == [(None, "общее"), (5, "новости")]

    await repo.delete(7, 5)
    await session.commit()

    assert await repo.list_for_user(7) == [(None, "общее")]


async def test_alias_upsert_general_topic_is_idempotent(
    session: AsyncSession, session_factory: SessionFactory
) -> None:
    repo = VkAliasRepositoryImpl(session)
    await repo.upsert(7, None, "Общее", "общее")
    await repo.upsert(7, None, "Общее обновлено", "общее обновлено")
    await session.commit()

    assert await repo.list_for_user(7) == [(None, "общее обновлено")]
    assert (
        await _scalar(
            session_factory,
            "SELECT count(*) FROM vk_topic_aliases WHERE vk_user_id = 7 AND topic_id IS NULL",
        )
        == 1
    )


async def test_alias_unique_normalized_violation_raises(session: AsyncSession) -> None:
    repo = VkAliasRepositoryImpl(session)
    await repo.upsert(7, 5, "Новости", "новости")
    await session.commit()

    with pytest.raises(IntegrityError):
        await repo.upsert(7, 6, "новости", "новости")

    await session.rollback()


async def test_second_general_topic_for_same_chat_raises(session: AsyncSession) -> None:
    await session.execute(
        text(
            "INSERT INTO telegram_topics (telegram_chat_id, topic_id, title, is_general)"
            " VALUES (:chat, NULL, 'General', 1)"
        ),
        {"chat": CHAT_ID},
    )
    await session.commit()

    with pytest.raises(IntegrityError):
        await session.execute(
            text(
                "INSERT INTO telegram_topics (telegram_chat_id, topic_id, title, is_general)"
                " VALUES (:chat, NULL, 'General 2', 1)"
            ),
            {"chat": CHAT_ID},
        )

    await session.rollback()


async def test_unit_of_work_commit_persists(session_factory: SessionFactory) -> None:
    uow = SqlAlchemyUnitOfWork(session_factory)

    async with uow:
        await uow.bridge_settings.upsert_chat(CHAT_ID, "Bridge chat")
        await uow.commit()

    async with session_factory() as fresh:
        state = await BridgeSettingsRepositoryImpl(fresh).get()
    assert state is not None
    assert state.telegram_chat_id == CHAT_ID


async def test_unit_of_work_rollback_discards_changes(session_factory: SessionFactory) -> None:
    uow = SqlAlchemyUnitOfWork(session_factory)

    async with uow:
        await uow.bridge_settings.upsert_chat(CHAT_ID, "Bridge chat")
        await uow.rollback()

    async with session_factory() as fresh:
        assert await BridgeSettingsRepositoryImpl(fresh).get() is None


async def test_unit_of_work_rolls_back_on_exception(session_factory: SessionFactory) -> None:
    uow = SqlAlchemyUnitOfWork(session_factory)

    with pytest.raises(RuntimeError, match="boom"):
        async with uow:
            await uow.bridge_settings.upsert_chat(CHAT_ID, "Bridge chat")
            raise RuntimeError("boom")

    async with session_factory() as fresh:
        assert await BridgeSettingsRepositoryImpl(fresh).get() is None


async def test_unit_of_work_exposes_every_repository(session_factory: SessionFactory) -> None:
    uow = SqlAlchemyUnitOfWork(session_factory)

    async with uow:
        assert isinstance(uow.bridge_settings, BridgeSettingsRepositoryImpl)
        assert isinstance(uow.telegram_topics, TelegramTopicsRepositoryImpl)
        assert isinstance(uow.vk_aliases, VkAliasRepositoryImpl)
        assert isinstance(uow.deliveries, DeliveryRepositoryImpl)


async def test_topics_availability_flags_roundtrip(session: AsyncSession) -> None:
    repo = TelegramTopicsRepositoryImpl(session)

    await repo.replace_all(
        CHAT_ID,
        [_topic(5, "Ticket", is_closed=True), _topic(6, "Hidden", is_hidden=True)],
    )
    await session.commit()

    listed = {topic.topic_id: topic for topic in await repo.list(CHAT_ID)}
    assert listed[5].is_closed is True
    assert listed[5].is_hidden is False
    assert listed[6].is_hidden is True


async def test_topics_availability_flags_update_on_refresh(session: AsyncSession) -> None:
    repo = TelegramTopicsRepositoryImpl(session)
    await repo.replace_all(CHAT_ID, [_topic(5, "Ticket", is_closed=True)])
    await session.commit()

    await repo.replace_all(CHAT_ID, [_topic(5, "Ticket", is_closed=False)])
    await session.commit()

    listed = await repo.list(CHAT_ID)
    assert listed[0].is_closed is False


async def test_general_alias_index_blocks_second_general_alias_for_user(
    session: AsyncSession,
) -> None:
    repo = VkAliasRepositoryImpl(session)
    await repo.upsert(7, None, "Общее", "общее")
    await session.commit()

    with pytest.raises(IntegrityError):
        await session.execute(
            text(
                "INSERT INTO vk_topic_aliases (vk_user_id, topic_id, alias, alias_normalized)"
                " VALUES (7, NULL, 'Ещё', 'ещё')"
            )
        )

    await session.rollback()


async def test_general_alias_index_allows_other_users(session: AsyncSession) -> None:
    repo = VkAliasRepositoryImpl(session)
    await repo.upsert(7, None, "Общее", "общее")
    await repo.upsert(8, None, "Общее", "общее")
    await session.commit()

    assert await repo.list_for_user(8) == [(None, "общее")]


async def test_settings_configured_flags_default_false(session: AsyncSession) -> None:
    repo = BridgeSettingsRepositoryImpl(session)
    await repo.upsert_chat(CHAT_ID, "Bridge chat")
    await session.commit()

    state = await repo.get()
    assert state is not None
    assert state.telegram_messages_topic_configured is False
    assert state.telegram_wall_topic_configured is False
    assert state.messages_destination_kind().value == "unset"


async def test_settings_set_named_topic_marks_configured(session: AsyncSession) -> None:
    repo = BridgeSettingsRepositoryImpl(session)
    await repo.set_messages_topic(11)
    await repo.set_wall_topic(None)
    await session.commit()

    state = await repo.get()
    assert state is not None
    assert state.messages_destination_kind().value == "named_topic"
    assert state.wall_destination_kind().value == "general"


async def test_settings_reset_clears_configured_flags(session: AsyncSession) -> None:
    repo = BridgeSettingsRepositoryImpl(session)
    await repo.set_messages_topic(5)
    await repo.set_wall_topic(None)
    await session.commit()

    await repo.reset()
    await session.commit()

    state = await repo.get()
    assert state is not None
    assert state.messages_destination_kind().value == "unset"
    assert state.wall_destination_kind().value == "unset"
