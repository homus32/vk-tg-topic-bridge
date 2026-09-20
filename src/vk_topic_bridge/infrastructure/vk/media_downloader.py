"""VK media download adapter: photo/video/document -> temp files for Telegram upload.

The shared media pipeline: download happens after the 50 MB pre-check; VK video may
lack a directly downloadable URL, in which case the per-item warning path applies
(docs/03 §12.5) instead of any retry loop.

Error mapping (frozen):
- missing downloadable URL / VK access errors for one item -> ``VkMediaUnavailableError``;
- known or mid-stream size over the policy limit -> ``AttachmentTooLargeError``;
- transport/status failures -> ``AttachmentDownloadFailed``.
All three are warning paths for the caller (docs/03 §12.4): the publication continues.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp
from vkbottle import VKAPIError

from vk_topic_bridge.domain.enums import AttachmentKind
from vk_topic_bridge.domain.errors import (
    AttachmentDownloadFailed,
    AttachmentTooLargeError,
    MediaUnavailableError,
)
from vk_topic_bridge.domain.policies.attachment_policy import MAX_ATTACHMENT_BYTES
from vk_topic_bridge.infrastructure.vk.api import RawVkApi

logger = logging.getLogger(__name__)

# Highest-quality mp4 first; the full list is our fallback policy (video.get contract).
_VIDEO_QUALITY_ORDER = (
    "mp4_2160",
    "mp4_1440",
    "mp4_1080",
    "mp4_720",
    "mp4_480",
    "mp4_360",
    "mp4_240",
    "mp4_144",
)

# VK access/permission codes that mean "this particular media cannot be fetched".
_ACCESS_DENIED_CODES = frozenset({15, 100, 200, 204, 1153})


class VkMediaUnavailableError(MediaUnavailableError):
    """VK provided no downloadable resource for one media item (per-item warning)."""


class VkMediaDownloader:
    """Resolves the direct URL for one attachment, then streams it to a temp file."""

    def __init__(self, api: RawVkApi, http: aiohttp.ClientSession, media_dir: Path) -> None:
        self._api = api
        self._http = http
        self._media_dir = Path(media_dir)

    async def resolve_url(self, source_ref: str, kind: AttachmentKind) -> str:
        """Resolve the direct download URL for one attachment identifier.

        ``source_ref`` is ``{owner_id}_{media_id}[_{access_key}]`` as produced by the
        mapper; the access key stays embedded in the identifier per the VK schema.
        """
        logger.debug("vk media URL resolution started", extra={"attachment_kind": kind.value})
        if kind is AttachmentKind.PHOTO:
            url = await self._resolve_photo(source_ref)
        elif kind is AttachmentKind.VIDEO:
            url = await self._resolve_video(source_ref)
        elif kind is AttachmentKind.DOCUMENT:
            url = await self._resolve_document(source_ref)
        else:
            msg = f"attachment kind {kind} has no download route"
            raise VkMediaUnavailableError(msg)
        logger.debug(
            "vk media URL resolution completed",
            extra={"attachment_kind": kind.value, "url_host": urlsplit(url).hostname},
        )
        return url

    async def download(self, source_ref: str, url: str) -> str:
        """Stream ``url`` into a temp file inside the media dir; return its path.

        Callers own the file afterwards (the publisher deletes it after the Bot API
        call); on any failure this method removes the partial file itself.
        """
        self._media_dir.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - closed in finally
            dir=self._media_dir, prefix="vk-media-", suffix=".bin", delete=False
        )
        path = Path(handle.name)
        written = 0
        logger.debug(
            "vk media download started",
            extra={"url_host": urlsplit(url).hostname},
        )
        try:
            try:
                context = self._http.get(url)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                msg = "media download failed"
                raise AttachmentDownloadFailed(msg) from exc
            async with context as response:
                if response.status != 200:
                    logger.warning(
                        "vk media download returned unexpected status",
                        extra={"http_status": response.status},
                    )
                    msg = f"media download returned HTTP {response.status}"
                    raise AttachmentDownloadFailed(msg)
                async for chunk in response.content.iter_chunked(64 * 1024):
                    written += len(chunk)
                    if written > MAX_ATTACHMENT_BYTES:
                        logger.warning(
                            "vk media download exceeded size limit",
                            extra={"written_bytes": written},
                        )
                        msg = "attachment exceeds the 50 MB limit"
                        raise AttachmentTooLargeError(msg)
                    handle.write(chunk)
            handle.close()
            logger.debug("vk media download completed", extra={"written_bytes": written})
            return str(path)
        except asyncio.CancelledError:
            handle.close()
            path.unlink(missing_ok=True)
            logger.debug("vk media download cancelled", extra={"written_bytes": written})
            raise
        except AttachmentTooLargeError, AttachmentDownloadFailed:
            handle.close()
            path.unlink(missing_ok=True)
            logger.warning(
                "vk media download failed",
                extra={"written_bytes": written, "reason": "download_failed"},
            )
            raise
        except Exception as exc:
            handle.close()
            path.unlink(missing_ok=True)
            logger.warning(
                "vk media download failed mid-stream",
                extra={"written_bytes": written, "reason": type(exc).__name__},
            )
            msg = "media download failed mid-stream"
            raise AttachmentDownloadFailed(msg) from exc

    async def _resolve_photo(self, source_ref: str) -> str:
        response = await self._request("photos.getById", {"photos": [source_ref]})
        item = _first_mapping(response)
        sizes = item.get("sizes") if item else None
        best: str | None = None
        best_area = -1
        if isinstance(sizes, list):
            for size in sizes:
                if not isinstance(size, Mapping):
                    continue
                candidate = size.get("url")
                width = size.get("width")
                height = size.get("height")
                if not isinstance(candidate, str):
                    continue
                area = width * height if isinstance(width, int) and isinstance(height, int) else 0
                if area > best_area:
                    best, best_area = candidate, area
        if best is None:
            msg = "VK photo has no downloadable size"
            raise VkMediaUnavailableError(msg)
        return best

    async def _resolve_video(self, source_ref: str) -> str:
        response = await self._request("video.get", {"videos": [source_ref]})
        items = response.get("items") if isinstance(response, Mapping) else None
        item = items[0] if isinstance(items, list) and items else None
        files = item.get("files") if isinstance(item, Mapping) else None
        if isinstance(files, Mapping):
            for quality in _VIDEO_QUALITY_ORDER:
                candidate = files.get(quality)
                if isinstance(candidate, str) and candidate:
                    return candidate
        # ``player`` is an embed page, not a media resource: never used for download.
        msg = "VK video has no downloadable mp4 resource"
        raise VkMediaUnavailableError(msg)

    async def _resolve_document(self, source_ref: str) -> str:
        response = await self._request("docs.getById", {"docs": [source_ref]})
        item = _first_mapping(response)
        url = item.get("url") if item else None
        size = item.get("size") if item else None
        if isinstance(size, int) and size > MAX_ATTACHMENT_BYTES:
            msg = "attachment exceeds the 50 MB limit"
            raise AttachmentTooLargeError(msg)
        if not isinstance(url, str) or not url:
            msg = "VK document has no downloadable url"
            raise VkMediaUnavailableError(msg)
        return url

    async def _request(self, method: str, params: dict[str, object]) -> object:
        logger.debug("vk media API request started", extra={"method": method})
        try:
            response = await self._api.request(method, params)
        except VKAPIError as exc:
            logger.warning(
                "vk media API request failed",
                extra={"method": method, "outcome": str(exc.code)},
            )
            if exc.code in _ACCESS_DENIED_CODES:
                raise VkMediaUnavailableError(f"vk access error {exc.code}") from exc
            raise AttachmentDownloadFailed(f"vk error {exc.code}") from exc
        if not isinstance(response, Mapping):
            logger.warning(
                "vk media API returned invalid response",
                extra={"method": method, "reason": "invalid_response"},
            )
            msg = f"unexpected VK response for {method}"
            raise AttachmentDownloadFailed(msg)
        logger.debug("vk media API request completed", extra={"method": method})
        return response.get("response")


def _first_mapping(response: object) -> Mapping[str, object] | None:
    if isinstance(response, list) and response and isinstance(response[0], Mapping):
        return response[0]
    if isinstance(response, Mapping):
        return response
    return None
