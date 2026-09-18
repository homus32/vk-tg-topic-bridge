"""End-to-end forwarding chain over real components, faking only the network edges.

One Long Poll ``message_new`` update travels through the real ``VkEventConsumer``, the real
``VkApiGateway``, the real ``ForwardVkMessage`` and the real SQLAlchemy unit of work into a
temporary SQLite file migrated by Alembic. Only the VK raw API, the Bot polling transport and
the Telegram publisher are fakes, so the acceptance chain — publish once, persist the ledger
row, set the VK reaction, deduplicate a replay and reject a filtered message — is proven
without network access or real credentials.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from config import Settings
from tests.acceptance._fakes import RecordingPublisher, make_source
from vk_topic_bridge.application.forwarding.forward_message import ForwardVkMessage
from vk_topic_bridge.bootstrap.vk_consumer import VkEventConsumer
from vk_topic_bridge.domain.enums import PublicationStatus, SourceType
from vk_topic_bridge.domain.publication import (
    OperationOutcome,
    PublicationPlan,
)
from vk_topic_bridge.domain.value_objects import TopicInfo
from vk_topic_bridge.infrastructure.db.engine import create_async_engine, create_session_factory
from vk_topic_bridge.infrastructure.db.models import DeliveryRecord as DeliveryRecordRow
from vk_topic_bridge.infrastructure.db.repositories.delivery import DeliveryRepositoryImpl
from vk_topic_bridge.infrastructure.db.repositories.unit_of_work import SqlAlchemyUnitOfWork
from vk_topic_bridge.infrastructure.vk.api import LIKE_REACTION_ID, VkApiGateway

REPO_ROOT = Path(__file__).resolve().parents[2]
SessionFactory = async_sessionmaker[AsyncSession]

GROUP_ID = 111
PEER_ID = 2_000_000_222
FROM_ID = 555
CONVERSATION_MESSAGE_ID = 333
SECOND_CONVERSATION_MESSAGE_ID = 334
CHAT_ID = -1001234567890
MESSAGES_TOPIC_ID = 7
PUBLISHED_MESSAGE_IDS = (101,)

PRIMARY_TEXT = "@all #вертикальныйсрез Сообщение для полной цепочки"
FILTERED_TEXT = "обычное сообщение без служебных тегов"
SOURCE_KEY = f"{GROUP_ID}:{PEER_ID}:{CONVERSATION_MESSAGE_ID}"


def _update(
    *,
    conversation_message_id: int = CONVERSATION_MESSAGE_ID,
    text: str = PRIMARY_TEXT,
) -> dict[str, object]:
    """One Long Poll ``message_new`` update with the service fields the consumer requires."""
    return {
        "type": "message_new",
        "group_id": GROUP_ID,
        "event_id": f"evt-{conversation_message_id}",
        "object": {
            "message": {
                "peer_id": PEER_ID,
                "from_id": FROM_ID,
                "conversation_message_id": conversation_message_id,
                "text": text,
                "is_cropped": False,
            },
            "client_info": {},
        },
    }


class FakeRawVkApi:
    """``RawVkApi`` replaying canned VK responses and recording every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def request(
        self, method: str, data: dict[str, object], version: str | None = None
    ) -> dict[str, object]:
        self.calls.append((method, dict(data)))
        if method == "users.get":
            return {
                "response": [{"first_name": "Иван", "last_name": "Петров", "screen_name": "ivanov"}]
            }
        if method == "groups.getById":
            return {"response": {"groups": [{"id": GROUP_ID}]}}
        if method == "messages.sendReaction":
            return {"response": 1}
        msg = f"unexpected VK method {method}"
        raise AssertionError(msg)

    def params_for(self, method: str) -> list[dict[str, object]]:
        return [data for called, data in self.calls if called == method]


class FakeBotPolling:
    """``BotPollingLike`` yielding each pushed Long Poll response exactly once."""

    def __init__(self) -> None:
        self._responses: list[dict[str, object]] = []
        self.stop_calls = 0

    def push(self, *updates: dict[str, object]) -> None:
        self._responses.append({"ts": len(self._responses) + 1, "updates": list(updates)})

    async def listen(self) -> AsyncIterator[dict[str, object]]:
        while self._responses:
            yield self._responses.pop(0)

    def stop(self) -> None:
        self.stop_calls += 1


@dataclass(slots=True)
class ChainHarness:
    """Real chain wired to a migrated SQLite file plus the fakes that observe it."""

    session_factory: SessionFactory
    raw_api: FakeRawVkApi
    publisher: RecordingPublisher
    polling: FakeBotPolling
    consumer: VkEventConsumer

    async def deliver(self, *updates: dict[str, object]) -> None:
        """Push one Long Poll response and drain the consumer until the stream ends."""
        self.polling.push(*updates)
        await self.consumer.run()


@pytest.fixture
def database_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Temp SQLite file migrated to head, mirroring the DB integration suite approach."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'forwarding-chain.db'}"
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


class _DbObservingPublisher(RecordingPublisher):
    """Publisher asserting from a fresh session that send intent is committed before I/O."""

    def __init__(self, *, session_factory: SessionFactory, source_key: str) -> None:
        super().__init__(message_ids=PUBLISHED_MESSAGE_IDS)
        self._session_factory = session_factory
        self._source_key = source_key
        self.observed_status: str | None = None

    async def publish_plan(self, plan: PublicationPlan) -> tuple[OperationOutcome, ...]:
        async with self._session_factory() as session:
            record = await DeliveryRepositoryImpl(session).get(
                SourceType.VK_MESSAGE, self._source_key
            )
        assert record is not None, "send intent must be durable before network I/O"
        self.observed_status = record.publication_status.value
        return await super().publish_plan(plan)


