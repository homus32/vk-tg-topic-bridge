"""Pure VK Long Poll event normalization into domain value objects (plan §9).

No SDK types cross this boundary: the presentation layer hands raw ``Mapping``
payloads in and receives ``SourceMessage``/``Author`` back.
"""

import logging
from collections.abc import Mapping

from vk_topic_bridge.domain.enums import SourceType
from vk_topic_bridge.domain.policies.attachment_policy import classify_attachment_type
from vk_topic_bridge.domain.policies.forwarding_policy import decide, source_key
from vk_topic_bridge.domain.value_objects import (
    Attachment,
    Author,
    MediaVariant,
    SourceMessage,
    SourceWallPost,
)
from vk_topic_bridge.domain.wall_post import wall_post_url, wall_source_key

_MISSING = object()
logger = logging.getLogger(__name__)


def extract_message_payload(
    raw_event: Mapping[str, object],
) -> Mapping[str, object] | None:
    raw_object = raw_event.get("object")
    if not isinstance(raw_object, Mapping):
        return None
    if "message" not in raw_object:
        return raw_object
    message = raw_object["message"]
    return message if isinstance(message, Mapping) else None


def extract_wall_payload(
    raw_event: Mapping[str, object],
) -> Mapping[str, object] | None:
    """The ``wall_post_new`` object lives directly under ``object`` (no nesting)."""
    raw_object = raw_event.get("object")
    return raw_object if isinstance(raw_object, Mapping) else None


def is_cropped(message: Mapping[str, object]) -> bool:
    """``is_cropped`` is optional and may arrive as bool, int or ``None``."""
    value = message.get("is_cropped")
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    return False


def _require_int(message: Mapping[str, object], field: str) -> int:
    value = message.get(field, _MISSING)
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"VK message payload is missing integer field {field!r}"
        raise ValueError(msg)
    return value


def _optional_str(message: Mapping[str, object], field: str) -> str | None:
    value = message.get(field)
    if isinstance(value, str) and value:
        return value
    return None


def _optional_https_url(message: Mapping[str, object], field: str) -> str | None:
    value = _optional_str(message, field)
    return value if value is not None and value.startswith("https://") else None


def _optional_int(message: Mapping[str, object], field: str) -> int | None:
    value = message.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _map_variants(payload: Mapping[str, object], raw_type: str) -> tuple[MediaVariant, ...]:
    variants: list[MediaVariant] = []
    seen: set[str] = set()
    if raw_type == "video":
        files = payload.get("files")
        if isinstance(files, Mapping):
            for quality, raw_url in files.items():
                if isinstance(quality, str) and isinstance(raw_url, str) and raw_url:
                    variants.append(MediaVariant(url=raw_url, quality=quality))
        return tuple(variants)
    sources = (payload.get("images"), payload.get("sizes")) if raw_type == "photo" else ()
    for source in sources:
        if not isinstance(source, list):
            continue
        for raw_variant in source:
            if not isinstance(raw_variant, Mapping):
                continue
            url = raw_variant.get("url")
            if not isinstance(url, str) or not url or url in seen:
                continue
            seen.add(url)
            quality = _optional_str(raw_variant, "type")
            variants.append(
                MediaVariant(
                    url=url,
                    quality=quality,
                    width=_optional_int(raw_variant, "width"),
                    height=_optional_int(raw_variant, "height"),
                )
            )
    return tuple(variants)


def _map_attachment(raw: object) -> Attachment | None:
    if not isinstance(raw, Mapping):
        return None
    raw_type = raw.get("type")
    if not isinstance(raw_type, str):
        return None
    payload = raw.get(raw_type)
    file_name: str | None = None
    size_bytes: int | None = None
    source_ref: str | None = None
    owner_id: int | None = None
    media_id: int | None = None
    access_key: str | None = None
    direct_url: str | None = None
    link_url: str | None = None
    variants: tuple[MediaVariant, ...] = ()
    if isinstance(payload, Mapping):
        file_name = _optional_str(payload, "title")
        size_bytes = _optional_int(payload, "size")
        owner_id = _optional_int(payload, "owner_id")
        media_id = _optional_int(payload, "id")
        access_key = _optional_str(payload, "access_key")
        if owner_id is not None and media_id is not None:
            source_ref = f"{owner_id}_{media_id}"
            if access_key is not None:
                source_ref = f"{source_ref}_{access_key}"
        direct_url = _optional_str(payload, "url")
        link_url = _optional_https_url(payload, "player")
        if (
            raw_type == "video"
            and link_url is None
            and owner_id is not None
            and media_id is not None
        ):
            link_url = f"https://vk.com/video{owner_id}_{media_id}"
        variants = _map_variants(payload, raw_type)
    logger.debug(
        "vk attachment mapped",
        extra={
            "attachment_kind": raw_type,
            "owner_id": owner_id,
            "media_id": media_id,
            "access_key_present": access_key is not None,
            "direct_url_present": direct_url is not None,
            "variant_count": len(variants),
            "filename_present": file_name is not None,
            "size_bytes": size_bytes,
        },
    )
    return Attachment(
        kind=classify_attachment_type(raw_type),
        file_name=file_name,
        size_bytes=size_bytes,
        source_ref=source_ref,
        owner_id=owner_id,
        media_id=media_id,
        access_key=access_key,
        direct_url=direct_url,
        link_url=link_url,
        variants=variants,
    )


