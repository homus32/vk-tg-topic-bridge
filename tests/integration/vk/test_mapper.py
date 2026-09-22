"""Mapper tests for VK event normalization (plan §9, docs 03 §10, docs 05 §14).

The production module is imported lazily so that, during the RED phase, its absence
surfaces as a normal test failure instead of aborting collection of the suite.
"""

import importlib
from types import ModuleType

import pytest

from vk_topic_bridge.domain.enums import AttachmentKind
from vk_topic_bridge.domain.value_objects import Author

GROUP_ID = 42
PEER_ID = 2000000001
CMID = 789


def _mapper() -> ModuleType:
    return importlib.import_module("vk_topic_bridge.infrastructure.vk.mapper")


def _author() -> Author:
    return Author(user_id=123, first_name="Иван", last_name="Иванов", screen_name="ivan")


def _message(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": 456,
        "date": 1700000000,
        "from_id": 123,
        "peer_id": PEER_ID,
        "conversation_message_id": CMID,
        "text": "@all #извк",
        "attachments": [],
        "fwd_messages": [],
        "reply_message": None,
        "is_cropped": 0,
    }
    base.update(overrides)
    return base


def test_maps_object_payload_fields() -> None:
    mapper = _mapper()
    source = mapper.map_message(group_id=GROUP_ID, message=_message(), author=_author())

    assert source.source_key == f"{GROUP_ID}:{PEER_ID}:{CMID}"
    assert source.has_all is True
    assert source.has_hashtag is True
    assert source.group_id == GROUP_ID
    assert source.peer_id == PEER_ID
    assert source.conversation_message_id == CMID
    assert source.author.display_name == "Иван Иванов"
    assert source.author.profile_url == "https://vk.com/id123"


def test_source_key_ignores_message_id_and_ts() -> None:
    mapper = _mapper()
    message = _message(id=456, ts=999999)
    source = mapper.map_message(group_id=GROUP_ID, message=message, author=_author())

    assert source.source_key == f"{GROUP_ID}:{PEER_ID}:{CMID}"
    assert "456" not in source.source_key
    assert "999999" not in source.source_key


def test_preserves_cyrillic_text() -> None:
    mapper = _mapper()
    text = "Привет, мир! #новости @all — ёжик"
    source = mapper.map_message(group_id=GROUP_ID, message=_message(text=text), author=_author())

    assert source.text == text
    assert source.has_all is True
    assert source.has_hashtag is True


def test_missing_optional_fields_are_tolerated() -> None:
    mapper = _mapper()
    message: dict[str, object] = {"peer_id": PEER_ID, "conversation_message_id": CMID}
    source = mapper.map_message(group_id=GROUP_ID, message=message, author=_author())

    assert source.text == ""
    assert source.has_all is False
    assert source.has_hashtag is False
    assert source.attachments == ()


def test_null_text_becomes_empty_string() -> None:
    mapper = _mapper()
    source = mapper.map_message(group_id=GROUP_ID, message=_message(text=None), author=_author())

    assert source.text == ""


def test_missing_peer_id_raises_value_error() -> None:
    mapper = _mapper()
    message: dict[str, object] = {"conversation_message_id": CMID}
    with pytest.raises(ValueError, match="peer_id"):
        mapper.map_message(group_id=GROUP_ID, message=message, author=_author())


def test_missing_conversation_message_id_raises_value_error() -> None:
    mapper = _mapper()
    message: dict[str, object] = {"peer_id": PEER_ID}
    with pytest.raises(ValueError, match="conversation_message_id"):
        mapper.map_message(group_id=GROUP_ID, message=message, author=_author())


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1, True),
        (True, True),
        (0, False),
        (False, False),
        (None, False),
    ],
)
def test_is_cropped_detection(value: object, expected: bool) -> None:
    mapper = _mapper()
    assert mapper.is_cropped({"is_cropped": value}) is expected


def test_is_cropped_absent_is_false() -> None:
    mapper = _mapper()
    assert mapper.is_cropped({}) is False


def test_attachments_are_classified(caplog: pytest.LogCaptureFixture) -> None:
    mapper = _mapper()
    message = _message(
        attachments=[
            {
                "type": "photo",
                "photo": {
                    "id": 11,
                    "owner_id": -1,
                    "access_key": "photo-key",
                    "sizes": [
                        {
                            "type": "s",
                            "url": "https://vk.example/s.jpg",
                            "width": 100,
                            "height": 80,
                        },
                        {
                            "type": "w",
                            "url": "https://vk.example/w.jpg",
                            "width": 1920,
                            "height": 1080,
                        },
                    ],
                },
            },
            {
                "type": "video",
                "video": {
                    "id": 22,
                    "owner_id": -1,
                    "title": "clip",
                    "size": 10,
                    "files": {"mp4_720": "https://vk.example/v720.mp4"},
                },
            },
            {
                "type": "doc",
                "doc": {
                    "id": 33,
                    "owner_id": -1,
                    "access_key": "doc-key",
                    "title": "file.pdf",
                    "size": 2048,
                    "url": "https://vk.example/file.pdf",
                },
            },
            {"type": "sticker", "sticker": {"id": 44}},
        ]
    )
    with caplog.at_level("DEBUG"):
        source = mapper.map_message(group_id=GROUP_ID, message=message, author=_author())

    assert [attachment.kind for attachment in source.attachments] == [
        AttachmentKind.PHOTO,
        AttachmentKind.VIDEO,
        AttachmentKind.DOCUMENT,
        AttachmentKind.UNSUPPORTED,
    ]
    photo = source.attachments[0]
    assert photo.source_ref == "-1_11_photo-key"
    assert photo.owner_id == -1
    assert photo.media_id == 11
    assert photo.access_key == "photo-key"
    assert [variant.url for variant in photo.variants] == [
        "https://vk.example/s.jpg",
        "https://vk.example/w.jpg",
    ]
    video = source.attachments[1]
    assert video.file_name == "clip"
    assert video.size_bytes == 10
    assert video.link_url == "https://vk.com/video-1_22"
    assert video.variants[0].quality == "mp4_720"
    document = source.attachments[2]
    assert document.file_name == "file.pdf"
    assert document.size_bytes == 2048
    assert document.source_ref == "-1_33_doc-key"
    assert document.direct_url == "https://vk.example/file.pdf"
    assert source.attachments[3].file_name is None
    assert source.attachments[3].size_bytes is None
    assert "photo-key" not in caplog.text
    assert "doc-key" not in caplog.text
    assert any(getattr(record, "access_key_present", False) for record in caplog.records)


