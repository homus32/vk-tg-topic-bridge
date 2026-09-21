"""Planner contract tests: caption/TEXT branches, grouping, limits, ordering.

Pure tests: the planner performs no I/O and produces immutable operations.
"""

from __future__ import annotations

from vk_topic_bridge.application.forwarding.publication_planning import plan_publication
from vk_topic_bridge.domain.enums import SourceType
from vk_topic_bridge.domain.publication import OperationKind, PlannedMedia
from vk_topic_bridge.domain.value_objects import Author, Publication, SourceMessage

CHAT_ID = -1001234567890
THREAD_ID = 7

PHOTO = OperationKind.PHOTO
VIDEO = OperationKind.VIDEO
DOCUMENT = OperationKind.DOCUMENT
TEXT = OperationKind.TEXT
MEDIA_GROUP = OperationKind.MEDIA_GROUP


def _source() -> SourceMessage:
    return SourceMessage(
        source_type=SourceType.VK_MESSAGE,
        source_key="42:2000000001:17",
        group_id=42,
        peer_id=2000000001,
        conversation_message_id=17,
        author=Author(user_id=1, first_name="Иван", last_name="Петров", screen_name="ivan"),
        text="привет",
        has_all=False,
        has_hashtag=False,
        attachments=(),
    )


def _publication(text: str, thread: int | None = THREAD_ID) -> Publication:
    return Publication(
        chat_id=CHAT_ID,
        message_thread_id=thread,
        html_text=text,
        has_all=False,
        source=_source(),
    )


def _media(kind: OperationKind, index: int) -> PlannedMedia:
    return PlannedMedia(kind=kind, file_path=f"/tmp/planned-{index}.bin", file_name=f"f{index}.bin")


def _photos(count: int) -> list[PlannedMedia]:
    return [_media(PHOTO, index) for index in range(count)]


def _kinds(plan_operations: list[OperationKind]) -> list[OperationKind]:
    return list(plan_operations)


# --- caption branch -----------------------------------------------------------


def test_short_text_with_media_becomes_caption_of_first_media_operation() -> None:
    text = "x" * 500
    plan = plan_publication(_publication(text), _photos(3))

    assert [op.kind for op in plan.operations] == [MEDIA_GROUP]
    assert plan.operations[0].text == text
    assert len(plan.operations[0].media) == 3


def test_short_text_with_single_media_becomes_its_caption() -> None:
    text = "x" * 500
    plan = plan_publication(_publication(text), _photos(1))

    assert [op.kind for op in plan.operations] == [PHOTO]
    assert plan.operations[0].text == text


def test_short_text_with_document_becomes_document_caption() -> None:
    text = "x" * 500
    plan = plan_publication(_publication(text), [_media(DOCUMENT, 0)])

    assert [op.kind for op in plan.operations] == [DOCUMENT]
    assert plan.operations[0].text == text


def test_text_exactly_at_caption_limit_uses_caption_branch() -> None:
    text = "x" * 1024
    plan = plan_publication(_publication(text), _photos(2))

    assert [op.kind for op in plan.operations] == [MEDIA_GROUP]
    assert plan.operations[0].text == text


def test_text_just_over_caption_limit_uses_text_branch() -> None:
    text = "x" * 1025
    plan = plan_publication(_publication(text), _photos(2))

    assert [op.kind for op in plan.operations] == [TEXT, MEDIA_GROUP]
    assert plan.operations[0].text == "x" * 1025
    assert plan.operations[1].text is None


# --- TEXT branch ----------------------------------------------------------------


def test_medium_text_with_media_is_not_truncated_to_caption() -> None:
    text = "x" * 2000
    plan = plan_publication(_publication(text), _photos(2))

    assert [op.kind for op in plan.operations] == [TEXT, MEDIA_GROUP]
    assert plan.operations[0].text == text
    assert plan.operations[1].text is None
    assert len(plan.operations[1].media) == 2


def test_text_without_media_is_a_text_operation() -> None:
    text = "x" * 500
    plan = plan_publication(_publication(text), ())

    assert [op.kind for op in plan.operations] == [TEXT]
    assert plan.operations[0].text == text


def test_long_text_splits_into_bounded_text_operations() -> None:
    text = "слово " * 2000
    plan = plan_publication(_publication(text), ())

    assert all(op.kind is TEXT for op in plan.operations)
    assert len(plan.operations) > 1
    for op in plan.operations:
        assert op.text is not None
        assert len(op.text) <= 4096
    assert "".join(op.text or "" for op in plan.operations) == text


