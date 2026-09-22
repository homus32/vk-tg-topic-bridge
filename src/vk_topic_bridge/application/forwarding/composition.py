"""Publication composition for manual forwarding, wall posts and media warnings.

Pure application-layer HTML composition: no SDK imports, no I/O. Every dynamic value
coming from VK (original text, author names, initiator, wall url, file names, warning
text) is escaped exactly once here; downstream layers treat the composed text as
pre-escaped HTML.
"""

from __future__ import annotations

import html
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from vk_topic_bridge.domain.enums import AttachmentKind
from vk_topic_bridge.domain.value_objects import (
    Author,
    Destination,
    Publication,
    SourceMessage,
)
from vk_topic_bridge.domain.wall_post import SourceWallPost

WALL_TAG = "#изстенывк"
MANUAL_TAG = "#извк"
_SERVICE_TAG_RE = re.compile(r"(?<!\w)#извк(?!\w)", re.IGNORECASE)

_KIND_LABELS = {
    AttachmentKind.PHOTO: "Фото",
    AttachmentKind.VIDEO: "Видео",
    AttachmentKind.DOCUMENT: "Документ",
}
_FALLBACK_KIND_LABEL = "Вложение"


@dataclass(frozen=True, slots=True)
class MediaLinkWarning:
    text: str
    link_url: str


type MediaWarning = str | MediaLinkWarning


class MediaFailureReason(StrEnum):
    """Why one attachment never became a media operation (warning text only)."""

    UNAVAILABLE = "unavailable"
    DOWNLOAD_FAILED = "download_failed"
    TOO_LARGE = "too_large"
    UNSUPPORTED = "unsupported"


_REASON_TEXTS = {
    MediaFailureReason.UNAVAILABLE: "недоступно. Остальная публикация отправлена",
    MediaFailureReason.DOWNLOAD_FAILED: "не удалось перенести. Остальная публикация отправлена",
    MediaFailureReason.TOO_LARGE: "превышает лимит 50 МБ. Остальная публикация отправлена",
    MediaFailureReason.UNSUPPORTED: "не поддерживается. Остальная публикация отправлена",
}


def _profile_link(author: Author, *, label: str | None = None) -> str:
    text = author.display_name if label is None else label
    return f'<a href="{author.profile_url}">{html.escape(text)}</a>'


def compose_manual_publication(
    source: SourceMessage,
    initiator: Author,
    destination: Destination,
) -> Publication:
    """Manual publication: original author link, text, service tag, initiator link.

    Both profile links are distinct clickable ``<a>`` links built from the stable
    numeric id; the VK text is escaped; no reply context and no nested forward
    expansion (the source is already a single message object). The manual service tag is
    separate from the source text and is not expanded to ``#извкважно``.
    """
    manual_tag = "" if _SERVICE_TAG_RE.search(source.text) else MANUAL_TAG
    html_text = (
        f"{_profile_link(source.author)}\n\n"
        f"{html.escape(source.text)}\n\n{manual_tag}\n\n"
        f"{_profile_link(initiator, label='Автор пересылки')}"
    )
    return Publication(
        chat_id=destination.chat_id,
        message_thread_id=destination.message_thread_id,
        html_text=html_text,
        has_all=False,
        source=source,
    )


def compose_wall_publication(
    wall_post: SourceWallPost,
    destination: Destination,
) -> Publication:
    """Wall publication: escaped text, mandatory original post link, ``#изстенывк``.

    The original post url is always present (AC-14.4), even when the wall post carries
    no text; ``has_all`` is always ``False`` because wall forwarding does not use the
    @all/hashtag filter.
    """
    link = f'<a href="{wall_post.url}">{HTML_ESCAPED_WALL_LINK_TEXT}</a>'
    html_text = f"{html.escape(wall_post.text)}\n\n{link}\n\n{WALL_TAG}"
    return Publication(
        chat_id=destination.chat_id,
        message_thread_id=destination.message_thread_id,
        html_text=html_text,
        has_all=False,
        source=wall_post,
    )


