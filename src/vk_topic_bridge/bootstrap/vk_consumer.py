"""VK Long Poll consumer: decode transport events, guard topology, hand off to forwarding.

The consumer owns no SDK types: it talks to a ``BotPollingLike`` transport, normalizes
through ``VkApiGateway`` and never builds a ``SourceMessage`` itself.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from pathlib import Path
from typing import Protocol, TypeGuard, cast

from vkbottle.api import ABCAPI
from vkbottle.polling import BotPolling
from vkbottle_types.events import GroupEventType

from vk_topic_bridge.application.forwarding.forward_message import ForwardVkMessage
from vk_topic_bridge.application.forwarding.forward_wall import ForwardWallPost
from vk_topic_bridge.domain.routing_policy import PeerRoute, classify_peer
from vk_topic_bridge.domain.value_objects import Author
from vk_topic_bridge.infrastructure.vk.api import RawVkApi, VkApiGateway
from vk_topic_bridge.infrastructure.vk.cursor import RuntimePathBotPolling
from vk_topic_bridge.infrastructure.vk.mapper import (
    FirstPeerGuard,
    extract_message_payload,
    extract_wall_payload,
)

logger = logging.getLogger(__name__)


class BotPollingLike(Protocol):
    """Minimal transport surface: an async stream of raw Long Poll events plus stop."""

    def listen(self) -> AsyncIterator[dict[str, object]]: ...

    def stop(self) -> None: ...


class VkUiRouter(Protocol):
    """Presentation fan-out for user-DM UI events (finish plan)."""

    async def handle_dm(self, update: Mapping[str, object]) -> bool: ...

    async def handle_message_event(self, update: Mapping[str, object]) -> bool: ...


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


class VkEventConsumer:
    """Turn one Long Poll stream into forwarding calls, never crashing."""

    def __init__(
        self,
        *,
        polling: BotPollingLike,
        gateway: VkApiGateway,
        forward: ForwardVkMessage,
        allowed_group_id: int,
        ui_router: VkUiRouter | None = None,
        forward_wall: ForwardWallPost | None = None,
    ) -> None:
        self._polling = polling
        self._gateway = gateway
        self._forward = forward
        self._allowed_group_id = allowed_group_id
        self._ui_router = ui_router
        self._forward_wall = forward_wall
        self._peer_guard = FirstPeerGuard()

    @property
    def bound_peer_id(self) -> int | None:
        return self._peer_guard.current()

    async def run(self) -> None:
        """Consume the stream until it ends or the task is cancelled."""
        logger.info(
            "vk consumer started",
            extra={"group_id": self._allowed_group_id, "poller": type(self._polling).__name__},
        )
        try:
            async for event in self._polling.listen():
                updates = event.get("updates")
                if not isinstance(updates, list):
                    logger.debug("vk long poll event ignored: updates is not a list")
                    continue
                logger.debug("vk event received", extra={"update_count": len(updates)})
                for update in updates:
                    await self._handle(update)
        finally:
            logger.info(
                "vk consumer stopped",
                extra={"group_id": self._allowed_group_id, "peer_id": self.bound_peer_id},
            )

    async def _handle(self, update: object) -> None:
        # One bad update must never kill the consumer: log with context and keep going.
        group_id = update.get("group_id") if isinstance(update, Mapping) else None
        peer_id: object = None
        try:
            if not isinstance(update, Mapping):
                logger.warning("vk update is not a mapping: %r", type(update).__name__)
                return
            event_type = update.get("type")
            logger.debug(
                "vk update received",
                extra={
                    "event_id": update.get("event_id"),
                    "event_type": event_type,
                    "group_id": group_id,
                },
            )
            if event_type == "wall_post_new":
                await self._handle_wall(update, group_id)
                return
            if event_type == GroupEventType.MESSAGE_EVENT.value:
                if group_id != self._allowed_group_id or self._ui_router is None:
                    return
                await self._ui_router.handle_message_event(update)
                return
            if event_type != "message_new":
                logger.debug(
                    "vk update ignored: unsupported event", extra={"event_type": event_type}
                )
                return
            if not _is_int(group_id):
                logger.warning("vk update has no integer group_id: %r", group_id)
                return
            if group_id != self._allowed_group_id:
                logger.warning(
                    "vk update arrived from another group: got %s, expected %s",
                    group_id,
                    self._allowed_group_id,
                )
                return
            obj = extract_message_payload(update)
            if obj is None:
                logger.warning("vk update has no message payload for group %s", group_id)
                return
            peer_id = obj.get("peer_id")
            if not _is_int(peer_id):
                logger.warning("vk update has no integer peer_id for group %s", group_id)
                return
            classification = classify_peer(peer_id)
            logger.debug(
                "vk message route classified",
                extra={
                    "peer_id": peer_id,
                    "route": classification.route.value,
                    "chat_id": classification.chat_id,
                },
            )
            if classification.route is PeerRoute.USER_DM:
                if self._ui_router is not None:
                    consumed = await self._ui_router.handle_dm(update)
                    logger.debug(
                        "vk DM routed to UI",
                        extra={
                            "peer_id": peer_id,
                            "outcome": "consumed" if consumed else "ignored",
                        },
                    )
                else:
                    logger.debug(
                        "vk DM from peer %s skipped: no UI router wired "
                        "(destination_not_configured)",
                        peer_id,
                    )
                return
            if not self._peer_guard.bind(peer_id):
                logger.warning(
                    "vk topology violation: peer_id %s does not match the bound peer %s",
                    peer_id,
                    self._peer_guard.current(),
                )
                return
            from_id = obj.get("from_id")
            if not _is_int(from_id):
                logger.warning("vk update has no integer from_id for peer %s", peer_id)
                return
            author = await self._gateway.get_author(from_id)
            source = await self._gateway.normalize_event(update, author)
            logger.debug(
                "vk message routed to forwarding",
                extra={
                    "group_id": source.group_id,
                    "peer_id": source.peer_id,
                    "from_id": source.author.user_id,
                    "conversation_message_id": source.conversation_message_id,
                    "source_key": source.source_key,
                    "source_type": source.source_type.value,
                    "attachment_count": len(source.attachments),
                },
            )
            outcome = await self._forward.execute(source)
            logger.debug(
                "vk message forwarding completed",
                extra={
                    "peer_id": source.peer_id,
                    "from_id": source.author.user_id,
                    "conversation_message_id": source.conversation_message_id,
                    "source_key": source.source_key,
                    "outcome": outcome.reason,
                    "published": outcome.published,
                    "skipped": outcome.skipped,
                    "delivery_id": outcome.delivery_id,
                    "message_id_count": len(outcome.message_ids),
                },
            )
            if outcome.published:
                logger.info(
                    "vk message forwarded",
                    extra={
                        "peer_id": source.peer_id,
                        "conversation_message_id": source.conversation_message_id,
                        "delivery_id": outcome.delivery_id,
                        "message_id_count": len(outcome.message_ids),
                    },
                )
        except Exception:
            logger.exception("vk update handling failed for group=%s peer=%s", group_id, peer_id)

    async def _handle_wall(self, update: Mapping[str, object], group_id: object) -> None:
        """Wall posts come from the community, so this branch runs before peer routing."""
        if self._forward_wall is None:
            logger.debug("vk wall update ignored: wall pipeline is not configured")
            return
        if not _is_int(group_id):
            logger.warning("vk wall update has no integer group_id: %r", group_id)
            return
        if group_id != self._allowed_group_id:
            logger.warning(
                "vk wall update arrived from another group: got %s, expected %s",
                group_id,
                self._allowed_group_id,
            )
            return
        obj = extract_wall_payload(update)
        if obj is None:
            logger.warning("vk wall update has no object payload for group %s", group_id)
            return
        owner_id = obj.get("owner_id")
        author = await self._gateway.get_author(owner_id) if _is_int(owner_id) else None
        if author is None:
            author = Author(user_id=0, first_name="", last_name="", screen_name=None)
        wall_post = await self._gateway.normalize_wall_event(update, author)
        logger.debug(
            "vk wall post routed to forwarding",
            extra={
                "group_id": wall_post.group_id,
                "owner_id": wall_post.owner_id,
                "post_id": wall_post.post_id,
                "source_type": wall_post.source_type.value,
                "attachment_count": len(wall_post.attachments),
            },
        )
        outcome = await self._forward_wall.execute(wall_post)
        logger.debug(
            "vk wall forwarding completed",
            extra={
                "group_id": wall_post.group_id,
                "owner_id": wall_post.owner_id,
                "post_id": wall_post.post_id,
                "outcome": outcome.reason,
                "published": outcome.published,
                "skipped": outcome.skipped,
                "delivery_id": outcome.delivery_id,
                "message_id_count": len(outcome.message_ids),
            },
        )
        if outcome.published:
            logger.info(
                "vk wall post forwarded",
                extra={
                    "group_id": wall_post.group_id,
                    "owner_id": wall_post.owner_id,
                    "post_id": wall_post.post_id,
                    "delivery_id": outcome.delivery_id,
                },
            )


class VkPollingRuntime:
    """Mutable holder shared between the polling coroutine and the stop callable.

    ``build_container`` must not perform I/O, so the ``BotPolling`` object and the running
    task only exist after the coroutine starts; the holder makes teardown safe in either
    order and idempotent.
    """

    def __init__(
        self,
        api: RawVkApi,
        gateway: VkApiGateway,
        forward: ForwardVkMessage,
        *,
        forward_wall: ForwardWallPost | None = None,
        ui_router: object | None = None,
        cursor_dir: Path | None = None,
        on_history_gap: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._api = api
        self._gateway = gateway
        self._forward = forward
        self._forward_wall = forward_wall
        self._ui_router = ui_router
        self._cursor_dir = cursor_dir
        self._on_history_gap = on_history_gap
        self._stop_requested = asyncio.Event()
        self._polling: BotPollingLike | None = None
        self._task: asyncio.Task[None] | None = None

    async def run(self) -> None:
        logger.info("vk polling starting")
        allowed_group_id = await self._gateway.get_community_id()
        logger.info("vk polling community resolved", extra={"group_id": allowed_group_id})
        # RawVkApi is the structural twin of ABCAPI (same ``request``); the SDK types it
        # nominally, so this single boundary cast is the only place the two meet.
        raw_api = cast(ABCAPI, self._api)
        polling: BotPollingLike
        if self._cursor_dir is not None:
            self._cursor_dir.mkdir(parents=True, exist_ok=True)
            polling = RuntimePathBotPolling(
                state_dir=self._cursor_dir,
                on_history_gap=self._on_history_gap,
                api=raw_api,
                group_id=allowed_group_id,
            )
        else:
            polling = BotPolling(api=raw_api, group_id=allowed_group_id)
        self._polling = polling
        logger.debug(
            "vk polling transport configured",
            extra={"group_id": allowed_group_id, "poller": type(polling).__name__},
        )
        consumer = VkEventConsumer(
            polling=polling,
            gateway=self._gateway,
            forward=self._forward,
            allowed_group_id=allowed_group_id,
            ui_router=cast("VkUiRouter | None", self._ui_router),
            forward_wall=self._forward_wall,
        )
        self._task = asyncio.current_task()
        if self._stop_requested.is_set():
            logger.info(
                "vk polling stopped before consumer start", extra={"group_id": allowed_group_id}
            )
            return
        try:
            await consumer.run()
        finally:
            logger.info("vk polling stopped", extra={"group_id": allowed_group_id})

    async def stop(self) -> None:
        logger.debug("vk polling stop requested")
        self._stop_requested.set()
        if self._polling is not None:
            self._polling.stop()
        task = self._task
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
