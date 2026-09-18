"""Persistent VK cursor transport tests: path layout, restore, gap kind, one-shot notice.

Everything runs against a tmp state dir with the pinned vkbottle base class, no network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vk_topic_bridge.infrastructure.vk.cursor import RuntimePathBotPolling, history_gap_kind

GROUP_ID = 777


class _FakeApi:
    """Minimal ``ABCAPI`` twin for the parent's ``get_server`` reconnect path."""

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"response": {"ts": "555", "server": "new", "key": "new-key"}}


def _polling(state_dir: Path, on_gap: object | None = None) -> RuntimePathBotPolling:
    return RuntimePathBotPolling(
        state_dir=state_dir,
        on_history_gap=on_gap,  # type: ignore[arg-type]
        api=_FakeApi(),  # type: ignore[arg-type]
        group_id=GROUP_ID,
    )


def test_ts_state_path_uses_controlled_runtime_dir(tmp_path: Path) -> None:
    polling = _polling(tmp_path)

    assert polling.ts_state_path == tmp_path / "bot-polling" / f"{GROUP_ID}.json"


def test_skip_old_events_disabled() -> None:
    polling = RuntimePathBotPolling(state_dir=Path("/tmp/x"), group_id=GROUP_ID)

    assert polling.skip_old_events is False


def test_restore_reads_persisted_ts_from_controlled_dir(tmp_path: Path) -> None:
    polling = _polling(tmp_path)
    polling.ts_state_path.parent.mkdir(parents=True, exist_ok=True)
    polling.ts_state_path.write_text('{"ts": "4242"}', encoding="utf-8")

    restored = polling.restore_server_ts({"ts": "1", "server": "s", "key": "k"})

    assert restored["ts"] == "4242"


def test_save_writes_ts_for_restore_on_restart(tmp_path: Path) -> None:
    first = _polling(tmp_path)
    first.save_server_ts({"ts": "9999"})

    second = _polling(tmp_path)

    assert second.restore_server_ts({"ts": "1"})["ts"] == "9999"


def test_corrupt_state_file_is_ignored_softly(tmp_path: Path) -> None:
    polling = _polling(tmp_path)
    polling.ts_state_path.parent.mkdir(parents=True, exist_ok=True)
    polling.ts_state_path.write_text("not json", encoding="utf-8")

    restored = polling.restore_server_ts({"ts": "7"})

    assert restored["ts"] == "7"


def test_history_gap_kind_mapping() -> None:
    assert history_gap_kind(1) == "history_outdated"
    assert history_gap_kind(3) == "information_lost"
    assert history_gap_kind(2) == "unknown"
    assert history_gap_kind(4) == "unknown"
    assert history_gap_kind(99) == "unknown"


class _RecordingGapCallback:
    def __init__(self) -> None:
        self.kinds: list[str] = []

    async def __call__(self, kind: str) -> None:
        self.kinds.append(kind)


async def _handle_failed(polling: RuntimePathBotPolling, event: dict[str, Any]) -> dict[str, Any]:
    server = {"ts": "1", "server": "s", "key": "k"}
    return await polling.handle_failed_event(server, event)


async def test_failed_1_notifies_once_per_episode(tmp_path: Path) -> None:
    callback = _RecordingGapCallback()
    polling = _polling(tmp_path, callback)

    await _handle_failed(polling, {"failed": 1, "ts": "100"})
    await _handle_failed(polling, {"failed": 1, "ts": "100"})

    assert callback.kinds == ["history_outdated"]


async def test_failed_3_reports_information_lost(tmp_path: Path) -> None:
    callback = _RecordingGapCallback()
    polling = _polling(tmp_path, callback)

    await _handle_failed(polling, {"failed": 3})

    assert callback.kinds == ["information_lost"]


async def test_key_expired_and_invalid_version_are_not_gaps(tmp_path: Path) -> None:
    callback = _RecordingGapCallback()
    polling = _polling(tmp_path, callback)

    await _handle_failed(polling, {"failed": 2})
    await _handle_failed(polling, {"failed": 4, "min_version": 1, "max_version": 3})

    assert callback.kinds == []


async def test_normal_event_after_gap_resets_the_episode(tmp_path: Path) -> None:
    callback = _RecordingGapCallback()
    polling = _polling(tmp_path, callback)

    await _handle_failed(polling, {"failed": 1, "ts": "100"})
    polling._gap_reported = False  # what listen() does when a normal event flows through
    await _handle_failed(polling, {"failed": 1, "ts": "100"})

    assert callback.kinds == ["history_outdated", "history_outdated"]
