"""VK gateway over VKBottle's raw API (plan §9, docs 03 §9-10, docs 05 §14).

The constructor accepts any object exposing ``async request(method, data)`` so the
whole gateway is testable with a fake API and never reaches into SDK model types.
"""

import logging
import random
from collections.abc import Mapping
from typing import Protocol

from vkbottle import VKAPIError

from config import Settings
from vk_topic_bridge.application.dto.infrastructure import LongPollInfo
from vk_topic_bridge.domain.errors import RecoverableInfraError
from vk_topic_bridge.domain.value_objects import Author, SourceMessage, SourceWallPost
from vk_topic_bridge.infrastructure.vk import mapper

logger = logging.getLogger(__name__)

# VK reaction ids are not documented per-emoji; 👍 must be confirmed live at the
# HUMAN GATE / final real E2E before being treated as verified. Single override point.
LIKE_REACTION_ID = 1

_FATAL_CODES = frozenset({5, 15, 100})
_RETRYABLE_CODES = frozenset({6, 10})


class VkError(RecoverableInfraError):
    """Base VK API failure; carries the numeric VK error code."""

    code: int

    def __init__(self, code: int, detail: str = "") -> None:
        self.code = code
        super().__init__(f"vk error {code}" if not detail else f"vk error {code}: {detail}")


class VkFatalError(VkError):
    """Auth/access/invalid-param failure: retrying cannot help."""


class VkRetryableError(VkError):
    """Rate limit or transient internal failure: the caller may retry."""


class RawVkApi(Protocol):
    async def request(
        self, method: str, data: dict[str, object], version: str | None = None
    ) -> dict[str, object]: ...


def _classify(code: int) -> VkError:
    if code in _FATAL_CODES:
        return VkFatalError(code)
    return VkRetryableError(code)


