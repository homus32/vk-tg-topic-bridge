"""Integration tests for the atomic CAS delivery ledger and its fail-closed state machine."""

import asyncio
import json
from collections.abc import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vk_topic_bridge.application.dto.delivery import (
    DeliveryRecord,
    ReserveOutcome,
    ReserveRequest,
)
from vk_topic_bridge.domain.enums import PublicationStatus, ReactionStatus, SourceType
from vk_topic_bridge.infrastructure.db.repositories.delivery import DeliveryRepositoryImpl

CHAT_ID = -1001234567890
TOPIC_ID = 42
KEY = "42:100:7"
SessionFactory = async_sessionmaker[AsyncSession]


def _request(key: str = KEY) -> ReserveRequest:
    return ReserveRequest(
        source_type=SourceType.VK_MESSAGE,
        source_key=key,
        destination_chat_id=CHAT_ID,
        destination_topic_id=TOPIC_ID,
        payload_hash="payload-hash",
    )


async def _reserve(session_factory: SessionFactory, key: str = KEY) -> ReserveOutcome:
    async with session_factory() as session:
        outcome = await DeliveryRepositoryImpl(session).reserve(_request(key))
        await session.commit()
        return outcome


async def _claim(
    session_factory: SessionFactory, delivery_id: int, token: str, lease_seconds: int = 60
) -> bool:
    async with session_factory() as session:
        claimed = await DeliveryRepositoryImpl(session).claim_reserved(
            delivery_id, token, lease_seconds
        )
        await session.commit()
        return claimed


async def _reserve_and_claim(
    session_factory: SessionFactory, token: str = "claim-1"
) -> ReserveOutcome:
    outcome = await _reserve(session_factory)
    assert outcome.created is True
    assert await _claim(session_factory, outcome.record.id, token) is True
    return outcome


async def _run(
    session_factory: SessionFactory,
    action: Callable[[DeliveryRepositoryImpl], Awaitable[bool]],
) -> bool:
    """Execute one repository mutation in its own session and commit it."""
    async with session_factory() as session:
        result = await action(DeliveryRepositoryImpl(session))
        await session.commit()
        return result


async def _get(session_factory: SessionFactory, key: str = KEY) -> DeliveryRecord | None:
    async with session_factory() as session:
        return await DeliveryRepositoryImpl(session).get(SourceType.VK_MESSAGE, key)


async def _raw(session_factory: SessionFactory, delivery_id: int) -> dict[str, object]:
    async with session_factory() as session:
        result = await session.execute(
            text(
                "SELECT publication_status, reaction_status, claim_token, lease_expires_at, "
                "send_started_at, attempts, telegram_message_ids, last_error_code, last_error, "
                "ambiguous_at, review_required, completed_at "
                "FROM delivery_records WHERE id = :id"
            ),
            {"id": delivery_id},
        )
        return dict(result.mappings().one())


async def _expire_lease(session_factory: SessionFactory, delivery_id: int) -> None:
    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE delivery_records "
                "SET lease_expires_at = datetime('now', '-10 seconds') WHERE id = :id"
            ),
            {"id": delivery_id},
        )
        await session.commit()


async def test_reserve_same_key_creates_one_row_then_returns_existing(
    session_factory: SessionFactory,
) -> None:
    first = await _reserve(session_factory)
    second = await _reserve(session_factory)

    assert first.created is True
    assert second.created is False
    assert second.record.id == first.record.id

    stored = await _get(session_factory)
    assert stored is not None
    assert stored.destination_chat_id == CHAT_ID
    assert stored.destination_topic_id == TOPIC_ID
    assert stored.payload_hash == "payload-hash"

    async with session_factory() as session:
        total = (await session.execute(text("SELECT count(*) FROM delivery_records"))).scalar_one()
    assert total == 1


async def test_concurrent_claim_has_exactly_one_winner(session_factory: SessionFactory) -> None:
    outcome = await _reserve(session_factory)
    delivery_id = outcome.record.id

    results = await asyncio.gather(
        _claim(session_factory, delivery_id, "token-a"),
        _claim(session_factory, delivery_id, "token-b"),
    )

    assert results.count(True) == 1, f"expected exactly one winner, got {results!r}"
    raw = await _raw(session_factory, delivery_id)
    assert raw["attempts"] == 1
    assert raw["claim_token"] in {"token-a", "token-b"}