def _map_attachments(raw: object) -> tuple[Attachment, ...]:
    if not isinstance(raw, list):
        return ()
    attachments: list[Attachment] = []
    for item in raw:
        mapped = _map_attachment(item)
        if mapped is not None:
            attachments.append(mapped)
    return tuple(attachments)


def map_message(
    *,
    group_id: int,
    message: Mapping[str, object],
    author: Author,
) -> SourceMessage:
    """Map one ``message_new`` object (fields live directly under it) to domain form."""
    peer_id = _require_int(message, "peer_id")
    conversation_message_id = _require_int(message, "conversation_message_id")

    raw_text = message.get("text")
    text = raw_text if isinstance(raw_text, str) else ""

    # Both toggles on: the decision only reports which tokens matched, not whether to forward.
    decision = decide(text, auto_forward_all=True, auto_forward_hashtags=True)

    return SourceMessage(
        source_type=SourceType.VK_MESSAGE,
        source_key=source_key(group_id, peer_id, conversation_message_id),
        group_id=group_id,
        peer_id=peer_id,
        conversation_message_id=conversation_message_id,
        author=author,
        text=text,
        has_all=decision.matched_all,
        has_hashtag=decision.matched_hashtag,
        attachments=_map_attachments(message.get("attachments")),
    )


def map_wall_post(
    *,
    group_id: int,
    payload: Mapping[str, object],
    author: Author,
) -> SourceWallPost:
    """Map one ``wall_post_new`` object into the domain wall-post form."""
    owner_id = _require_int(payload, "owner_id")
    post_id = _require_int(payload, "id")

    raw_text = payload.get("text")
    text = raw_text if isinstance(raw_text, str) else ""

    return SourceWallPost(
        source_type=SourceType.VK_WALL,
        source_key=wall_source_key(group_id, owner_id, post_id),
        group_id=group_id,
        owner_id=owner_id,
        post_id=post_id,
        author=author,
        text=text,
        url=wall_post_url(owner_id, post_id),
        attachments=_map_attachments(payload.get("attachments")),
    )


def extract_forwarded_payload(
    message: Mapping[str, object],
) -> Mapping[str, object] | None:
    """First forwarded message of a DM, if any; nested forwards are never expanded."""
    forwarded = message.get("fwd_messages")
    if not isinstance(forwarded, list) or not forwarded:
        return None
    first = forwarded[0]
    return first if isinstance(first, Mapping) else None


def map_manual_source(
    *,
    message: Mapping[str, object],
    fwd: Mapping[str, object] | None,
    author: Author,
    initiator_id: int,
) -> SourceMessage | None:
    """Manual DM -> SourceMessage: forwarded content when present, else the DM itself.

    The source key stays bound to the DM so one manual action equals one delivery
    attempt; content text/attachments come from the forwarded message because a
    forward carries no own text.
    """
    cmid = _optional_int(message, "conversation_message_id")
    peer_id = _optional_int(message, "peer_id")
    if cmid is None or peer_id is None:
        return None
    content = fwd if fwd is not None else message
    raw_text = content.get("text")
    return SourceMessage(
        source_type=SourceType.VK_MESSAGE,
        source_key=f"manual:{initiator_id}:{cmid}",
        group_id=0,
        peer_id=peer_id,
        conversation_message_id=cmid,
        author=author,
        text=raw_text if isinstance(raw_text, str) else "",
        has_all=False,
        has_hashtag=False,
        attachments=_map_attachments(content.get("attachments")),
    )


class FirstPeerGuard:
    """One-chat topology guard: bind the first observed ``peer_id``, never replace it.

    Process-local only (plan D15): it defends against a second peer inside one run,
    it is not a persisted source policy.
    """

    def __init__(self) -> None:
        self._peer_id: int | None = None

    def bind(self, peer_id: int) -> bool:
        if self._peer_id is None:
            self._peer_id = peer_id
            return True
        return self._peer_id == peer_id

    def current(self) -> int | None:
        return self._peer_id

    def reset(self) -> None:
        self._peer_id = None
