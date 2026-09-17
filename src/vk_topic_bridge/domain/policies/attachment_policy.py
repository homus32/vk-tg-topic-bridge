"""Attachment policy: the 50 MB product limit and skip warning text."""

from vk_topic_bridge.domain.enums import AttachmentKind
from vk_topic_bridge.domain.value_objects import Attachment

MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024

_KIND_BY_SOURCE_TYPE = {
    "photo": AttachmentKind.PHOTO,
    "video": AttachmentKind.VIDEO,
    "doc": AttachmentKind.DOCUMENT,
}


def is_within_size_limit(size_bytes: int | None) -> bool:
    return size_bytes is None or size_bytes <= MAX_ATTACHMENT_BYTES


def classify_attachment_type(raw_type: str) -> AttachmentKind:
    return _KIND_BY_SOURCE_TYPE.get(raw_type, AttachmentKind.UNSUPPORTED)


def attachment_warning(attachment: Attachment) -> str | None:
    """Warning item for a skipped attachment; never raises, the publication continues."""
    name = attachment.file_name or "без имени"
    if attachment.kind is AttachmentKind.UNSUPPORTED:
        return f"Вложение «{name}» не поддерживается и пропущено."
    if not is_within_size_limit(attachment.size_bytes):
        return f"Вложение «{name}» превышает лимит 50 МБ и пропущено."
    return None