HTML_ESCAPED_WALL_LINK_TEXT = "Оригинал поста"


def append_media_warnings(html_text: str, warnings: Sequence[MediaWarning]) -> str:
    """Append escaped warning lines and safe media links to a composed publication.

    Every warning becomes its own line (US-12.3 — warnings must not be collapsed) and
    ordinary text is escaped here exactly once; an empty warning list returns the text
    unchanged.
    """
    if not warnings:
        return html_text
    escaped = "\n".join(_render_media_warning(warning) for warning in warnings)
    return f"{html_text}\n{escaped}"


def prepend_general_fallback_warning(html_text: str, *, topic_label: str) -> str:
    return (
        f"⚠️ Топик «{html.escape(topic_label)}» недоступен.\n"
        "Публикация отправлена в General.\n\n"
        f"{html_text}"
    )


def _render_media_warning(warning: MediaWarning) -> str:
    if isinstance(warning, MediaLinkWarning):
        return (
            f'{html.escape(warning.text)} <a href="{html.escape(warning.link_url, quote=True)}">'
            "Открыть видео в VK</a>"
        )
    return html.escape(warning)


def media_failure_warning(
    kind: AttachmentKind,
    file_name: str | None,
    reason: MediaFailureReason,
) -> str:
    """Plain-text warning for an attachment that never reached the publisher.

    Downloads happen before planning, so a failed/unavailable/oversized attachment is
    represented ONLY as this warning line (docs/03 §12.4/§12.5) — never an
    ``OperationOutcome``. The text is plain; ``append_media_warnings`` escapes it.
    """
    label = _KIND_LABELS.get(kind, _FALLBACK_KIND_LABEL)
    if file_name:
        return f"⚠️ {label} «{file_name}» {_REASON_TEXTS[reason]}."
    return f"⚠️ {label} {_REASON_TEXTS[reason]}."


def media_link_warning(file_name: str | None, link_url: str) -> MediaLinkWarning:
    if file_name:
        return MediaLinkWarning(f"🎬 Видео «{file_name}» доступно по ссылке:", link_url)
    return MediaLinkWarning("🎬 Видео доступно по ссылке:", link_url)


def _unsafe_boundaries(text: str, length: int) -> bytearray:
    """Mark boundary positions that fall strictly inside an HTML tag or entity."""
    unsafe = bytearray(length + 1)
    index = 0
    while index < length:
        char = text[index]
        if char == "<":
            end = text.find(">", index)
            if end != -1:
                for position in range(index + 1, end + 1):
                    unsafe[position] = 1
                index = end + 1
                continue
        elif char == "&":
            end = text.find(";", index)
            if end != -1 and end - index <= 12:
                for position in range(index + 1, end + 1):
                    unsafe[position] = 1
                index = end + 1
                continue
        index += 1
    return unsafe


def split_text_safely(text: str, limit: int) -> tuple[str, ...]:
    """Split the composed HTML into chunks of at most ``limit`` characters.

    Boundaries never cut inside an HTML tag or entity (``&#39;`` stays whole);
    whitespace boundaries are preferred, otherwise the last position outside a tag or
    entity is used. Concatenating the chunks reproduces the original text exactly.
    """
    if limit <= 0:
        msg = "limit must be positive"
        raise ValueError(msg)
    if len(text) <= limit:
        return (text,)

    length = len(text)
    unsafe = _unsafe_boundaries(text, length)
    chunks: list[str] = []
    start = 0
    while start < length:
        if length - start <= limit:
            chunks.append(text[start:])
            break
        hard = start + limit
        cut = next(
            (
                position
                for position in range(hard, start, -1)
                if not unsafe[position] and text[position - 1].isspace()
            ),
            None,
        )
        if cut is None:
            cut = next(
                (position for position in range(hard, start, -1) if not unsafe[position]),
                None,
            )
        if cut is None or cut <= start:
            cut = hard
        chunks.append(text[start:cut])
        start = cut
    return tuple(chunks)