async def test_mark_send_started_requires_the_matching_claim_token(
    session_factory: SessionFactory,
) -> None:
    outcome = await _reserve_and_claim(session_factory, token="claim-1")

    async with session_factory() as session:
        repo = DeliveryRepositoryImpl(session)
        assert await repo.mark_send_started(outcome.record.id, "foreign-token") is False
        await session.commit()

    raw = await _raw(session_factory, outcome.record.id)
    assert raw["publication_status"] == PublicationStatus.RESERVED.value
    assert raw["send_started_at"] is None


async def test_happy_path_reserved_send_started_published(
    session_factory: SessionFactory,
) -> None:
    outcome = await _reserve_and_claim(session_factory, token="claim-1")
    delivery_id = outcome.record.id

    async with session_factory() as session:
        repo = DeliveryRepositoryImpl(session)
        assert await repo.mark_send_started(delivery_id, "claim-1") is True
        await session.commit()

    after_send = await _raw(session_factory, delivery_id)
    assert after_send["publication_status"] == PublicationStatus.SEND_STARTED.value
    assert after_send["send_started_at"] is not None

    async with session_factory() as session:
        repo = DeliveryRepositoryImpl(session)
        assert await repo.mark_published(delivery_id, "claim-1", [101, 102]) is True
        await session.commit()

    raw = await _raw(session_factory, delivery_id)
    assert raw["publication_status"] == PublicationStatus.PUBLISHED.value
    assert raw["reaction_status"] == ReactionStatus.NOT_DUE.value
    assert json.loads(str(raw["telegram_message_ids"])) == [101, 102]
    assert raw["completed_at"] is not None

    record = await _get(session_factory)
    assert record is not None
    assert record.publication_status is PublicationStatus.PUBLISHED
    assert record.reaction_status is ReactionStatus.NOT_DUE
    assert record.telegram_message_ids == (101, 102)


async def test_mark_published_with_foreign_claim_token_is_rejected(
    session_factory: SessionFactory,
) -> None:
    outcome = await _reserve_and_claim(session_factory, token="claim-1")
    delivery_id = outcome.record.id

    async with session_factory() as session:
        repo = DeliveryRepositoryImpl(session)
        assert await repo.mark_send_started(delivery_id, "claim-1") is True
        await session.commit()

    async with session_factory() as session:
        repo = DeliveryRepositoryImpl(session)
        assert await repo.mark_published(delivery_id, "stale-token", [7]) is False
        await session.commit()

    raw = await _raw(session_factory, delivery_id)
    assert raw["publication_status"] == PublicationStatus.SEND_STARTED.value
    assert raw["telegram_message_ids"] is None
    assert raw["completed_at"] is None


async def test_send_started_then_ambiguous_sets_review_required(
    session_factory: SessionFactory,
) -> None:
    outcome = await _reserve_and_claim(session_factory, token="claim-1")
    delivery_id = outcome.record.id

    async with session_factory() as session:
        repo = DeliveryRepositoryImpl(session)
        assert await repo.mark_send_started(delivery_id, "claim-1") is True
        await session.commit()

    async with session_factory() as session:
        repo = DeliveryRepositoryImpl(session)
        assert (
            await repo.mark_publication_ambiguous(delivery_id, "claim-1", "timeout", "no reply")
            is True
        )
        await session.commit()

    raw = await _raw(session_factory, delivery_id)
    assert raw["publication_status"] == PublicationStatus.AMBIGUOUS.value
    assert raw["review_required"] == 1
    assert raw["ambiguous_at"] is not None

    async with session_factory() as session:
        ambiguous = await DeliveryRepositoryImpl(session).list_ambiguous()
    assert [record.id for record in ambiguous] == [delivery_id]


async def test_mark_published_from_ambiguous_is_rejected(
    session_factory: SessionFactory,
) -> None:
    outcome = await _reserve_and_claim(session_factory, token="claim-1")
    delivery_id = outcome.record.id

    async with session_factory() as session:
        repo = DeliveryRepositoryImpl(session)
        assert await repo.mark_send_started(delivery_id, "claim-1") is True
        await session.commit()
    async with session_factory() as session:
        repo = DeliveryRepositoryImpl(session)
        assert (
            await repo.mark_publication_ambiguous(delivery_id, "claim-1", "timeout", None) is True
        )
        await session.commit()
    async with session_factory() as session:
        repo = DeliveryRepositoryImpl(session)
        assert await repo.mark_published(delivery_id, "claim-1", [1]) is False
        await session.commit()

    raw = await _raw(session_factory, delivery_id)
    assert raw["publication_status"] == PublicationStatus.AMBIGUOUS.value
    assert raw["telegram_message_ids"] is None


