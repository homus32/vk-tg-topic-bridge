"""Delivery review data tests: terminal listing, reviewed CAS, fail-closed semantics.

Runs against a real migrated temp SQLite database (finish task 19); no network.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vk_topic_bridge.application.dto.delivery import ReserveRequest
from vk_topic_bridge.domain.enums import PublicationStatus, SourceType
from vk_topic_bridge.infrastructure.db.repositories.delivery import DeliveryRepositoryImpl

SessionFactory = async_sessionmaker[AsyncSession]

_TOKEN = "review-token"


async def _reserve(session: AsyncSession, key: str) -> int:
    repo = DeliveryRepositoryImpl(session)
    outcome = await repo.reserve(
        ReserveRequest(
            source_type=SourceType.VK_MESSAGE,
            source_key=key,
            destination_chat_id=-100,
            destination_topic_id=7,
            payload_hash="hash",
        )
    )
    await session.commit()
    return outcome.record.id


async def _make_ambiguous(session: AsyncSession, delivery_id: int) -> None:
    repo = DeliveryRepositoryImpl(session)
    await repo.claim_reserved(delivery_id, _TOKEN, 60)
    await repo.mark_send_started(delivery_id, _TOKEN)
    await repo.mark_publication_ambiguous(delivery_id, _TOKEN, "timeout", "no response")
    await session.commit()


async def _make_failed_permanent(session: AsyncSession, delivery_id: int) -> None:
    repo = DeliveryRepositoryImpl(session)
    await repo.claim_reserved(delivery_id, _TOKEN, 60)
    await repo.mark_send_started(delivery_id, _TOKEN)
    await repo.mark_failed_permanent(delivery_id, _TOKEN, "thread_not_found", "no thread")
    await session.commit()


async def test_list_failed_terminal_returns_only_terminal_rows(
    session: AsyncSession,
) -> None:
    ambiguous = await _reserve(session, "1:1:1")
    failed = await _reserve(session, "1:1:2")
    reserved = await _reserve(session, "1:1:3")
    await _make_ambiguous(session, ambiguous)
    await _make_failed_permanent(session, failed)

    rows = await DeliveryRepositoryImpl(session).list_failed_terminal()

    ids = {row.id for row in rows}
    assert ids == {ambiguous, failed}
    assert reserved not in ids
    statuses = {row.publication_status for row in rows}
    assert statuses == {
        PublicationStatus.AMBIGUOUS,
        PublicationStatus.FAILED_PERMANENT,
    }


async def test_list_failed_terminal_orders_newest_first(session: AsyncSession) -> None:
    first = await _reserve(session, "1:1:1")
    second = await _reserve(session, "1:1:2")
    await _make_ambiguous(session, first)
    await _make_ambiguous(session, second)

    rows = await DeliveryRepositoryImpl(session).list_failed_terminal(limit=20)

    assert next(row.id for row in rows) == second


async def test_list_failed_terminal_respects_limit(session: AsyncSession) -> None:
    ids = [await _reserve(session, f"1:1:{n}") for n in range(3)]
    for delivery_id in ids:
        await _make_ambiguous(session, delivery_id)

    rows = await DeliveryRepositoryImpl(session).list_failed_terminal(limit=2)

    assert len(rows) == 2


async def test_mark_reviewed_clears_flag_for_ambiguous_row(session: AsyncSession) -> None:
    delivery_id = await _reserve(session, "1:1:1")
    await _make_ambiguous(session, delivery_id)
    repo = DeliveryRepositoryImpl(session)

    marked = await repo.mark_reviewed(delivery_id)
    await session.commit()

    assert marked is True
    rows = await repo.list_failed_terminal()
    record = next(row for row in rows if row.id == delivery_id)
    assert record.review_required is False
    assert record.publication_status is PublicationStatus.AMBIGUOUS


async def test_mark_reviewed_returns_false_when_already_reviewed(session: AsyncSession) -> None:
    delivery_id = await _reserve(session, "1:1:1")
    await _make_ambiguous(session, delivery_id)
    repo = DeliveryRepositoryImpl(session)
    await repo.mark_reviewed(delivery_id)
    await session.commit()

    second = await repo.mark_reviewed(delivery_id)

    assert second is False


async def test_mark_reviewed_does_not_touch_failed_permanent(session: AsyncSession) -> None:
    delivery_id = await _reserve(session, "1:1:1")
    await _make_failed_permanent(session, delivery_id)

    marked = await DeliveryRepositoryImpl(session).mark_reviewed(delivery_id)

    assert marked is False


async def test_mark_reviewed_does_not_touch_published(session: AsyncSession) -> None:
    delivery_id = await _reserve(session, "1:1:1")
    repo = DeliveryRepositoryImpl(session)
    await repo.claim_reserved(delivery_id, _TOKEN, 60)
    await repo.mark_send_started(delivery_id, _TOKEN)
    await repo.mark_published(delivery_id, _TOKEN, (101,))
    await session.commit()

    marked = await repo.mark_reviewed(delivery_id)

    assert marked is False


async def test_ambiguous_row_requires_review_by_default(session: AsyncSession) -> None:
    delivery_id = await _reserve(session, "1:1:1")
    await _make_ambiguous(session, delivery_id)

    rows = await DeliveryRepositoryImpl(session).list_failed_terminal()

    record = next(row for row in rows if row.id == delivery_id)
    assert record.review_required is True
    assert isinstance(record.ambiguous_at, datetime)
