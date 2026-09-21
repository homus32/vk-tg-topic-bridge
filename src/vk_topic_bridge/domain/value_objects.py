"""Immutable, SDK-neutral domain value objects."""

from dataclasses import dataclass

from vk_topic_bridge.domain.enums import AttachmentKind, SourceType

type PublicationSource = SourceMessage | SourceWallPost


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
class MediaVariant:
    """SDK-neutral downloadable variant exposed by a VK attachment."""

    url: str
    quality: str | None = None
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True, slots=True)
class Attachment:
    """Attachment-neutral metadata; no download logic lives in this layer."""

    kind: AttachmentKind
    file_name: str | None
    size_bytes: int | None
    source_ref: str | None
    owner_id: int | None = None
    media_id: int | None = None
    access_key: str | None = None
    direct_url: str | None = None
    link_url: str | None = None
    variants: tuple[MediaVariant, ...] = ()


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
class SourceWallPost:
    """Normalized ``wall_post_new`` event after attachment mapping.

    TODO(finish): constructed by the wall normalizer in ``infrastructure/vk/mapper.py``
    from the raw payload; ``text`` is the raw VK text (unescaped); ``author`` is the
    resolved profile of ``from_id``/community when resolvable, otherwise a zero-id
    placeholder author with empty names (wall posts may be community-authored).
    ``url`` comes from ``wall_post_url(owner_id, post_id)`` (domain/wall_post.py).
    """

    source_type: SourceType
    source_key: str
    group_id: int
    owner_id: int
    post_id: int
    author: Author
    text: str
    url: str
    attachments: tuple[Attachment, ...]


@dataclass(frozen=True, slots=True)
class Publication:
    """Composed Telegram publication ready for the Bot API publisher.

    ``source`` is the normalized origin of this publication: a ``SourceMessage`` for
    message flows or a ``SourceWallPost`` for wall flows (the wall post keeps its own
    identity and is never forced into the message-only union).
    """

    chat_id: int
    message_thread_id: int | None
    html_text: str
    has_all: bool
    source: PublicationSource


@dataclass(frozen=True, slots=True)
class PublicationResult:
    """Confirmed Bot API result."""

    chat_id: int
    message_thread_id: int | None
    message_ids: tuple[int, ...]
