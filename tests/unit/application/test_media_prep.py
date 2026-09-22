from __future__ import annotations

from typing import Never

from vk_topic_bridge.application.forwarding.composition import MediaLinkWarning
from vk_topic_bridge.application.forwarding.media_prep import prepare_media
from vk_topic_bridge.domain.enums import AttachmentKind
from vk_topic_bridge.domain.errors import (
    AttachmentDownloadFailed,
    MediaUnavailableError,
    RecoverableInfraError,
)
from vk_topic_bridge.domain.policies.attachment_policy import MAX_ATTACHMENT_BYTES
from vk_topic_bridge.domain.value_objects import Attachment


class UnavailableDownloader:
    def __init__(
        self,
        error: RecoverableInfraError | None = None,
        fallback_url: str | None = None,
    ) -> None:
        self.error = error or MediaUnavailableError(
            "no downloadable video", fallback_url=fallback_url
        )

    async def resolve_url(self, attachment: Attachment) -> Never:
        _ = attachment
        raise self.error

    async def download(self, attachment: Attachment, url: str) -> Never:
        _ = attachment
        _ = url
        raise AssertionError("download must not run")


def _video(*, link_url: str | None, size_bytes: int | None = None) -> Attachment:
    return Attachment(
        kind=AttachmentKind.VIDEO,
        file_name="clip",
        size_bytes=size_bytes,
        source_ref="-1_22",
        owner_id=-1,
        media_id=22,
        link_url=link_url,
    )


async def test_unavailable_video_becomes_vk_link_warning() -> None:
    planned, warnings = await prepare_media(
        (_video(link_url="https://vk.com/video-1_22"),), UnavailableDownloader()
    )

    assert planned == ()
    assert warnings == [
        MediaLinkWarning("🎬 Видео «clip» доступно по ссылке:", "https://vk.com/video-1_22")
    ]


async def test_unavailable_video_without_link_keeps_warning() -> None:
    planned, warnings = await prepare_media((_video(link_url=None),), UnavailableDownloader())

    assert planned == ()
    assert warnings == ["⚠️ Видео «clip» недоступно. Остальная публикация отправлена."]


async def test_unavailable_video_uses_player_link_from_lookup() -> None:
    planned, warnings = await prepare_media(
        (_video(link_url=None),),
        UnavailableDownloader(fallback_url="https://vk.example/player"),
    )

    assert planned == ()
    assert warnings == [
        MediaLinkWarning("🎬 Видео «clip» доступно по ссылке:", "https://vk.example/player")
    ]


async def test_failed_video_uses_canonical_link() -> None:
    planned, warnings = await prepare_media(
        (_video(link_url="https://vk.com/video-1_22"),),
        UnavailableDownloader(error=AttachmentDownloadFailed("lookup failed")),
    )

    assert planned == ()
    assert warnings == [
        MediaLinkWarning("🎬 Видео «clip» доступно по ссылке:", "https://vk.com/video-1_22")
    ]


async def test_oversize_video_uses_canonical_link() -> None:
    planned, warnings = await prepare_media(
        (
            _video(
                link_url="https://vk.com/video-1_22",
                size_bytes=MAX_ATTACHMENT_BYTES + 1,
            ),
        ),
        UnavailableDownloader(),
    )

    assert planned == ()
    assert warnings == [
        MediaLinkWarning("🎬 Видео «clip» доступно по ссылке:", "https://vk.com/video-1_22")
    ]
