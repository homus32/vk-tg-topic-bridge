"""Canonical logging setup: one Loguru pipeline with stdlib interception.

Importing this module has no side effects; `configure_logging` is the only entry point
that mutates global logging state.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterable

from loguru import logger

from config import Settings

_MIN_SECRET_LENGTH = 8
_REDACTED = "<redacted>"

_NOISY_LOGGER_PREFIXES: tuple[str, ...] = (
    "aiogram",
    "vkbottle",
    "telethon",
    "sqlalchemy",
    "aiohttp",
    "asyncio",
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


class _InterceptHandler(logging.Handler):
    """Forward stdlib logging records into Loguru, dropping noisy library noise."""

    def __init__(self, noisy_level: int) -> None:
        super().__init__()
        self._noisy_level = noisy_level

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < self._noisy_level and record.name.startswith(_NOISY_LOGGER_PREFIXES):
            return

        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame is not None and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def configure_logging(settings: Settings) -> None:
    """(Re)build the Loguru pipeline from `Settings`; safe to call repeatedly."""
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.LOG_LEVEL,
        format=_CONSOLE_FORMAT,
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
        enqueue=True,
        rotation=settings.LOG_ROTATION,
        retention=settings.LOG_RETENTION,
        compression=compression,
        backtrace=True,
        diagnose=False,
    )
    logging.basicConfig(
        handlers=[_InterceptHandler(logger.level(settings.LOG_LEVEL_LIBS).no)],
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