def test_text_split_respects_html_entities() -> None:
    entity = "&#x27;"
    text = "x" * 4092 + entity + "y" * 20
    plan = plan_publication(_publication(text), ())

    chunks = [op.text or "" for op in plan.operations]
    assert "".join(chunks) == text
    for chunk in chunks[:-1]:
        assert not chunk.endswith(("&", "&#", "&#x", "&#x2", "&#x27"))


def test_text_split_prefers_newline_boundaries() -> None:
    text = "строка\n" * 800
    plan = plan_publication(_publication(text), ())

    for op in plan.operations[:-1]:
        assert op.text is not None
        assert len(op.text) <= 4096


# --- grouping -------------------------------------------------------------------


def test_single_tail_after_group_becomes_single_photo_operation() -> None:
    plan = plan_publication(_publication("t"), _photos(11))

    assert [op.kind for op in plan.operations] == [MEDIA_GROUP, PHOTO]
    assert len(plan.operations[0].media) == 10
    assert len(plan.operations[1].media) == 1


def test_twelve_photos_yield_two_valid_groups() -> None:
    plan = plan_publication(_publication(""), _photos(12))

    assert [op.kind for op in plan.operations] == [MEDIA_GROUP, MEDIA_GROUP]
    assert [len(op.media) for op in plan.operations] == [10, 2]


def test_photos_and_videos_mix_in_one_group() -> None:
    media = [
        _media(PHOTO, 0),
        _media(VIDEO, 1),
        _media(PHOTO, 2),
        _media(VIDEO, 3),
    ]
    plan = plan_publication(_publication(""), media)

    assert [op.kind for op in plan.operations] == [MEDIA_GROUP]
    assert [item.kind for item in plan.operations[0].media] == [PHOTO, VIDEO, PHOTO, VIDEO]


def test_documents_are_never_grouped() -> None:
    media = [_media(DOCUMENT, index) for index in range(3)]
    plan = plan_publication(_publication(""), media)

    assert [op.kind for op in plan.operations] == [DOCUMENT, DOCUMENT, DOCUMENT]
    assert all(len(op.media) == 1 for op in plan.operations)


def test_document_breaks_a_media_run() -> None:
    media = [
        _media(PHOTO, 0),
        _media(PHOTO, 1),
        _media(DOCUMENT, 2),
        _media(PHOTO, 3),
    ]
    plan = plan_publication(_publication(""), media)

    assert [op.kind for op in plan.operations] == [MEDIA_GROUP, DOCUMENT, PHOTO]
    assert len(plan.operations[0].media) == 2


def test_photo_and_document_use_separate_bot_api_operations() -> None:
    plan = plan_publication(_publication(""), [_media(PHOTO, 0), _media(DOCUMENT, 1)])

    assert [op.kind for op in plan.operations] == [PHOTO, DOCUMENT]
    assert all(len(op.media) == 1 for op in plan.operations)


def test_single_video_uses_video_operation() -> None:
    plan = plan_publication(_publication(""), [_media(VIDEO, 0)])

    assert [op.kind for op in plan.operations] == [VIDEO]


# --- ordering and edges ----------------------------------------------------------


def test_positions_are_zero_based_and_sequential() -> None:
    media = [
        _media(PHOTO, 0),
        _media(PHOTO, 1),
        _media(DOCUMENT, 2),
        _media(VIDEO, 3),
        _media(VIDEO, 4),
    ]
    plan = plan_publication(_publication("x" * 5000), media)

    assert [op.position for op in plan.operations] == list(range(len(plan.operations)))
    assert [op.kind for op in plan.operations] == [TEXT, TEXT, MEDIA_GROUP, DOCUMENT, MEDIA_GROUP]


def test_media_only_publication_has_no_text_operations() -> None:
    plan = plan_publication(_publication(""), _photos(2))

    assert [op.kind for op in plan.operations] == [MEDIA_GROUP]
    assert plan.operations[0].text is None


def test_empty_publication_yields_no_operations() -> None:
    plan = plan_publication(_publication(""), ())

    assert plan.operations == ()


def test_plan_base_is_the_original_publication() -> None:
    publication = _publication("t")
    plan = plan_publication(publication, _photos(1))

    assert plan.base is publication
