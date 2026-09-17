"""Immutable, SDK-neutral domain value objects."""

from dataclasses import dataclass

from vk_topic_bridge.domain.enums import AttachmentKind, SourceType


@dataclass(frozen=True, slots=True)
class Author:
    """VK message author; numeric ``user_id`` is the identity."""

    user_id: int
    first_name: str
    last_name: str
    screen_name: str | None

    @property
    def display_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def profile_url(self) -> str:
        # screen_name is mutable, so the stable numeric id is the only identity in links.
        return f"https://vk.com/id{self.user_id}"


@dataclass(frozen=True, slots=True)
class Attachment:
    """Attachment-neutral metadata; no download logic lives in this layer."""

    kind: AttachmentKind
    file_name: str | None
    size_bytes: int | None
    source_ref: str | None


@dataclass(frozen=True, slots=True)
class SourceMessage:
    """Normalized incoming event after cropped-message completion."""

    source_type: SourceType
    source_key: str
    group_id: int
    peer_id: int
    conversation_message_id: int
    author: Author
    text: str
    has_all: bool
    has_hashtag: bool
    attachments: tuple[Attachment, ...]


@dataclass(frozen=True, slots=True)
class Destination:
    """Telegram routing target; ``message_thread_id=None`` means the General topic."""

    chat_id: int
    message_thread_id: int | None


@dataclass(frozen=True, slots=True)
class ChatCapabilities:
    """Rights of the bot inside the registered chat."""

    can_send_text: bool
    can_send_photo: bool
    can_send_video: bool
    can_send_document: bool
    missing: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TopicInfo:
    """Forum topic as seen by Telethon; ``topic_id=None`` for the General topic."""

    topic_id: int | None
    title: str
    is_general: bool
    is_closed: bool
    is_hidden: bool


@dataclass(frozen=True, slots=True)
class Publication:
    """Composed Telegram publication ready for the Bot API publisher."""

    chat_id: int
    message_thread_id: int | None
    html_text: str
    has_all: bool
    source: SourceMessage


@dataclass(frozen=True, slots=True)
class PublicationResult:
    """Confirmed Bot API result."""

    chat_id: int
    message_thread_id: int | None
    message_ids: tuple[int, ...]