def test_wall_attachment_is_dropped_from_message_attachments() -> None:
    mapper = _mapper()
    message = _message(
        attachments=[
            {"type": "wall", "wall": {"owner_id": -1, "id": 77, "access_key": "key"}},
            {
                "type": "photo",
                "photo": {"owner_id": -1, "id": 11, "access_key": "photo-key"},
            },
        ]
    )
    source = mapper.map_message(group_id=GROUP_ID, message=message, author=_author())

    assert [attachment.kind for attachment in source.attachments] == [AttachmentKind.PHOTO]
    assert source.wall_link is None
    assert source.wall_post is None


def test_wall_reference_is_extracted_from_outer_attachment() -> None:
    mapper = _mapper()
    message = _message(
        attachments=[{"type": "wall", "wall": {"owner_id": -1, "id": 77, "access_key": "k"}}]
    )

    assert mapper.extract_wall_reference(message) == (-1, 77)
    assert mapper.extract_wall_reference(_message()) is None


def test_wall_reference_ignores_forwarded_wall_attachments() -> None:
    mapper = _mapper()
    message = _message(
        fwd_messages=[{"text": "forward", "attachments": [{"type": "wall", "wall": {}}]}]
    )

    assert mapper.extract_wall_reference(message) is None


def test_non_list_attachments_are_ignored() -> None:
    mapper = _mapper()
    source = mapper.map_message(
        group_id=GROUP_ID, message=_message(attachments=None), author=_author()
    )

    assert source.attachments == ()


def test_video_player_link_is_preserved() -> None:
    mapper = _mapper()
    source = mapper.map_message(
        group_id=GROUP_ID,
        message=_message(
            attachments=[
                {
                    "type": "video",
                    "video": {
                        "id": 22,
                        "owner_id": -1,
                        "player": "https://vk.example/player",
                    },
                }
            ]
        ),
        author=_author(),
    )

    assert source.attachments[0].link_url == "https://vk.example/player"


def test_first_peer_guard_binds_once_and_rejects_other() -> None:
    guard = _mapper().FirstPeerGuard()

    assert guard.current() is None
    assert guard.bind(111) is True
    assert guard.bind(111) is True
    assert guard.bind(222) is False
    assert guard.current() == 111

    guard.reset()
    assert guard.current() is None
    assert guard.bind(222) is True


def _manual_dm(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": 1,
        "from_id": 555,
        "peer_id": 555,
        "conversation_message_id": 9001,
        "text": "",
    }
    base.update(overrides)
    return base


def _forwarded(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": 2,
        "from_id": 777,
        "peer_id": PEER_ID,
        "conversation_message_id": 42,
        "text": "пересланный текст",
        "attachments": [
            {
                "type": "photo",
                "photo": {"owner_id": -1, "id": 5, "access_key": "abc"},
            }
        ],
    }
    base.update(overrides)
    return base


def test_extract_forwarded_payload_returns_first_forward_only() -> None:
    mapper = _mapper()

    forwarded = _forwarded()
    payload = mapper.extract_forwarded_payload(
        _manual_dm(fwd_messages=[forwarded, _forwarded(id=3)])
    )

    assert payload is forwarded


def test_extract_forwarded_payload_absent_returns_none() -> None:
    mapper = _mapper()

    assert mapper.extract_forwarded_payload(_manual_dm()) is None
    assert mapper.extract_forwarded_payload(_manual_dm(fwd_messages=[])) is None


def test_map_manual_source_uses_forwarded_text_and_attachments() -> None:
    mapper = _mapper()

    source = mapper.map_manual_source(
        message=_manual_dm(fwd_messages=[_forwarded()]),
        fwd=_forwarded(),
        author=_author(),
        initiator_id=555,
    )

    assert source is not None
    assert source.text == "пересланный текст"
    assert len(source.attachments) == 1
    assert source.attachments[0].source_ref == "-1_5_abc"
    assert source.attachments[0].access_key == "abc"
    assert source.source_key == "manual:555:9001"
    assert source.conversation_message_id == 9001


def test_map_manual_source_without_forward_uses_dm_content() -> None:
    mapper = _mapper()

    source = mapper.map_manual_source(
        message=_manual_dm(text="текст без пересылки"),
        fwd=None,
        author=_author(),
        initiator_id=555,
    )

    assert source is not None
    assert source.text == "текст без пересылки"
    assert source.attachments == ()


def test_map_manual_source_without_cmid_returns_none() -> None:
    mapper = _mapper()

    message = _manual_dm()
    del message["conversation_message_id"]

    assert (
        mapper.map_manual_source(message=message, fwd=None, author=_author(), initiator_id=555)
        is None
    )
