"""Unit tests for the VK Long Poll consumer: transport decoding and topology guard."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import cast

from vk_topic_bridge.application.forwarding.forward_message import ForwardOutcome, ForwardVkMessage
from vk_topic_bridge.bootstrap.vk_consumer import VkEventConsumer
from vk_topic_bridge.domain.enums import SourceType
from vk_topic_bridge.domain.value_objects import Author, SourceMessage
from vk_topic_bridge.infrastructure.vk.api import VkApiGateway

ALLOWED_GROUP = 1
PEER_ID = 100
SECOND_PEER_ID = 200
FROM_ID = 7


def _author(user_id: int = FROM_ID) -> Author:
    return Author(user_id=user_id, first_name="Ann", last_name="Lee", screen_name=None)


def _source(*, peer_id: int = PEER_ID, author: Author | None = None) -> SourceMessage:
    return SourceMessage(
        source_type=SourceType.VK_MESSAGE,
        source_key=f"vk:{ALLOWED_GROUP}:{peer_id}:55",
        group_id=ALLOWED_GROUP,
        peer_id=peer_id,
        conversation_message_id=55,
        author=author or _author(),
        text="hello",
        has_all=False,
        has_hashtag=False,
        attachments=(),
    )


def _update(
    *,
    event_type: str = "message_new",
    group_id: int = ALLOWED_GROUP,
    peer_id: int = PEER_ID,
    from_id: int = FROM_ID,
) -> dict[str, object]:
    return {
        "type": event_type,
        "group_id": group_id,
        "event_id": "evt-1",
        "object": {
            "peer_id": peer_id,
            "from_id": from_id,
            "conversation_message_id": 55,
            "text": "hello",
        },
    }


def _event(*updates: dict[str, object]) -> dict[str, object]:
    return {"ts": 1, "updates": list(updates)}


class FakePolling:
    def __init__(self, events: list[dict[str, object]]) -> None:
        self._events = events
        self.stop_calls = 0

    async def listen(self) -> AsyncIterator[dict[str, object]]:
        for event in self._events:
            yield event

    def stop(self) -> None:
        self.stop_calls += 1


class FakeGateway:
    def __init__(self, *, fail_first_normalize: bool = False) -> None:
        self.author_calls: list[int] = []
        self.normalize_calls: list[Mapping[str, object]] = []
        self._fail_first = fail_first_normalize
        self._normalize_count = 0

    async def get_author(self, user_id: int) -> Author:
        self.author_calls.append(user_id)
        return _author(user_id)

    async def normalize_event(
        self, raw_event: Mapping[str, object], author: Author
    ) -> SourceMessage:
        self.normalize_calls.append(raw_event)
        self._normalize_count += 1
        if self._fail_first and self._normalize_count == 1:
            raise RuntimeError("normalize failed")
        peer_id = raw_event.get("object")
        resolved = peer_id.get("peer_id") if isinstance(peer_id, Mapping) else PEER_ID
        return _source(peer_id=resolved if isinstance(resolved, int) else PEER_ID, author=author)


class FakeForward:
    def __init__(self) -> None:
        self.calls: list[SourceMessage] = []

    async def execute(self, source: SourceMessage) -> ForwardOutcome:
        self.calls.append(source)
        return ForwardOutcome(published=True, skipped=False, reason="test", delivery_id=1)


def _consumer(
    events: list[dict[str, object]],
    *,
    gateway: FakeGateway | None = None,
    forward: FakeForward | None = None,
) -> tuple[VkEventConsumer, FakeGateway, FakeForward]:
    fake_gateway = gateway or FakeGateway()
    fake_forward = forward or FakeForward()
    consumer = VkEventConsumer(
        polling=FakePolling(events),
        gateway=cast(VkApiGateway, fake_gateway),
        forward=cast(ForwardVkMessage, fake_forward),
        allowed_group_id=ALLOWED_GROUP,
    )
    return consumer, fake_gateway, fake_forward


async def test_valid_message_new_is_forwarded_once() -> None:
    consumer, gateway, forward = _consumer([_event(_update())])

    await consumer.run()

    assert len(forward.calls) == 1
    assert forward.calls[0].peer_id == PEER_ID
    assert gateway.author_calls == [FROM_ID]


async def test_message_new_from_other_group_is_ignored() -> None:
    consumer, _, forward = _consumer([_event(_update(group_id=ALLOWED_GROUP + 1))])

    await consumer.run()

    assert forward.calls == []


async def test_second_peer_id_is_dropped_and_binding_stays() -> None:
    consumer, _, forward = _consumer(
        [_event(_update(peer_id=PEER_ID), _update(peer_id=SECOND_PEER_ID))]
    )

    await consumer.run()

    assert len(forward.calls) == 1
    assert consumer.bound_peer_id == PEER_ID


async def test_non_message_new_update_is_ignored() -> None:
    consumer, _, forward = _consumer([_event(_update(event_type="message_reply"))])

    await consumer.run()

    assert forward.calls == []


async def test_failing_update_does_not_stop_the_loop() -> None:
    gateway = FakeGateway(fail_first_normalize=True)
    consumer, _, forward = _consumer([_event(_update(), _update())], gateway=gateway)

    await consumer.run()

    assert len(gateway.normalize_calls) == 2
    assert len(forward.calls) == 1


async def test_run_returns_when_the_stream_ends() -> None:
    consumer, _, forward = _consumer([_event(_update())])

    await consumer.run()

    assert len(forward.calls) == 1
