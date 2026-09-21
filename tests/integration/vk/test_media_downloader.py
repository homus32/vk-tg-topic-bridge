"""Media downloader tests: resolve per-kind URLs, 50 MB guard, streaming, taxonomy.

No network: a fake RawVkApi replays canned VK responses and a fake aiohttp session
replays byte streams, so taxonomy and temp-file behavior are verified offline.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast

import aiohttp
import pytest
from vkbottle import VKAPIError

from vk_topic_bridge.domain.errors import AttachmentDownloadFailed, AttachmentTooLargeError
from vk_topic_bridge.domain.policies.attachment_policy import MAX_ATTACHMENT_BYTES
from vk_topic_bridge.domain.value_objects import Author
from vk_topic_bridge.infrastructure.vk.mapper import map_message
from vk_topic_bridge.infrastructure.vk.media_downloader import (
    VkMediaDownloader,
    VkMediaUnavailableError,
)

PHOTO_REF = "-1_11"
VIDEO_REF = "-1_22"
DOC_REF = "-1_33_ACCESSKEYXX"
BIG_DOC_REF = "-1_44"


class FakeVkApi:
    """Replays one canned response or raises one canned error; records calls."""

    def __init__(self, *, response: object = None, error: BaseException | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def request(
        self, method: str, data: dict[str, object], version: str | None = None
    ) -> dict[str, object]:
        _ = version
        self.calls.append((method, data))
        if self.error is not None:
            raise self.error
        return {"response": self.response}


class FakeContent:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks

    async def iter_chunked(self, _n: int) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk


class FakeResponse:
    def __init__(self, *, status: int = 200, chunks: tuple[bytes, ...] = ()) -> None:
        self.status = status
        self.content = FakeContent(chunks)

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


class FakeHttp:
    """Records GET urls; replays a response or raises before/inside streaming."""

    def __init__(
        self,
        *,
        response: FakeResponse | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.response = response or FakeResponse()
        self.error = error
        self.gets: list[str] = []

    def get(self, url: str) -> FakeResponse:
        self.gets.append(url)
        if self.error is not None:
            raise self.error
        return self.response


def _downloader(
    api: FakeVkApi,
    http: FakeHttp,
    media_dir: Path,
    *,
    user_api: FakeVkApi | None = None,
) -> VkMediaDownloader:
    return VkMediaDownloader(
        api,
        cast(aiohttp.ClientSession, http),
        media_dir,
        user_api=user_api,
    )


def _mapped_attachment(payload: dict[str, object]):
    source = map_message(
        group_id=42,
        message={
            "peer_id": 2000000001,
            "conversation_message_id": 789,
            "text": "@all",
            "attachments": [payload],
        },
        author=Author(user_id=1, first_name="", last_name="", screen_name=None),
    )
    return source.attachments[0]


def _photo_response() -> list[dict[str, object]]:
    return [
        {
            "sizes": [
                {"type": "m", "url": "https://vk.example/small.jpg", "width": 130, "height": 87},
                {"type": "w", "url": "https://vk.example/big.jpg", "width": 2560, "height": 1707},
                {"type": "x", "url": "https://vk.example/mid.jpg", "width": 604, "height": 403},
            ]
        }
    ]


# --- resolve_url ---------------------------------------------------------------


async def test_resolve_photo_uses_full_message_sizes_without_lookup(tmp_path: Path) -> None:
    api = FakeVkApi(response=_photo_response())
    downloader = _downloader(api, FakeHttp(), tmp_path)
    attachment = _mapped_attachment(
        {
            "type": "photo",
            "photo": {
                "owner_id": -1,
                "id": 11,
                "access_key": "PHOTO_KEY",
                "sizes": [
                    {"type": "s", "url": "https://vk.example/s.jpg", "width": 100, "height": 80},
                    {"type": "w", "url": "https://vk.example/w.jpg", "width": 1920, "height": 1080},
                ],
            },
        }
    )

    url = await downloader.resolve_url(attachment)

    assert url == "https://vk.example/w.jpg"
    assert api.calls == []


async def test_resolve_document_uses_full_message_url_without_lookup(tmp_path: Path) -> None:
    api = FakeVkApi(response=[])
    downloader = _downloader(api, FakeHttp(), tmp_path)
    attachment = _mapped_attachment(
        {
            "type": "doc",
            "doc": {
                "owner_id": -1,
                "id": 33,
                "access_key": "DOC_KEY",
                "title": "report.pdf",
                "size": 100,
                "url": "https://vk.example/report.pdf",
            },
        }
    )

    url = await downloader.resolve_url(attachment)

    assert url == "https://vk.example/report.pdf"
    assert api.calls == []


async def test_resolve_video_uses_inline_mp4_without_lookup(tmp_path: Path) -> None:
    api = FakeVkApi(response={"items": []})
    downloader = _downloader(api, FakeHttp(), tmp_path)
    attachment = _mapped_attachment(
        {
            "type": "video",
            "video": {
                "owner_id": -1,
                "id": 22,
                "files": {
                    "mp4_360": "https://vk.example/v360.mp4",
                    "mp4_720": "https://vk.example/v720.mp4",
                },
                "player": "https://vk.example/player",
            },
        }
    )

    url = await downloader.resolve_url(attachment)

    assert url == "https://vk.example/v720.mp4"
    assert api.calls == []


async def test_resolve_photo_requests_get_by_id_with_full_identifier(tmp_path: Path) -> None:
    api = FakeVkApi(response=_photo_response())
    downloader = _downloader(api, FakeHttp(), tmp_path)

    url = await downloader.resolve_url(
        _mapped_attachment({"type": "photo", "photo": {"owner_id": -1, "id": 11}})
    )

    assert url == "https://vk.example/big.jpg"
    method, params = api.calls[0]
    assert method == "photos.getById"
    assert params["photos"] == [PHOTO_REF]


async def test_resolve_photo_uses_configured_user_api(tmp_path: Path) -> None:
    group_api = FakeVkApi(response=[])
    user_api = FakeVkApi(response=_photo_response())
    downloader = _downloader(group_api, FakeHttp(), tmp_path, user_api=user_api)

    url = await downloader.resolve_url(
        _mapped_attachment({"type": "photo", "photo": {"owner_id": -1, "id": 11}})
    )

    assert url == "https://vk.example/big.jpg"
    assert group_api.calls == []
    assert user_api.calls[0][0] == "photos.getById"


async def test_resolve_photo_identifier_keeps_access_key(tmp_path: Path) -> None:
    api = FakeVkApi(response=_photo_response())
    downloader = _downloader(api, FakeHttp(), tmp_path)

    await downloader.resolve_url(
        _mapped_attachment(
            {"type": "photo", "photo": {"owner_id": -1, "id": 11, "access_key": "SECRETKEY"}}
        )
    )

    assert api.calls[0][1]["photos"] == [f"{PHOTO_REF}_SECRETKEY"]


async def test_resolve_document_returns_url_and_requests_get_by_id(tmp_path: Path) -> None:
    api = FakeVkApi(response=[{"id": 33, "owner_id": -1, "url": "https://vk.example/f.pdf"}])
    downloader = _downloader(api, FakeHttp(), tmp_path)

    url = await downloader.resolve_url(
        _mapped_attachment(
            {
                "type": "doc",
                "doc": {"owner_id": -1, "id": 33, "access_key": "ACCESSKEYXX"},
            }
        )
    )

    assert url == "https://vk.example/f.pdf"
    method, params = api.calls[0]
    assert method == "docs.getById"
    assert params["docs"] == [DOC_REF]


async def test_resolve_video_picks_highest_quality_mp4(tmp_path: Path) -> None:
    api = FakeVkApi(
        response={
            "items": [
                {
                    "files": {
                        "mp4_360": "https://vk.example/v360.mp4",
                        "mp4_720": "https://vk.example/v720.mp4",
                    },
                    "player": "https://vk.example/player",
                }
            ]
        }
    )
    downloader = _downloader(api, FakeHttp(), tmp_path)

    url = await downloader.resolve_url(
        _mapped_attachment({"type": "video", "video": {"owner_id": -1, "id": 22}})
    )

    assert url == "https://vk.example/v720.mp4"
    assert api.calls[0][0] == "video.get"


async def test_resolve_video_uses_configured_user_api(tmp_path: Path) -> None:
    group_api = FakeVkApi(response={"items": []})
    user_api = FakeVkApi(
        response={
            "items": [
                {"files": {"mp4_720": "https://vk.example/user-video.mp4"}},
            ]
        }
    )
    downloader = _downloader(group_api, FakeHttp(), tmp_path, user_api=user_api)

    url = await downloader.resolve_url(
        _mapped_attachment({"type": "video", "video": {"owner_id": -1, "id": 22}})
    )

    assert url == "https://vk.example/user-video.mp4"
    assert group_api.calls == []
    assert user_api.calls[0][0] == "video.get"


async def test_resolve_video_without_mp4_files_is_unavailable(tmp_path: Path) -> None:
    api = FakeVkApi(response={"items": [{"player": "https://vk.example/player"}]})
    downloader = _downloader(api, FakeHttp(), tmp_path)

    with pytest.raises(VkMediaUnavailableError) as exc_info:
        await downloader.resolve_url(
            _mapped_attachment({"type": "video", "video": {"owner_id": -1, "id": 22}})
        )

    assert exc_info.value.fallback_url == "https://vk.example/player"


async def test_resolve_video_with_empty_items_is_unavailable(tmp_path: Path) -> None:
    api = FakeVkApi(response={"items": []})
    downloader = _downloader(api, FakeHttp(), tmp_path)

    with pytest.raises(VkMediaUnavailableError):
        await downloader.resolve_url(
            _mapped_attachment({"type": "video", "video": {"owner_id": -1, "id": 22}})
        )


async def test_resolve_access_denied_vk_error_is_unavailable(tmp_path: Path) -> None:
    api = FakeVkApi(error=VKAPIError[204](error_msg="access denied"))
    downloader = _downloader(api, FakeHttp(), tmp_path)

    with pytest.raises(VkMediaUnavailableError):
        await downloader.resolve_url(
            _mapped_attachment({"type": "video", "video": {"owner_id": -1, "id": 22}})
        )


async def test_lookup_trace_contains_method_and_vk_error_without_secret(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    api = FakeVkApi(error=VKAPIError[204](error_msg="access denied"))
    downloader = _downloader(api, FakeHttp(), tmp_path)

    with caplog.at_level("DEBUG"), pytest.raises(VkMediaUnavailableError):
        await downloader.resolve_url(
            _mapped_attachment(
                {
                    "type": "video",
                    "video": {
                        "owner_id": -1,
                        "id": 22,
                        "access_key": "SECRETKEYXX",
                    },
                }
            )
        )

    failed = [
        record for record in caplog.records if record.message == "vk media API request failed"
    ]
    assert failed
    assert failed[0].__dict__["method"] == "video.get"
    assert failed[0].__dict__["vk_error_code"] == 204
    assert failed[0].__dict__["vk_error_class"].startswith("VKAPIError")
    assert "SECRETKEYXX" not in caplog.text


async def test_resolve_oversize_document_refused_before_download(tmp_path: Path) -> None:
    api = FakeVkApi(
        response=[
            {
                "id": 44,
                "owner_id": -1,
                "url": "https://vk.example/big.zip",
                "size": MAX_ATTACHMENT_BYTES + 1,
            }
        ]
    )
    http = FakeHttp()
    downloader = _downloader(api, http, tmp_path)

    with pytest.raises(AttachmentTooLargeError):
        await downloader.resolve_url(
            _mapped_attachment({"type": "doc", "doc": {"owner_id": -1, "id": 44}})
        )

    assert http.gets == []


# --- download ------------------------------------------------------------------


async def test_download_streams_chunks_into_media_dir(tmp_path: Path) -> None:
    payload = b"x" * 1024 * 1024
    http = FakeHttp(response=FakeResponse(chunks=(payload[: 512 * 1024], payload[512 * 1024 :])))
    media_dir = tmp_path / "media"
    downloader = _downloader(FakeVkApi(), http, media_dir)

    path = await downloader.download(
        _mapped_attachment({"type": "doc", "doc": {"owner_id": -1, "id": 33}}),
        "https://vk.example/f.bin",
    )

    assert media_dir.is_dir()
    assert Path(path).read_bytes() == payload
    assert http.gets == ["https://vk.example/f.bin"]


async def test_download_emits_safe_media_trace(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    payload = b"x" * 1024
    http = FakeHttp(response=FakeResponse(chunks=(payload,)))
    downloader = _downloader(FakeVkApi(), http, tmp_path)

    with caplog.at_level("DEBUG"):
        await downloader.download(
            _mapped_attachment({"type": "doc", "doc": {"owner_id": -1, "id": 33}}),
            "https://vk.example/f.bin?key=ACCESSKEYXX",
        )

    assert "vk media download started" in caplog.text
    assert "vk media download completed" in caplog.text
    assert "ACCESSKEYXX" not in caplog.text


async def test_download_midstream_oversize_aborts_and_removes_temp(tmp_path: Path) -> None:
    chunk = b"y" * (1024 * 1024)
    chunks = (chunk,) * (MAX_ATTACHMENT_BYTES // len(chunk) + 2)
    http = FakeHttp(response=FakeResponse(chunks=chunks))
    media_dir = tmp_path / "media"
    downloader = _downloader(FakeVkApi(), http, media_dir)

    with pytest.raises(AttachmentTooLargeError):
        await downloader.download(
            _mapped_attachment({"type": "doc", "doc": {"owner_id": -1, "id": 33}}),
            "https://vk.example/big.bin",
        )

    assert list(media_dir.iterdir()) == []


async def test_download_http_error_status_maps_to_download_failed(tmp_path: Path) -> None:
    http = FakeHttp(response=FakeResponse(status=500))
    downloader = _downloader(FakeVkApi(), http, tmp_path)

    with pytest.raises(AttachmentDownloadFailed):
        await downloader.download(
            _mapped_attachment({"type": "doc", "doc": {"owner_id": -1, "id": 33}}),
            "https://vk.example/f.bin",
        )

    assert list(tmp_path.iterdir()) == []


async def test_download_connection_error_maps_to_download_failed(tmp_path: Path) -> None:
    http = FakeHttp(error=aiohttp.ClientConnectionError("dropped"))
    downloader = _downloader(FakeVkApi(), http, tmp_path)

    with pytest.raises(AttachmentDownloadFailed):
        await downloader.download(
            _mapped_attachment({"type": "doc", "doc": {"owner_id": -1, "id": 33}}),
            "https://vk.example/f.bin",
        )


async def test_download_does_not_log_access_key(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    http = FakeHttp(error=aiohttp.ClientConnectionError("dropped"))
    downloader = _downloader(FakeVkApi(), http, tmp_path)

    with caplog.at_level("DEBUG"), pytest.raises(AttachmentDownloadFailed):
        await downloader.download(
            _mapped_attachment({"type": "doc", "doc": {"owner_id": -1, "id": 33}}),
            "https://vk.example/f.bin?key=ACCESSKEYXX",
        )

    assert "ACCESSKEYXX" not in caplog.text


async def test_download_cancellation_propagates(tmp_path: Path) -> None:
    import asyncio

    http = FakeHttp(error=asyncio.CancelledError())
    downloader = _downloader(FakeVkApi(), http, tmp_path)

    with pytest.raises(asyncio.CancelledError):
        await downloader.download(
            _mapped_attachment({"type": "doc", "doc": {"owner_id": -1, "id": 33}}),
            "https://vk.example/f.bin",
        )