async def test_failed_before_send_is_reclaimable(session_factory: SessionFactory) -> None:
    outcome = await _reserve_and_claim(session_factory, token="claim-1")
    delivery_id = outcome.record.id

    async with session_factory() as session:
        repo = DeliveryRepositoryImpl(session)
        assert await repo.mark_failed_before_send(delivery_id, "claim-1", "rejected", "bad chat")
        await session.commit()

    failed = await _raw(session_factory, delivery_id)
    assert failed["publication_status"] == PublicationStatus.FAILED_BEFORE_SEND.value
    assert failed["last_error_code"] == "rejected"
    assert failed["last_error"] == "bad chat"
    # No network intent was recorded, so the claim is released for a safe retry.
    assert failed["claim_token"] is None
    assert failed["lease_expires_at"] is None

    assert await _claim(session_factory, delivery_id, "claim-2") is True
    reclaimed = await _raw(session_factory, delivery_id)
    assert reclaimed["publication_status"] == PublicationStatus.RESERVED.value
    assert reclaimed["claim_token"] == "claim-2"


async def test_stale_lease_is_reclaimable_and_fresh_lease_is_not(
    session_factory: SessionFactory,
) -> None:
    outcome = await _reserve_and_claim(session_factory, token="claim-1")
    delivery_id = outcome.record.id

    assert await _claim(session_factory, delivery_id, "claim-2") is False

    await _expire_lease(session_factory, delivery_id)
    assert await _claim(session_factory, delivery_id, "claim-3") is True

    raw = await _raw(session_factory, delivery_id)
    assert raw["claim_token"] == "claim-3"
    assert raw["attempts"] == 2


async def test_reaction_claim_requires_published(session_factory: SessionFactory) -> None:
    outcome = await _reserve_and_claim(session_factory, token="claim-1")
    delivery_id = outcome.record.id

    async with session_factory() as session:
        assert await DeliveryRepositoryImpl(session).claim_reaction(delivery_id) is False
        await session.commit()

    async with session_factory() as session:
        repo = DeliveryRepositoryImpl(session)
        assert await repo.mark_send_started(delivery_id, "claim-1") is True
        await session.commit()

    async with session_factory() as session:
        assert await DeliveryRepositoryImpl(session).claim_reaction(delivery_id) is False
        await session.commit()

    async with session_factory() as session:
        repo = DeliveryRepositoryImpl(session)
        assert await repo.mark_published(delivery_id, "claim-1", [5]) is True
        await session.commit()

    async with session_factory() as session:
        assert await DeliveryRepositoryImpl(session).claim_reaction(delivery_id) is True
        await session.commit()

    raw = await _raw(session_factory, delivery_id)
    assert raw["reaction_status"] == ReactionStatus.PENDING.value

    async with session_factory() as session:
        pending = await DeliveryRepositoryImpl(session).list_pending_reactions()
    assert [record.id for record in pending] == [delivery_id]


async def test_reaction_failure_keeps_publication_published(
    session_factory: SessionFactory,
) -> None:
    outcome = await _reserve_and_claim(session_factory, token="claim-1")
    delivery_id = outcome.record.id

    async with session_factory() as session:
        repo = DeliveryRepositoryImpl(session)
        assert await repo.mark_send_started(delivery_id, "claim-1") is True
        await session.commit()
    async with session_factory() as session:
        repo = DeliveryRepositoryImpl(session)
        assert await repo.mark_published(delivery_id, "claim-1", [5]) is True
        await session.commit()
    async with session_factory() as session:
        assert await DeliveryRepositoryImpl(session).claim_reaction(delivery_id) is True
        await session.commit()

    async with session_factory() as session:
        repo = DeliveryRepositoryImpl(session)
        assert await repo.mark_reaction_failed(delivery_id, "vk_denied", "reaction error") is True
        await session.commit()

    raw = await _raw(session_factory, delivery_id)
    assert raw["publication_status"] == PublicationStatus.PUBLISHED.value
    assert raw["reaction_status"] == ReactionStatus.FAILED.value
    assert raw["last_error_code"] == "vk_denied"

    async with session_factory() as session:
        repo = DeliveryRepositoryImpl(session)
        assert await repo.mark_reaction_succeeded(delivery_id) is True
        await session.commit()

    succeeded = await _raw(session_factory, delivery_id)
    assert succeeded["reaction_status"] == ReactionStatus.SUCCEEDED.value
    assert succeeded["publication_status"] == PublicationStatus.PUBLISHED.value


