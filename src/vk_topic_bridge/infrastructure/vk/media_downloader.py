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
from vk_topic_bridge.domain.value_objects import Attachment
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

    def __init__(
        self,
        api: RawVkApi,
        http: aiohttp.ClientSession,
        media_dir: Path,
        *,
        token_type: str = "group",
        user_api: RawVkApi | None = None,
    ) -> None:
        self._api = api
        self._http = http
        self._media_dir = Path(media_dir)
        self._token_type = token_type
        self._user_api = user_api

    async def resolve_url(self, attachment: Attachment) -> str:
        """Resolve the direct download URL for one attachment identifier.

        ``source_ref`` is ``{owner_id}_{media_id}[_{access_key}]`` as produced by the
        mapper; the access key stays embedded in the identifier per the VK schema.
        """
        kind = attachment.kind
        logger.debug(
            "vk media URL resolution started",
            extra={
                "attachment_kind": kind.value,
                "direct_url_present": attachment.direct_url is not None,
                "variant_count": len(attachment.variants),
                "api_adapter": "vkbottle_raw_api",
                "token_type": self._token_type,
            },
        )
        inline_url = _inline_url(attachment)
        if inline_url is not None:
            logger.debug(
                "vk media URL resolution completed",
                extra={
                    "attachment_kind": kind.value,
                    "url_host": urlsplit(inline_url).hostname,
                    "lookup": False,
                    "resolution_source": "full_message",
                },
            )
            return inline_url
        source_ref = attachment.source_ref
        if not source_ref:
            msg = "VK attachment has no identity for URL lookup"
            raise VkMediaUnavailableError(msg)
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
            extra={
                "attachment_kind": kind.value,
                "url_host": urlsplit(url).hostname,
                "lookup": True,
                "lookup_method": _lookup_method(kind),
                "resolution_source": "vk_api",
            },
        )
        return url

    async def download(self, attachment: Attachment, url: str) -> str:
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
            extra={
                "attachment_kind": attachment.kind.value,
                "url_host": urlsplit(url).hostname,
                "download_result": "started",
            },
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
            logger.debug(
                "vk media download completed",
                extra={"written_bytes": written, "download_result": "success"},
            )
            return str(path)
        except asyncio.CancelledError:
            handle.close()
            path.unlink(missing_ok=True)
            logger.debug(
                "vk media download cancelled",
                extra={"written_bytes": written, "download_result": "cancelled"},
            )
            raise
        except AttachmentTooLargeError, AttachmentDownloadFailed:
            handle.close()
            path.unlink(missing_ok=True)
            logger.warning(
                "vk media download failed",
                extra={
                    "written_bytes": written,
                    "reason": "download_failed",
                    "download_result": "failed",
                },
            )
            raise
        except Exception as exc:
            handle.close()
            path.unlink(missing_ok=True)
            logger.warning(
                "vk media download failed mid-stream",
                extra={
                    "written_bytes": written,
                    "reason": type(exc).__name__,
                    "download_result": "failed",
                },
            )
            msg = "media download failed mid-stream"
            raise AttachmentDownloadFailed(msg) from exc

    async def _resolve_photo(self, source_ref: str) -> str:
        response = await self._request("photos.getById", {"photos": [source_ref]})
        item = _first_mapping(response)
        sizes = item.get("images") or item.get("sizes") if item else None
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
        player = item.get("player") if isinstance(item, Mapping) else None
        fallback_url = player if isinstance(player, str) and player.startswith("https://") else None
        logger.debug(
            "vk video response inspected",
            extra={
                "files_present": isinstance(files, Mapping),
                "player_present": fallback_url is not None,
                "variant_count": len(files) if isinstance(files, Mapping) else 0,
            },
        )
        if isinstance(files, Mapping):
            candidate = _select_video_url(files)
            if candidate is not None:
                return candidate
        msg = "VK video has no downloadable mp4 resource"
        raise VkMediaUnavailableError(msg, fallback_url=fallback_url)

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
        api, token_type = _lookup_client(
            method,
            default_api=self._api,
            default_token_type=self._token_type,
            user_api=self._user_api,
        )
        logger.debug(
            "vk media API request started",
            extra={
                "method": method,
                "api_adapter": "vkbottle_raw_api",
                "token_type": token_type,
            },
        )
        try:
            response = await api.request(method, params)
        except VKAPIError as exc:
            logger.warning(
                "vk media API request failed",
                extra={
                    "method": method,
                    "outcome": "error",
                    "vk_error_code": exc.code,
                    "vk_error_class": type(exc).__name__,
                    "api_adapter": "vkbottle_raw_api",
                    "token_type": token_type,
                },
            )
            if exc.code in _ACCESS_DENIED_CODES:
                raise VkMediaUnavailableError(f"vk access error {exc.code}") from exc
            raise AttachmentDownloadFailed(f"vk error {exc.code}") from exc
        if not isinstance(response, Mapping):
            logger.warning(
                "vk media API returned invalid response",
                extra={
                    "method": method,
                    "reason": "invalid_response",
                    "outcome": "invalid_response",
                    "api_adapter": "vkbottle_raw_api",
                    "token_type": token_type,
                },
            )
            msg = f"unexpected VK response for {method}"
            raise AttachmentDownloadFailed(msg)
        logger.debug(
            "vk media API request completed",
            extra={
                "method": method,
                "outcome": "success",
                "api_adapter": "vkbottle_raw_api",
                "token_type": token_type,
            },
        )
        return response.get("response")


def _first_mapping(response: object) -> Mapping[str, object] | None:
    if isinstance(response, list) and response and isinstance(response[0], Mapping):
        return response[0]
    if isinstance(response, Mapping):
        return response
    return None


def _lookup_method(kind: AttachmentKind) -> str:
    return {
        AttachmentKind.PHOTO: "photos.getById",
        AttachmentKind.VIDEO: "video.get",
        AttachmentKind.DOCUMENT: "docs.getById",
    }.get(kind, "unsupported")


def _lookup_client(
    method: str,
    *,
    default_api: RawVkApi,
    default_token_type: str,
    user_api: RawVkApi | None,
) -> tuple[RawVkApi, str]:
    if user_api is not None and method in {"photos.getById", "video.get"}:
        return user_api, "user"
    return default_api, default_token_type


def _inline_url(attachment: Attachment) -> str | None:
    if attachment.direct_url:
        return attachment.direct_url
    if attachment.kind is AttachmentKind.PHOTO:
        best = max(
            attachment.variants,
            key=lambda variant: (variant.width or 0) * (variant.height or 0),
            default=None,
        )
        return best.url if best is not None else None
    if attachment.kind is AttachmentKind.VIDEO:
        files = {
            variant.quality: variant.url
            for variant in attachment.variants
            if variant.quality is not None
        }
        return _select_video_url(files)
    return None


def _select_video_url(files: Mapping[str, object]) -> str | None:
    for quality in _VIDEO_QUALITY_ORDER:
        candidate = files.get(quality)
        if isinstance(candidate, str) and candidate:
            return candidate
    return None
