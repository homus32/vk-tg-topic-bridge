"""Unit tests for the canonical root `logger.py` (Loguru pipeline + stdlib interception).

`logger` is imported lazily so that, during the RED phase, its absence surfaces as a
normal test failure instead of aborting collection of the whole suite.
"""

import importlib
import logging
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from loguru import logger

from config import Settings

NOISY_PREFIXES = ("aiogram", "vkbottle", "telethon", "sqlalchemy", "aiohttp", "asyncio")


class _CapturedSink:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def __call__(self, message: object) -> None:
        self.messages.append(str(message))


def _logger_module() -> ModuleType:
    return importlib.import_module("logger")


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {"LOG_DIR": tmp_path}
    values.update(overrides)
    return Settings.model_validate(values)


def _capture_sink() -> _CapturedSink:
    sink = _CapturedSink()
    logger.add(sink, format="{message}", level=0)
    return sink


def _emit_stdlib(
    monkeypatch: pytest.MonkeyPatch, logger_name: str, level: int, message: str
) -> None:
    """Force the stdlib logger level so the record reaches handlers regardless of any
    level a library may have configured earlier in the session."""
    stdlib_logger = logging.getLogger(logger_name)
    monkeypatch.setattr(stdlib_logger, "level", level)
    stdlib_logger.log(level, message)


@pytest.fixture
def logging_state() -> Iterator[None]:
    saved_handlers = logging.root.handlers[:]
    saved_level = logging.root.level
    logger.remove()
    try:
        yield
    finally:
        logger.remove()
        logging.root.handlers[:] = saved_handlers
        logging.root.setLevel(saved_level)
        logger.add(sys.stderr)


@pytest.mark.usefixtures("logging_state")
def test_import_does_not_install_intercept_handler() -> None:
    module = _logger_module()
    intercept_handler = getattr(module, "_InterceptHandler")  # noqa: B009

    assert not any(isinstance(handler, intercept_handler) for handler in logging.root.handlers)


@pytest.mark.usefixtures("logging_state")
def test_stdlib_record_reaches_loguru_sink(tmp_path: Path) -> None:
    module = _logger_module()
    module.configure_logging(_settings(tmp_path))
    sink = _capture_sink()

    logging.getLogger("aiogram.test").warning("X")

    assert any("X" in message for message in sink.messages)


@pytest.mark.usefixtures("logging_state")
def test_file_sink_creates_app_log_with_record(tmp_path: Path) -> None:
    module = _logger_module()
    settings = _settings(tmp_path)
    module.configure_logging(settings)

    logger.info("file-sink-record-42")
    module.flush_logging()

    assert settings.log_file() == tmp_path / "app.log"
    assert "file-sink-record-42" in settings.log_file().read_text(encoding="utf-8")


@pytest.mark.usefixtures("logging_state")
@pytest.mark.parametrize("prefix", NOISY_PREFIXES)
def test_library_filter_drops_noisy_record_below_lib_level(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prefix: str
) -> None:
    module = _logger_module()
    module.configure_logging(_settings(tmp_path))
    sink = _capture_sink()

    _emit_stdlib(monkeypatch, f"{prefix}.diagnostics", logging.DEBUG, "noisy-debug")

    assert not any("noisy-debug" in message for message in sink.messages)


@pytest.mark.usefixtures("logging_state")
def test_library_filter_keeps_noisy_record_at_lib_level(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _logger_module()
    module.configure_logging(_settings(tmp_path))
    sink = _capture_sink()

    _emit_stdlib(monkeypatch, "aiogram.diagnostics", logging.WARNING, "noisy-warning")

    assert any("noisy-warning" in message for message in sink.messages)


@pytest.mark.usefixtures("logging_state")
def test_library_filter_keeps_non_noisy_record_below_lib_level(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _logger_module()
    module.configure_logging(_settings(tmp_path))
    sink = _capture_sink()

    _emit_stdlib(monkeypatch, "vk_topic_bridge.core", logging.DEBUG, "app-debug")

    assert any("app-debug" in message for message in sink.messages)


@pytest.mark.usefixtures("logging_state")
def test_library_filter_level_comes_from_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _logger_module()
    module.configure_logging(_settings(tmp_path, LOG_LEVEL_LIBS="ERROR"))
    sink = _capture_sink()

    _emit_stdlib(monkeypatch, "aiogram.diagnostics", logging.WARNING, "noisy-warning")
    _emit_stdlib(monkeypatch, "aiogram.diagnostics", logging.ERROR, "noisy-error")

    assert not any("noisy-warning" in message for message in sink.messages)
    assert any("noisy-error" in message for message in sink.messages)


@pytest.mark.usefixtures("logging_state")
def test_compression_none_is_accepted(tmp_path: Path) -> None:
    module = _logger_module()
    module.configure_logging(_settings(tmp_path, LOG_COMPRESSION="none"))

    logger.info("uncompressed-record")
    module.flush_logging()

    assert "uncompressed-record" in (tmp_path / "app.log").read_text(encoding="utf-8")


@pytest.mark.usefixtures("logging_state")
def test_flush_logging_completes(tmp_path: Path) -> None:
    module = _logger_module()
    module.configure_logging(_settings(tmp_path))

    logger.info("flush-record")
    module.flush_logging()

    assert "flush-record" in (tmp_path / "app.log").read_text(encoding="utf-8")