async def test_mark_send_started_with_wrong_claim_token_leaves_row_unchanged(
    session_factory: SessionFactory,
) -> None:
    outcome = await _reserve(session_factory)
    delivery_id = outcome.record.id
    before = await _raw(session_factory, delivery_id)

    assert (
        await _run(
            session_factory,
            lambda repo: repo.mark_send_started(delivery_id, "wrong-token"),
        )
        is False
    )

    assert await _raw(session_factory, delivery_id) == before


async def test_mark_publication_ambiguous_with_wrong_claim_token_leaves_row_unchanged(
    session_factory: SessionFactory,
) -> None:
    outcome = await _reserve_and_claim(session_factory, token="claim-1")
    delivery_id = outcome.record.id
    assert (
        await _run(session_factory, lambda repo: repo.mark_send_started(delivery_id, "claim-1"))
        is True
    )
    before = await _raw(session_factory, delivery_id)

    assert (
        await _run(
            session_factory,
            lambda repo: repo.mark_publication_ambiguous(
                delivery_id, "wrong-token", "timeout", "no reply"
            ),
        )
        is False
    )

    assert await _raw(session_factory, delivery_id) == before


async def test_mark_failed_before_send_with_wrong_claim_token_leaves_row_unchanged(
    session_factory: SessionFactory,
) -> None:
    outcome = await _reserve_and_claim(session_factory, token="claim-1")
    delivery_id = outcome.record.id
    before = await _raw(session_factory, delivery_id)

    assert (
        await _run(
            session_factory,
            lambda repo: repo.mark_failed_before_send(delivery_id, "wrong-token", "rejected", None),
        )
        is False
    )

    assert await _raw(session_factory, delivery_id) == before


async def test_mark_failed_permanent_with_wrong_claim_token_leaves_row_unchanged(
    session_factory: SessionFactory,
) -> None:
    outcome = await _reserve_and_claim(session_factory, token="claim-1")
    delivery_id = outcome.record.id
    assert (
        await _run(session_factory, lambda repo: repo.mark_send_started(delivery_id, "claim-1"))
        is True
    )
    before = await _raw(session_factory, delivery_id)

    assert (
        await _run(
            session_factory,
            lambda repo: repo.mark_failed_permanent(delivery_id, "wrong-token", "forbidden", None),
        )
        is False
    )

    assert await _raw(session_factory, delivery_id) == before


async def test_mark_published_from_reserved_is_illegal(session_factory: SessionFactory) -> None:
    outcome = await _reserve_and_claim(session_factory, token="claim-1")
    delivery_id = outcome.record.id

    rejected = await _run(
        session_factory,
        lambda repo: repo.mark_published(delivery_id, "claim-1", [7]),
    )

    assert rejected is False
    raw = await _raw(session_factory, delivery_id)
    assert raw["publication_status"] == PublicationStatus.RESERVED.value
    assert raw["telegram_message_ids"] is None
    assert raw["completed_at"] is None


async def test_ambiguous_is_terminal_for_reserve_and_claim(
    session_factory: SessionFactory,
) -> None:
    outcome = await _reserve_and_claim(session_factory, token="claim-1")
    delivery_id = outcome.record.id
    assert (
        await _run(session_factory, lambda repo: repo.mark_send_started(delivery_id, "claim-1"))
        is True
    )
    assert (
        await _run(
            session_factory,
            lambda repo: repo.mark_publication_ambiguous(delivery_id, "claim-1", "timeout", None),
        )
        is True
    )

    reclaimed = await _claim(session_factory, delivery_id, "claim-2")
    assert reclaimed is False

    raw = await _raw(session_factory, delivery_id)
    assert raw["publication_status"] == PublicationStatus.AMBIGUOUS.value
    assert raw["review_required"] == 1
    assert raw["claim_token"] == "claim-1"