class VkApiGateway:
    """``VkGateway`` implementation writing through a VKBottle-style raw API."""

    def __init__(self, api: RawVkApi, settings: Settings) -> None:
        self._api = api
        self._settings = settings

    async def _request(self, method: str, params: dict[str, object]) -> object:
        logger.debug("vk API request started", extra={"method": method})
        try:
            response = await self._api.request(method, params)
        except VKAPIError as exc:
            logger.warning(
                "vk API request failed",
                extra={"method": method, "reason": str(exc.code)},
            )
            raise _classify(exc.code) from exc
        if not isinstance(response, Mapping):
            logger.warning(
                "vk API returned invalid response",
                extra={"method": method, "reason": "invalid_response"},
            )
            msg = f"unexpected VK response for {method}"
            raise VkRetryableError(1, msg)
        logger.debug("vk API request completed", extra={"method": method})
        return response.get("response")

    async def get_community_id(self) -> int:
        response = await self._request("groups.getById", {})
        groups = response.get("groups") if isinstance(response, Mapping) else None
        if not isinstance(groups, list) or not groups:
            msg = "VK token did not resolve to a community"
            raise VkFatalError(5, msg)
        first = groups[0]
        if not isinstance(first, Mapping) or not isinstance(first.get("id"), int):
            msg = "VK groups.getById returned no numeric community id"
            raise VkFatalError(5, msg)
        derived = first["id"]
        override = self._settings.VK_GROUP_ID
        if override is not None and override != derived:
            msg = f"VK_GROUP_ID={override} does not match token community id {derived}"
            raise VkFatalError(100, msg)
        logger.info("vk community resolved", extra={"group_id": derived})
        return derived

    async def check_long_poll(self) -> LongPollInfo:
        group_id = await self.get_community_id()
        settings = await self._request("groups.getLongPollSettings", {"group_id": group_id})
        enabled = bool(settings.get("is_enabled")) if isinstance(settings, Mapping) else False
        server_info = await self._request("groups.getLongPollServer", {"group_id": group_id})
        if not isinstance(server_info, Mapping):
            msg = "VK groups.getLongPollServer returned no server data"
            raise VkRetryableError(10, msg)
        info = LongPollInfo(
            server=str(server_info.get("server", "")),
            key=str(server_info.get("key", "")),
            ts=str(server_info.get("ts", "")),
            enabled=enabled,
        )
        logger.info(
            "vk long poll settings checked",
            extra={"group_id": group_id, "status": "enabled" if enabled else "disabled"},
        )
        return info

    async def get_author(self, user_id: int) -> Author:
        logger.debug("vk author lookup started", extra={"from_id": user_id})
        response = await self._request("users.get", {"user_ids": [user_id]})
        profiles = response if isinstance(response, list) else []
        profile = profiles[0] if profiles and isinstance(profiles[0], Mapping) else {}
        first_name = profile.get("first_name")
        last_name = profile.get("last_name")
        screen_name = profile.get("screen_name")
        author = Author(
            user_id=user_id,
            first_name=first_name if isinstance(first_name, str) else "",
            last_name=last_name if isinstance(last_name, str) else "",
            screen_name=screen_name if isinstance(screen_name, str) and screen_name else None,
        )
        logger.debug("vk author lookup completed", extra={"from_id": user_id})
        return author

    async def get_full_message(self, peer_id: int, conversation_message_id: int) -> SourceMessage:
        logger.debug(
            "vk full message lookup started",
            extra={"peer_id": peer_id, "conversation_message_id": conversation_message_id},
        )
        response = await self._request(
            "messages.getByConversationMessageId",
            {"peer_id": peer_id, "conversation_message_ids": [conversation_message_id]},
        )
        items = response.get("items") if isinstance(response, Mapping) else None
        if not isinstance(items, list) or not items or not isinstance(items[0], Mapping):
            msg = f"VK returned no message for cmid {conversation_message_id}"
            raise VkRetryableError(10, msg)
        full = items[0]
        from_id = full.get("from_id")
        author = await self.get_author(from_id if isinstance(from_id, int) else peer_id)
        source = mapper.map_message(
            group_id=await self.get_community_id(), message=full, author=author
        )
        logger.debug(
            "vk full message lookup completed",
            extra={
                "peer_id": peer_id,
                "conversation_message_id": conversation_message_id,
                "attachment_count": len(source.attachments),
            },
        )
        return source

    async def set_reaction(self, peer_id: int, conversation_message_id: int) -> None:
        logger.debug(
            "vk reaction request started",
            extra={"peer_id": peer_id, "conversation_message_id": conversation_message_id},
        )
        await self._request(
            "messages.sendReaction",
            {
                "peer_id": peer_id,
                "cmid": conversation_message_id,
                "reaction_id": LIKE_REACTION_ID,
            },
        )
        logger.debug(
            "vk reaction request completed",
            extra={"peer_id": peer_id, "conversation_message_id": conversation_message_id},
        )

    async def send_user_message(self, user_id: int, text: str, keyboard_json: str | None) -> int:
        """``messages.send`` to one user DM; returns the sent message id.

        ``random_id`` is always generated: VK uses it to deduplicate an identical
        retried send, which matters because this call is the UI reply transport.
        """
        params: dict[str, object] = {
            "peer_id": user_id,
            "message": text,
            "random_id": random.getrandbits(31),
        }
        if keyboard_json is not None:
            params["keyboard"] = keyboard_json
        logger.debug(
            "vk UI reply started",
            extra={"owner_id": user_id, "text_length": len(text)},
        )
        response = await self._request("messages.send", params)
        message_id = response if isinstance(response, int) else 0
        logger.debug(
            "vk UI reply completed",
            extra={"owner_id": user_id, "message_id_count": 1 if message_id else 0},
        )
        return message_id

    async def normalize_event(
        self, raw_event: Mapping[str, object], author: Author
    ) -> SourceMessage:
        """Single entry point for the VK handler: map or complete a cropped message."""
        group_id = raw_event.get("group_id")
        if not isinstance(group_id, int):
            msg = "VK event payload is missing integer group_id"
            raise ValueError(msg)
        obj = mapper.extract_message_payload(raw_event)
        if obj is None:
            msg = "VK event payload is missing the object message mapping"
            raise ValueError(msg)
        if mapper.is_cropped(obj):
            logger.debug("vk message normalization requires full lookup")
            peer_id = obj.get("peer_id")
            cmid = obj.get("conversation_message_id")
            if not isinstance(peer_id, int) or isinstance(peer_id, bool):
                msg = "cropped VK event is missing integer peer_id"
                raise ValueError(msg)
            if not isinstance(cmid, int) or isinstance(cmid, bool):
                msg = "cropped VK event is missing integer conversation_message_id"
                raise ValueError(msg)
            return await self.get_full_message(peer_id, cmid)
        source = mapper.map_message(group_id=group_id, message=obj, author=author)
        logger.debug(
            "vk message normalized",
            extra={
                "source_type": source.source_type.value,
                "attachment_count": len(source.attachments),
            },
        )
        return source

    async def normalize_wall_event(
        self, raw_event: Mapping[str, object], author: Author
    ) -> SourceWallPost:
        """Map one ``wall_post_new`` event into the domain wall-post form."""
        group_id = raw_event.get("group_id")
        if not isinstance(group_id, int) or isinstance(group_id, bool):
            msg = "VK wall event is missing integer group_id"
            raise ValueError(msg)
        obj = mapper.extract_wall_payload(raw_event)
        if obj is None:
            msg = "VK wall event payload is missing the object mapping"
            raise ValueError(msg)
        source = mapper.map_wall_post(group_id=group_id, payload=obj, author=author)
        logger.debug(
            "vk wall post normalized",
            extra={
                "source_type": source.source_type.value,
                "attachment_count": len(source.attachments),
            },
        )
        return source
