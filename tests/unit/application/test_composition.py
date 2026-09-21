"""Unit tests for publication composition: manual links, warnings, walls, splitting."""

import html

import pytest

from vk_topic_bridge.application.forwarding.composition import (
    WALL_TAG,
    MediaFailureReason,
    append_media_warnings,
    compose_manual_publication,
    compose_wall_publication,
    media_failure_warning,
    media_link_warning,
    split_text_safely,
)
from vk_topic_bridge.domain.enums import AttachmentKind, SourceType
from vk_topic_bridge.domain.value_objects import Author, Destination, SourceMessage
from vk_topic_bridge.domain.wall_post import SourceWallPost

AUTHOR = Author(user_id=11, first_name="Иван", last_name="Иванов", screen_name="ivan")
INITIATOR = Author(user_id=22, first_name="Пётр", last_name="Петров", screen_name=None)
DESTINATION = Destination(chat_id=-100500, message_thread_id=7)


def _source(text: str = "привет <script>") -> SourceMessage:
    return SourceMessage(
        source_type=SourceType.VK_MESSAGE,
        source_key="1:2:3",
        group_id=1,
        peer_id=2,
        conversation_message_id=3,
        author=AUTHOR,
        text=text,
        has_all=False,
        has_hashtag=False,
        attachments=(),
    )


def _wall_post(text: str = "текст стены") -> SourceWallPost:
    return SourceWallPost(
        source_type=SourceType.VK_WALL,
        source_key="1:-1:5",
        group_id=1,
        owner_id=-1,
        post_id=5,
        author=AUTHOR,
        text=text,
        url="https://vk.com/wall-1_5",
        attachments=(),
    )


def test_manual_has_two_distinct_links() -> None:
    publication = compose_manual_publication(_source(), INITIATOR, DESTINATION)

    assert publication.html_text.count("<a href=") == 2
    assert "https://vk.com/id11" in publication.html_text
    assert "https://vk.com/id22" in publication.html_text
    assert ">Автор пересылки</a>" in publication.html_text
    assert publication.html_text.index("https://vk.com/id11") < publication.html_text.index(
        "https://vk.com/id22"
    )


def test_manual_uses_visible_initiator_label_when_name_is_unavailable() -> None:
    initiator = Author(user_id=22, first_name="", last_name="", screen_name=None)
    publication = compose_manual_publication(_source(), initiator, DESTINATION)

    assert '<a href="https://vk.com/id22">Автор пересылки</a>' in publication.html_text


def test_manual_escapes_vk_text_and_names() -> None:
    publication = compose_manual_publication(_source(), INITIATOR, DESTINATION)

    assert "<script>" not in publication.html_text
    assert html.escape("привет <script>") in publication.html_text


def test_manual_has_no_automatic_tags() -> None:
    publication = compose_manual_publication(_source(), INITIATOR, DESTINATION)

    assert "#извк" not in publication.html_text


def test_manual_carries_destination() -> None:
    publication = compose_manual_publication(_source(), INITIATOR, DESTINATION)

    assert publication.chat_id == DESTINATION.chat_id
    assert publication.message_thread_id == DESTINATION.message_thread_id


def test_wall_always_contains_link_and_tag() -> None:
    publication = compose_wall_publication(_wall_post(text=""), DESTINATION)

    assert "https://vk.com/wall-1_5" in publication.html_text
    assert WALL_TAG in publication.html_text


def test_wall_escapes_text() -> None:
    publication = compose_wall_publication(_wall_post(text="<b>жирный</b>"), DESTINATION)

    assert "<b>жирный</b>" not in publication.html_text
    assert html.escape("<b>жирный</b>") in publication.html_text


def test_append_media_warnings_keeps_every_warning_on_its_own_line() -> None:
    result = append_media_warnings("текст", ["первое", "второе"])

    lines = result.splitlines()
    assert "текст" in lines
    assert "первое" in lines
    assert "второе" in lines
    assert lines.index("первое") + 1 == lines.index("второе")


def test_append_media_warnings_escapes_each_warning() -> None:
    result = append_media_warnings("текст", ["<script>"])

    assert "<script>" not in result
    assert html.escape("<script>") in result


def test_append_media_warnings_empty_returns_original() -> None:
    assert append_media_warnings("текст", []) == "текст"


def test_append_media_warnings_renders_video_link_as_safe_anchor() -> None:
    warning = media_link_warning(
        "clip",
        'https://vk.com/video-1_22?param="quoted"&view=full',
    )

    result = append_media_warnings("текст", [warning])

    assert (
        "Видео «clip» не удалось скачать. "
        '<a href="https://vk.com/video-1_22?param=&quot;quoted&quot;&amp;view=full">'
        "Открыть видео в VK</a>"
    ) in result


def test_media_failure_warning_names_kind_and_reason() -> None:
    warning = media_failure_warning(
        AttachmentKind.VIDEO, "clip.mp4", MediaFailureReason.UNAVAILABLE
    )

    assert "clip.mp4" in warning
    assert "Видео" in warning
    assert "недоступно" in warning


def test_media_failure_warning_without_name() -> None:
    warning = media_failure_warning(
        AttachmentKind.DOCUMENT, None, MediaFailureReason.DOWNLOAD_FAILED
    )

    assert "без имени" not in warning
    assert "Документ" in warning
    assert "не удалось скачать" in warning


def test_media_failure_warning_oversize_reason() -> None:
    warning = media_failure_warning(
        AttachmentKind.DOCUMENT, "big.zip", MediaFailureReason.TOO_LARGE
    )

    assert "50 МБ" in warning


@pytest.mark.parametrize(
    "text",
    [
        "а" * 10,  # noqa: RUF001
        "а" * 4096,  # noqa: RUF001
        "а" * 4097,  # noqa: RUF001
        "а" * 12000,  # noqa: RUF001
    ],
)
def test_split_text_safely_preserves_text_exactly(text: str) -> None:
    chunks = split_text_safely(text, 4096)

    assert "".join(chunks) == text
    assert all(len(chunk) <= 4096 for chunk in chunks)


def test_split_text_respects_html_entities() -> None:
    text = ("а" * 4089) + "&#39;" + ("б" * 10)  # noqa: RUF001

    chunks = split_text_safely(text, 4096)

    assert "".join(chunks) == text
    assert all("&#39;" in chunk or "&#39;" not in text for chunk in chunks[:1])


def test_split_text_never_cuts_inside_entity() -> None:
    text = ("х" * 4093) + "&#39;" + "у"  # noqa: RUF001

    chunks = split_text_safely(text, 4096)

    assert "".join(chunks) == text
    assert not any(chunk.endswith("&#") or chunk.endswith("&#3") for chunk in chunks)


def test_split_text_never_cuts_inside_tag() -> None:
    link = '<a href="https://vk.com/id11">Иван</a>'
    text = ("т" * 4085) + link

    chunks = split_text_safely(text, 4096)

    assert "".join(chunks) == text
    for chunk in chunks[:-1]:
        assert chunk.count("<") == chunk.count(">")


def test_split_text_short_text_is_single_chunk() -> None:
    assert split_text_safely("коротко", 4096) == ("коротко",)
