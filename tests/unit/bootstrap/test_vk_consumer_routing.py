"""Routing tests: community conversations vs independent user DMs (finish task 2).

VK peer semantics: a DM carries a positive user ``peer_id``; a community conversation
carries ``peer_id = 2000000000 + chat_id``. The guard must never let one user's DM
block another user's DM or the source conversation.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any, cast

from tests.acceptance._fakes import make_test_source_resolver
from vk_topic_bridge.application.forwarding.forward_message import ForwardOutcome, ForwardVkMessage
from vk_topic_bridge.application.manual.aliasing import AliasManager, ManualForwarding
from vk_topic_bridge.application.manual.publish_manual import PublishManualMessage
from vk_topic_bridge.application.ports.vk_ex import VkManualUiPort
from vk_topic_bridge.bootstrap.vk_consumer import VkEventConsumer, VkUiRouter
from vk_topic_bridge.domain.enums import SourceType
from vk_topic_bridge.domain.routing_policy import PeerRoute, classify_peer
from vk_topic_bridge.domain.value_objects import Author, SourceMessage, SourceWallPost
from vk_topic_bridge.infrastructure.vk.api import VkApiGateway

ALLOWED_GROUP = 1
CONVERSATION_PEER = 2_000_000_123
DM_USER_A = 111
DM_USER_B = 222


def _author(user_id: int) -> Author:
    return Author(user_id=user_id, first_name="Ann", last_name="Lee", screen_name=None)


def _source(peer_id: int, from_id: int) -> SourceMessage:
    return SourceMessage(
        source_type=SourceType.VK_MESSAGE,
        source_key=f"vk:{ALLOWED_GROUP}:{peer_id}:55",
        group_id=ALLOWED_GROUP,
        peer_id=peer_id,
        conversation_message_id=55,
        author=_author(from_id),
        text="hello",
        has_all=False,
        has_hashtag=False,
        attachments=(),
    )


def _update(peer_id: int, from_id: int) -> dict[str, object]:
    return {
        "type": "message_new",
        "group_id": ALLOWED_GROUP,
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
    def __init__(self) -> None:
        self.author_calls: list[int] = []
        self.normalize_calls: list[int] = []

    async def get_author(self, user_id: int) -> Author:
        self.author_calls.append(user_id)
        return _author(user_id)

    async def normalize_event(
        self, raw_event: Mapping[str, object], author: Author
    ) -> SourceMessage:
        obj = raw_event["object"]
        assert isinstance(obj, Mapping)
        peer_id = obj["peer_id"]
        assert isinstance(peer_id, int)
        from_id = obj["from_id"]
        assert isinstance(from_id, int)
        self.normalize_calls.append(peer_id)
        return _source(peer_id, from_id)

    async def normalize_wall_event(
        self, raw_event: Mapping[str, object], author: Author
    ) -> SourceWallPost:
        obj = raw_event["object"]
        assert isinstance(obj, Mapping)
        owner_id = obj["owner_id"]
        post_id = obj["id"]
        assert isinstance(owner_id, int)
        assert isinstance(post_id, int)
        return SourceWallPost(
            source_type=SourceType.VK_WALL,
            source_key=f"{ALLOWED_GROUP}:{owner_id}:{post_id}",
            group_id=ALLOWED_GROUP,
            owner_id=owner_id,
            post_id=post_id,
            author=author,
            text="post",
            url=f"https://vk.com/wall{owner_id}_{post_id}",
            attachments=(),
        )


class FakeForward:
    def __init__(self) -> None:
        self.calls: list[SourceMessage] = []

    async def execute(self, source: SourceMessage) -> ForwardOutcome:
        self.calls.append(source)
        return ForwardOutcome(published=True, skipped=False, reason="test", delivery_id=1)


class FakeUiRouter:
    def __init__(self) -> None:
        self.handle_calls: list[Mapping[str, object]] = []

    async def handle_dm(self, update: Mapping[str, object]) -> bool:
        self.handle_calls.append(update)
        return True


def _consumer(
    events: list[dict[str, object]],
    *,
    ui_router: VkUiRouter | None = None,
) -> tuple[VkEventConsumer, FakeGateway, FakeForward, VkUiRouter]:
    gateway = FakeGateway()
    forward = FakeForward()
    router: VkUiRouter = ui_router or FakeUiRouter()
    consumer = VkEventConsumer(
        polling=FakePolling(events),
        gateway=cast(VkApiGateway, gateway),
        forward=cast(ForwardVkMessage, forward),
        allowed_group_id=ALLOWED_GROUP,
        ui_router=router,
    )
    return consumer, gateway, forward, router


def test_classify_peer_conversation_route() -> None:
    classification = classify_peer(CONVERSATION_PEER)

    assert classification.route is PeerRoute.COMMUNITY_CONVERSATION
    assert classification.chat_id == 123


def test_classify_peer_dm_route() -> None:
    classification = classify_peer(DM_USER_A)

    assert classification.route is PeerRoute.USER_DM
    assert classification.chat_id is None


async def test_conversation_event_is_forwarded_once() -> None:
    consumer, _, forward, router = _consumer([_event(_update(CONVERSATION_PEER, 7))])

    await consumer.run()

    assert isinstance(router, FakeUiRouter)
    assert len(forward.calls) == 1
    assert forward.calls[0].peer_id == CONVERSATION_PEER
    assert router.handle_calls == []


async def test_two_independent_dms_both_reach_ui_router() -> None:
    consumer, _, forward, router = _consumer(
        [
            _event(_update(DM_USER_A, DM_USER_A), _update(DM_USER_B, DM_USER_B)),
        ]
    )

    await consumer.run()

    assert isinstance(router, FakeUiRouter)
    assert len(router.handle_calls) == 2
    assert forward.calls == []


async def test_dm_does_not_bind_conversation_guard() -> None:
    consumer, _, forward, _ = _consumer(
        [
            _event(_update(DM_USER_A, DM_USER_A), _update(CONVERSATION_PEER, 7)),
        ]
    )

    await consumer.run()

    assert len(forward.calls) == 1
    assert forward.calls[0].peer_id == CONVERSATION_PEER


async def test_second_conversation_peer_is_still_rejected() -> None:
    second_conversation = CONVERSATION_PEER + 1
    consumer, _, forward, _ = _consumer(
        [
            _event(
                _update(CONVERSATION_PEER, 7),
                _update(second_conversation, 7),
            )
        ]
    )

    await consumer.run()

    assert len(forward.calls) == 1
    assert forward.calls[0].peer_id == CONVERSATION_PEER


async def test_dm_without_ui_router_is_skipped_silently() -> None:
    gateway = FakeGateway()
    forward = FakeForward()
    consumer = VkEventConsumer(
        polling=FakePolling([_event(_update(DM_USER_A, DM_USER_A))]),
        gateway=cast(VkApiGateway, gateway),
        forward=cast(ForwardVkMessage, forward),
        allowed_group_id=ALLOWED_GROUP,
    )

    await consumer.run()

    assert forward.calls == []
    assert gateway.author_calls == []


# --- real VkUiDispatcher as the consumer's UI router (T15 fan-out seam) -------


class _SendRecorder:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_user_message(self, user_id: int, text: str, keyboard_json: str | None) -> int:
        self.messages.append((user_id, text))
        return len(self.messages)


async def test_dm_reaches_real_dispatcher_and_produces_ui_reply() -> None:
    from vk_topic_bridge.presentation.vk.handlers import VkUiDispatcher
    from vk_topic_bridge.presentation.vk.states import VkSessionStore

    send = _SendRecorder()
    dispatcher = VkUiDispatcher(
        VkSessionStore(),
        cast(VkManualUiPort, send),
        manual_forwarding=cast(ManualForwarding, None),
        alias_manager=cast(AliasManager, None),
        manual_publisher=cast(PublishManualMessage, None),
        source_resolver=cast(Any, make_test_source_resolver()),
    )
    consumer, _, forward, _ = _consumer(
        [_event(_update(DM_USER_A, DM_USER_A))],
        ui_router=dispatcher,
    )

    await consumer.run()

    assert len(send.messages) == 1
    assert send.messages[0][0] == DM_USER_A
    assert forward.calls == []


# --- wall_post_new branch (runs before peer routing) --------------------------


class FakeForwardWall:
    def __init__(self) -> None:
        self.calls: list[object] = []

    async def execute(self, wall_post: object) -> object:
        from vk_topic_bridge.application.forwarding.forward_wall import WallForwardOutcome

        self.calls.append(wall_post)
        return WallForwardOutcome(published=True, skipped=False, reason="published")


async def test_wall_event_routes_to_wall_pipeline_before_peer_classification() -> None:
    from vk_topic_bridge.application.forwarding.forward_wall import ForwardWallPost

    gateway = FakeGateway()
    forward = FakeForward()
    wall_forward = FakeForwardWall()
    wall_event = {
        "type": "wall_post_new",
        "group_id": ALLOWED_GROUP,
        "object": {
            "id": 5,
            "owner_id": -ALLOWED_GROUP,
            "from_id": -ALLOWED_GROUP,
            "text": "пост",
            "attachments": [],
        },
    }
    consumer = VkEventConsumer(
        polling=FakePolling([_event(wall_event)]),
        gateway=cast(VkApiGateway, gateway),
        forward=cast(ForwardVkMessage, forward),
        allowed_group_id=ALLOWED_GROUP,
        forward_wall=cast(ForwardWallPost, wall_forward),
    )

    await consumer.run()

    assert len(wall_forward.calls) == 1
    assert forward.calls == []


async def test_wall_event_without_pipeline_is_ignored() -> None:
    gateway = FakeGateway()
    forward = FakeForward()
    wall_event = {
        "type": "wall_post_new",
        "group_id": ALLOWED_GROUP,
        "object": {"id": 5, "owner_id": -ALLOWED_GROUP, "text": "пост"},
    }
    consumer = VkEventConsumer(
        polling=FakePolling([_event(wall_event)]),
        gateway=cast(VkApiGateway, gateway),
        forward=cast(ForwardVkMessage, forward),
        allowed_group_id=ALLOWED_GROUP,
    )

    await consumer.run()

    assert forward.calls == []


async def test_wall_event_from_other_group_is_rejected() -> None:
    from vk_topic_bridge.application.forwarding.forward_wall import ForwardWallPost

    gateway = FakeGateway()
    forward = FakeForward()
    wall_forward = FakeForwardWall()
    wall_event = {
        "type": "wall_post_new",
        "group_id": ALLOWED_GROUP + 1,
        "object": {"id": 5, "owner_id": -ALLOWED_GROUP, "text": "пост"},
    }
    consumer = VkEventConsumer(
        polling=FakePolling([_event(wall_event)]),
        gateway=cast(VkApiGateway, gateway),
        forward=cast(ForwardVkMessage, forward),
        allowed_group_id=ALLOWED_GROUP,
        forward_wall=cast(ForwardWallPost, wall_forward),
    )

    await consumer.run()

    assert wall_forward.calls == []
