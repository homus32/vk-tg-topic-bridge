"""Wall-post normalization tests: identity, url, text, attachments (US-14)."""

from __future__ import annotations

from vk_topic_bridge.domain.enums import AttachmentKind, SourceType
from vk_topic_bridge.domain.value_objects import Author
from vk_topic_bridge.infrastructure.vk.mapper import extract_wall_payload, map_wall_post

GROUP_ID = 42
OWNER_ID = -999
POST_ID = 5


def _author() -> Author:
    return Author(user_id=123, first_name="Иван", last_name="Иванов", screen_name="ivan")


def _payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": POST_ID,
        "owner_id": OWNER_ID,
        "from_id": OWNER_ID,
        "date": 1700000000,
        "text": "текст поста",
        "attachments": [],
    }
    base.update(overrides)
    return base


def _event(payload: dict[str, object]) -> dict[str, object]:
    return {"type": "wall_post_new", "group_id": GROUP_ID, "object": payload}


def test_extract_wall_payload_returns_object_mapping() -> None:
    payload = _payload()
    assert extract_wall_payload(_event(payload)) == payload


def test_extract_wall_payload_rejects_non_mapping_object() -> None:
    assert extract_wall_payload({"object": "nope"}) is None
    assert extract_wall_payload({}) is None


def test_map_wall_post_identity_key_and_url() -> None:
    wall_post = map_wall_post(group_id=GROUP_ID, payload=_payload(), author=_author())

    assert wall_post.source_type is SourceType.VK_WALL
    assert wall_post.source_key == f"{GROUP_ID}:{OWNER_ID}:{POST_ID}"
    assert wall_post.url == f"https://vk.com/wall{OWNER_ID}_{POST_ID}"
    assert wall_post.owner_id == OWNER_ID
    assert wall_post.post_id == POST_ID
    assert wall_post.group_id == GROUP_ID


def test_map_wall_post_preserves_raw_text_unescaped() -> None:
    wall_post = map_wall_post(
        group_id=GROUP_ID, payload=_payload(text="<b>&amp;</b>"), author=_author()
    )

    assert wall_post.text == "<b>&amp;</b>"


def test_map_wall_post_missing_text_becomes_empty() -> None:
    wall_post = map_wall_post(group_id=GROUP_ID, payload=_payload(text=None), author=_author())

    assert wall_post.text == ""


def test_map_wall_post_requires_int_ids() -> None:
    import pytest

    with pytest.raises(ValueError):
        map_wall_post(group_id=GROUP_ID, payload=_payload(owner_id="x"), author=_author())
    with pytest.raises(ValueError):
        map_wall_post(group_id=GROUP_ID, payload=_payload(id=None), author=_author())


def test_map_wall_post_maps_attachments() -> None:
    payload = _payload(
        attachments=[
            {"type": "photo", "photo": {"owner_id": OWNER_ID, "id": 11, "access_key": "key"}},
            {
                "type": "doc",
                "doc": {"owner_id": OWNER_ID, "id": 33, "title": "file.pdf", "size": 100},
            },
        ]
    )
    wall_post = map_wall_post(group_id=GROUP_ID, payload=payload, author=_author())

    assert [attachment.kind for attachment in wall_post.attachments] == [
        AttachmentKind.PHOTO,
        AttachmentKind.DOCUMENT,
    ]
    assert wall_post.attachments[0].source_ref == f"{OWNER_ID}_11_key"
    assert wall_post.attachments[0].access_key == "key"
    assert wall_post.attachments[1].file_name == "file.pdf"
