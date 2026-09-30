"""Canonical logging setup: one Loguru pipeline with stdlib interception.

Importing this module has no side effects; `configure_logging` is the only entry point
that mutates global logging state.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable, Iterable, Mapping

from loguru import logger

from config import Settings
from log_context_fields import (
    _CROSS_SYSTEM_CORRELATION_FIELDS,
    _DELIVERY_NOTIFICATION_FIELDS,
    _MEDIA_PREPARATION_FIELDS,
    _REGISTRATION_CAPABILITY_FIELDS,
    _VK_API_MAPPING_FIELDS,
    _VK_EVENT_POLLING_FIELDS,
)

_MIN_SECRET_LENGTH = 8
_REDACTED = "<redacted>"

_NOISY_LOGGER_PREFIXES: tuple[str, ...] = (
    "aiogram",
    "vkbottle",
    "telethon",
    "sqlalchemy",
    "aiohttp",
    "asyncio",
    "aiosqlite",
)

# Telethon warns on every socket close before its automatic reconnect; only these
# known-benign chatter messages are muted, all other library warnings stay visible.
_SUPPRESSED_LIBRARY_RECORDS: tuple[tuple[str, str], ...] = (
    ("telethon.network.connection.connection", "Server closed the connection"),
)

_SAFE_CONTEXT_FIELDS: frozenset[str] = (
    _VK_EVENT_POLLING_FIELDS
    | _CROSS_SYSTEM_CORRELATION_FIELDS
    | _DELIVERY_NOTIFICATION_FIELDS
    | _MEDIA_PREPARATION_FIELDS
    | _REGISTRATION_CAPABILITY_FIELDS
    | _VK_API_MAPPING_FIELDS
)

_CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)

_FILE_FORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"


def redact_secrets(text: str, secrets: Iterable[str]) -> str:
    """Replace every non-empty secret occurrence of length >= 8 with a placeholder."""
    redacted = str(text)
    for raw_secret in secrets:
        secret = str(raw_secret)
        if len(secret) >= _MIN_SECRET_LENGTH:
            redacted = redacted.replace(secret, _REDACTED)
    return redacted


def _is_suppressed_library_record(name: str, message: str) -> bool:
    return any(
        name.startswith(prefix) and marker in message
        for prefix, marker in _SUPPRESSED_LIBRARY_RECORDS
    )


class _InterceptHandler(logging.Handler):
    """Forward stdlib logging records into Loguru, dropping noisy library noise."""

    def __init__(self, noisy_level: int) -> None:
        super().__init__()
        self._noisy_level = noisy_level

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < self._noisy_level and record.name.startswith(_NOISY_LOGGER_PREFIXES):
            return

        message = record.getMessage()
        if _is_suppressed_library_record(record.name, message):
            return

        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 0
        while frame is not None and (
            frame.f_code.co_filename != record.pathname
            or frame.f_code.co_name != record.funcName
            or frame.f_lineno != record.lineno
        ):
            frame = frame.f_back
            depth += 1

        context = _safe_context(record)
        if context:
            message = f"{message} | {context}"
        logger.opt(depth=depth, exception=record.exc_info).log(level, message)


def _sink_filter(noisy_level: int) -> Callable[[object], bool]:
    def allow(record: object) -> bool:
        if not isinstance(record, Mapping):
            return True
        name = record.get("name")
        if not isinstance(name, str):
            return True
        message = record.get("message")
        if isinstance(message, str) and _is_suppressed_library_record(name, message):
            return False
        level = record.get("level")
        level_number = getattr(level, "no", None)
        return not (
            name.startswith(_NOISY_LOGGER_PREFIXES)
            and isinstance(level_number, int)
            and level_number < noisy_level
        )

    return allow


def _safe_context(record: logging.LogRecord) -> str:
    """Render an allow-listed subset of stdlib ``extra`` fields for the Loguru sink."""
    fields: list[str] = []
    for name in sorted(_SAFE_CONTEXT_FIELDS):
        value = getattr(record, name, None)
        if value is None:
            continue
        if isinstance(value, (tuple, list, set, frozenset)):
            rendered = ",".join(str(item) for item in value)
        else:
            rendered = str(value)
        fields.append(f"{name}={rendered}")
    return " ".join(fields)


def configure_logging(settings: Settings) -> None:
    """(Re)build the Loguru pipeline from `Settings`; safe to call repeatedly."""
    logger.remove()
    noisy_level = logger.level(settings.LOG_LEVEL_LIBS).no
    sink_filter = _sink_filter(noisy_level)
    logger.add(
        sys.stderr,
        level=settings.LOG_LEVEL,
        format=_CONSOLE_FORMAT,
        filter=sink_filter,
        backtrace=True,
        diagnose=False,
    )
    compression = (
        None if settings.LOG_COMPRESSION.casefold() == "none" else settings.LOG_COMPRESSION
    )
    logger.add(
        settings.log_file(),
        level=settings.LOG_LEVEL,
        format=_FILE_FORMAT,
        filter=sink_filter,
        enqueue=True,
        rotation=settings.LOG_ROTATION,
        retention=settings.LOG_RETENTION,
        compression=compression,
        backtrace=True,
        diagnose=False,
    )
    logging.basicConfig(
        handlers=[_InterceptHandler(noisy_level)],
        level=0,
        force=True,
    )
    logger.bind(component="logging").info(
        "logging configured: level={} libs={} file={} rotation={} retention={} compression={}",
        settings.LOG_LEVEL,
        settings.LOG_LEVEL_LIBS,
        settings.log_file(),
        settings.LOG_ROTATION,
        settings.LOG_RETENTION,
        settings.LOG_COMPRESSION,
    )


def flush_logging() -> None:
    """Wait for the enqueued file-sink messages; call on shutdown."""
    logger.complete()
