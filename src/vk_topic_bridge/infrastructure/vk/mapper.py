"""Pure VK Long Poll event normalization into domain value objects (plan §9).

No SDK types cross this boundary: the presentation layer hands raw ``Mapping``
payloads in and receives ``SourceMessage``/``Author`` back.
"""

from collections.abc import Mapping

from vk_topic_bridge.domain.enums import SourceType
from vk_topic_bridge.domain.policies.attachment_policy import classify_attachment_type
from vk_topic_bridge.domain.policies.forwarding_policy import decide, source_key
from vk_topic_bridge.domain.value_objects import Attachment, Author, SourceMessage

_MISSING = object()


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


def _optional_int(message: Mapping[str, object], field: str) -> int | None:
    value = message.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


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
    if isinstance(payload, Mapping):
        file_name = _optional_str(payload, "title")
        size_bytes = _optional_int(payload, "size")
        owner_id = _optional_int(payload, "owner_id")
        media_id = _optional_int(payload, "id")
        if owner_id is not None and media_id is not None:
            source_ref = f"{owner_id}_{media_id}"
    return Attachment(
        kind=classify_attachment_type(raw_type),
        file_name=file_name,
        size_bytes=size_bytes,
        source_ref=source_ref,
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