@pytest.fixture
async def harness(session_factory: SessionFactory) -> ChainHarness:
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.bridge_settings.upsert_chat(CHAT_ID, "Целевой чат")
        await uow.bridge_settings.set_messages_topic(MESSAGES_TOPIC_ID)
        await uow.telegram_topics.replace_all(
            CHAT_ID,
            [
                TopicInfo(
                    topic_id=MESSAGES_TOPIC_ID,
                    title="Новости",
                    is_general=False,
                    is_closed=False,
                    is_hidden=False,
                )
            ],
        )
        await uow.commit()

    raw_api = FakeRawVkApi()
    publisher = RecordingPublisher(message_ids=PUBLISHED_MESSAGE_IDS)
    gateway = VkApiGateway(raw_api, Settings.model_validate({}))
    forward = ForwardVkMessage(
        uow_factory=lambda: SqlAlchemyUnitOfWork(session_factory),
        plan_publisher=publisher,
        vk=gateway,
    )
    polling = FakeBotPolling()
    consumer = VkEventConsumer(
        polling=polling,
        gateway=gateway,
        forward=forward,
        allowed_group_id=GROUP_ID,
    )
    return ChainHarness(
        session_factory=session_factory,
        raw_api=raw_api,
        publisher=publisher,
        polling=polling,
        consumer=consumer,
    )


async def _delivery_rows(session_factory: SessionFactory) -> list[DeliveryRecordRow]:
    async with session_factory() as session:
        result = await session.execute(select(DeliveryRecordRow).order_by(DeliveryRecordRow.id))
        return list(result.scalars())


async def test_chain_publishes_once_to_the_seeded_destination(harness: ChainHarness) -> None:
    await harness.deliver(_update())

    assert len(harness.publisher.publications) == 1
    publication = harness.publisher.publications[0]
    assert publication.chat_id == CHAT_ID
    assert publication.message_thread_id == MESSAGES_TOPIC_ID
    assert "#извк" in publication.html_text
    assert "#извкважно" in publication.html_text
    assert f"https://vk.com/id{FROM_ID}" in publication.html_text


async def test_chain_records_one_published_delivery_row(harness: ChainHarness) -> None:
    await harness.deliver(_update())

    rows = await _delivery_rows(harness.session_factory)
    assert len(rows) == 1
    row = rows[0]
    assert row.source_key == SOURCE_KEY
    assert row.publication_status == "published"
    assert row.reaction_status == "succeeded"
    assert row.destination_chat_id == CHAT_ID
    assert row.destination_topic_id == MESSAGES_TOPIC_ID
    assert row.telegram_message_ids is not None
    assert json.loads(row.telegram_message_ids) == list(PUBLISHED_MESSAGE_IDS)


async def test_chain_sets_the_vk_reaction_once(harness: ChainHarness) -> None:
    await harness.deliver(_update())

    assert harness.raw_api.params_for("messages.sendReaction") == [
        {"peer_id": PEER_ID, "cmid": CONVERSATION_MESSAGE_ID, "reaction_id": LIKE_REACTION_ID}
    ]


@pytest.mark.parametrize("text", ["#хештег сообщение", "@all важное сообщение"])
async def test_nested_trigger_publishes_and_reacts(harness: ChainHarness, text: str) -> None:
    await harness.deliver(_update(text=text))

    assert len(harness.publisher.publications) == 1
    assert harness.raw_api.params_for("messages.sendReaction") == [
        {"peer_id": PEER_ID, "cmid": CONVERSATION_MESSAGE_ID, "reaction_id": LIKE_REACTION_ID}
    ]


async def test_replaying_the_same_event_does_not_publish_again(harness: ChainHarness) -> None:
    await harness.deliver(_update())
    await harness.deliver(_update())

    assert len(harness.publisher.publications) == 1
    rows = await _delivery_rows(harness.session_factory)
    assert len(rows) == 1
    assert [row.publication_status for row in rows] == ["published"]
    assert len(harness.raw_api.params_for("messages.sendReaction")) == 1


async def test_filtered_event_publishes_nothing(harness: ChainHarness) -> None:
    await harness.deliver(_update())
    await harness.deliver(
        _update(conversation_message_id=SECOND_CONVERSATION_MESSAGE_ID, text=FILTERED_TEXT)
    )

    assert len(harness.publisher.publications) == 1
    rows = await _delivery_rows(harness.session_factory)
    assert [row.source_key for row in rows] == [SOURCE_KEY]


async def test_send_intent_is_committed_before_network_io(
    session_factory: SessionFactory,
) -> None:
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.bridge_settings.upsert_chat(CHAT_ID, "Целевой чат")
        await uow.bridge_settings.set_messages_topic(MESSAGES_TOPIC_ID)
        await uow.telegram_topics.replace_all(
            CHAT_ID,
            [
                TopicInfo(
                    topic_id=MESSAGES_TOPIC_ID,
                    title="Новости",
                    is_general=False,
                    is_closed=False,
                    is_hidden=False,
                )
            ],
        )
        await uow.commit()

    publisher = _DbObservingPublisher(session_factory=session_factory, source_key=SOURCE_KEY)
    gateway = VkApiGateway(FakeRawVkApi(), Settings.model_validate({}))
    use_case = ForwardVkMessage(
        uow_factory=lambda: SqlAlchemyUnitOfWork(session_factory),
        plan_publisher=publisher,
        vk=gateway,
    )

    outcome = await use_case.execute(make_source(PRIMARY_TEXT))

    assert outcome.published is True
    assert outcome.reason == "published"
    assert publisher.observed_status == PublicationStatus.SEND_STARTED.value
    rows = await _delivery_rows(session_factory)
    assert [row.publication_status for row in rows] == ["published"]
