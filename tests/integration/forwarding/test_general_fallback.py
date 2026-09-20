"""General fallback over real SQLite: a configured-but-missing topic publishes to General.

Uses the real ``ForwardVkMessage`` and the real SQLAlchemy unit of work on a temp migrated
SQLite file; only the publisher, the notifier port and the VK gateway are fakes.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.acceptance._fakes import RecordingPublisher, make_source
from vk_topic_bridge.application.dto.infrastructure import LongPollInfo
from vk_topic_bridge.application.forwarding.forward_message import ForwardVkMessage
from vk_topic_bridge.application.notifications.owner_notifier import OwnerNotifier
from vk_topic_bridge.domain.enums import PublicationStatus
from vk_topic_bridge.domain.value_objects import Author, SourceMessage, SourceWallPost, TopicInfo
from vk_topic_bridge.infrastructure.db.engine import create_async_engine, create_session_factory
from vk_topic_bridge.infrastructure.db.models import DeliveryRecord as DeliveryRecordRow
from vk_topic_bridge.infrastructure.db.repositories.unit_of_work import SqlAlchemyUnitOfWork

REPO_ROOT = Path(__file__).resolve().parents[3]
SessionFactory = async_sessionmaker[AsyncSession]

GROUP_ID = 111
CHAT_ID = -1001234567890
MISSING_TOPIC_ID = 99
PRESENT_TOPIC_ID = 7
OWNER_ID = 111
PEER_ID = 2_000_000_222
CONVERSATION_MESSAGE_ID = 333
SOURCE_KEY = f"{GROUP_ID}:{PEER_ID}:{CONVERSATION_MESSAGE_ID}"
PUBLISHED_MESSAGE_IDS = (101,)


class FakeVk:
    def __init__(self) -> None:
        self.reactions: list[tuple[int, int]] = []

    async def set_reaction(self, peer_id: int, conversation_message_id: int) -> None:
        self.reactions.append((peer_id, conversation_message_id))

    async def get_community_id(self) -> int:
        return GROUP_ID

    async def check_long_poll(self) -> LongPollInfo:
        raise NotImplementedError

    async def get_full_message(self, peer_id: int, conversation_message_id: int) -> SourceMessage:
        raise NotImplementedError

    async def get_author(self, user_id: int) -> Author:
        raise NotImplementedError

    async def normalize_event(self, raw_event: object, author: Author) -> SourceMessage:
        raise NotImplementedError

    async def normalize_wall_event(self, raw_event: object, author: Author) -> SourceWallPost:
        raise NotImplementedError


class OwnerSelectivePublisher(RecordingPublisher):
    def __init__(self, *, failing_owner_ids: frozenset[int]) -> None:
        super().__init__(message_ids=PUBLISHED_MESSAGE_IDS)
        self._failing_owner_ids = failing_owner_ids

    async def send_text(self, chat_id: int, text: str, message_thread_id: int | None = None) -> int:
        if chat_id in self._failing_owner_ids:
            raise RuntimeError(f"owner notification failed for {chat_id}")
        return await super().send_text(chat_id, text, message_thread_id)


@pytest.fixture
def database_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    url = f"sqlite+aiosqlite:///{tmp_path / 'general-fallback.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    command.upgrade(config, "head")
    return url


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    db_engine = create_async_engine(database_url)
    try:
        yield db_engine
    finally:
        await db_engine.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> SessionFactory:
    return create_session_factory(engine)


async def _seed(
    session_factory: SessionFactory, topic_id: int, *, snapshot_topic_id: int | None
) -> None:
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.bridge_settings.upsert_chat(CHAT_ID, "Целевой чат")
        await uow.bridge_settings.set_messages_topic(topic_id)
        topics = []
        if snapshot_topic_id is not None:
            topics.append(
                TopicInfo(
                    topic_id=snapshot_topic_id,
                    title="Новости",
                    is_general=False,
                    is_closed=False,
                    is_hidden=False,
                )
            )
        await uow.telegram_topics.replace_all(CHAT_ID, topics)
        await uow.commit()


def _harness(
    session_factory: SessionFactory,
) -> tuple[ForwardVkMessage, RecordingPublisher, FakeVk]:
    publisher = RecordingPublisher(message_ids=PUBLISHED_MESSAGE_IDS)
    notifier = OwnerNotifier(frozenset({OWNER_ID}), publisher)
    vk = FakeVk()
    use_case = ForwardVkMessage(
        uow_factory=lambda: SqlAlchemyUnitOfWork(session_factory),
        plan_publisher=publisher,
        vk=vk,
        notifier=notifier,
    )
    return use_case, publisher, vk


async def _rows(session_factory: SessionFactory) -> list[DeliveryRecordRow]:
    async with session_factory() as session:
        result = await session.execute(select(DeliveryRecordRow).order_by(DeliveryRecordRow.id))
        return list(result.scalars())


async def test_missing_configured_topic_falls_back_to_general(
    session_factory: SessionFactory,
) -> None:
    await _seed(session_factory, MISSING_TOPIC_ID, snapshot_topic_id=PRESENT_TOPIC_ID)
    use_case, publisher, vk = _harness(session_factory)

    outcome = await use_case.execute(make_source("@all Привет"))

    assert outcome.published is True
    assert publisher.publications[0].message_thread_id is None
    assert len(publisher.sent_text) == 1
    owner_id, text, _ = publisher.sent_text[0]
    assert owner_id == OWNER_ID
    assert "General" in text
    assert str(MISSING_TOPIC_ID) in text
    row = (await _rows(session_factory))[0]
    assert row.publication_status == PublicationStatus.PUBLISHED.value
    assert row.destination_topic_id is None
    assert row.telegram_message_ids is not None
    assert json.loads(row.telegram_message_ids) == list(PUBLISHED_MESSAGE_IDS)
    assert vk.reactions == [(PEER_ID, CONVERSATION_MESSAGE_ID)]


async def test_available_configured_topic_publishes_directly(
    session_factory: SessionFactory,
) -> None:
    await _seed(session_factory, PRESENT_TOPIC_ID, snapshot_topic_id=PRESENT_TOPIC_ID)
    use_case, publisher, _ = _harness(session_factory)

    outcome = await use_case.execute(make_source("@all Привет"))

    assert outcome.published is True
    assert publisher.publications[0].message_thread_id == PRESENT_TOPIC_ID
    assert publisher.sent_text == []
    row = (await _rows(session_factory))[0]
    assert row.destination_topic_id == PRESENT_TOPIC_ID


async def test_fallback_notifies_all_owners_without_blocking_reaction(
    session_factory: SessionFactory,
) -> None:
    await _seed(session_factory, MISSING_TOPIC_ID, snapshot_topic_id=PRESENT_TOPIC_ID)
    publisher = OwnerSelectivePublisher(failing_owner_ids=frozenset({222}))
    notifier = OwnerNotifier(frozenset({111, 222, 333}), publisher)
    vk = FakeVk()
    use_case = ForwardVkMessage(
        uow_factory=lambda: SqlAlchemyUnitOfWork(session_factory),
        plan_publisher=publisher,
        vk=vk,
        notifier=notifier,
    )

    outcome = await use_case.execute(make_source("@all Привет"))

    assert outcome.published is True
    assert [owner_id for owner_id, _, _ in publisher.sent_text] == [111, 333]
    assert vk.reactions == [(PEER_ID, CONVERSATION_MESSAGE_ID)]
