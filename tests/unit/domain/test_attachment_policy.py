"""Unit tests for the attachment policy: 50 MB limit, classification and warnings."""

import pytest

from vk_topic_bridge.domain.enums import AttachmentKind
from vk_topic_bridge.domain.policies import attachment_policy
from vk_topic_bridge.domain.value_objects import Attachment

MB = 1024 * 1024


def _attachment(
    kind: AttachmentKind, *, size: int | None = None, name: str | None = None
) -> Attachment:
    return Attachment(kind=kind, file_name=name, size_bytes=size, source_ref="ref")


def test_max_attachment_bytes_is_fifty_megabytes() -> None:
    assert attachment_policy.MAX_ATTACHMENT_BYTES == 50 * MB


def test_exactly_fifty_megabytes_is_allowed() -> None:
    assert attachment_policy.is_within_size_limit(50 * MB) is True


def test_one_byte_over_the_limit_is_rejected() -> None:
    assert attachment_policy.is_within_size_limit(50 * MB + 1) is False


def test_unknown_size_is_allowed() -> None:
    assert attachment_policy.is_within_size_limit(None) is True


@pytest.mark.parametrize(
    ("raw_type", "expected"),
    [
        ("photo", AttachmentKind.PHOTO),
        ("video", AttachmentKind.VIDEO),
        ("doc", AttachmentKind.DOCUMENT),
        ("audio", AttachmentKind.UNSUPPORTED),
        ("wall", AttachmentKind.UNSUPPORTED),
        ("sticker", AttachmentKind.UNSUPPORTED),
    ],
)
def test_classify_attachment_type(raw_type: str, expected: AttachmentKind) -> None:
    assert attachment_policy.classify_attachment_type(raw_type) is expected


def test_supported_small_attachment_has_no_warning() -> None:
    assert (
        attachment_policy.attachment_warning(
            _attachment(AttachmentKind.PHOTO, size=10, name="p.jpg")
        )
        is None
    )


def test_unsupported_attachment_produces_warning() -> None:
    warning = attachment_policy.attachment_warning(
        _attachment(AttachmentKind.UNSUPPORTED, name="voice.ogg")
    )
    assert warning is not None
    assert "voice.ogg" in warning


def test_oversized_attachment_produces_warning() -> None:
    warning = attachment_policy.attachment_warning(
        _attachment(AttachmentKind.VIDEO, size=50 * MB + 1, name="big.mp4")
    )
    assert warning is not None
    assert "big.mp4" in warning
