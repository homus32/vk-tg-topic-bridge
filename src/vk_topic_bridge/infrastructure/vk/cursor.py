"""Persistent VK Long Poll cursor transport (skip_old_events=False).

Frozen decision: persistent cursor mode is the final policy. VKBottle already persists
the cursor as JSON; the only change needed is the storage path — a controlled gitignored
runtime dir instead of ``.vkbottle/`` in the project root. The cursor and the SQLite
delivery ledger are NOT one transaction and must never be advertised as one.

Gap diagnostics observation point (verified against the pinned vkbottle 4.11.0 source,
``vkbottle/polling/base.py``): ``BasePolling.listen`` consumes ``failed`` events
internally through ``handle_failed_event`` and never yields them to consumers, so this
override is the only place a failed code can be observed — not a wrapper around
``listen()``. Dedup is per gap episode: one notification until a normal event flows
through ``listen`` again.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from vkbottle.polling import BotPolling

if TYPE_CHECKING:
    from vkbottle.api import ABCAPI

logger = logging.getLogger(__name__)

_GAP_KINDS = {1: "history_outdated", 3: "information_lost"}


class RuntimePathBotPolling(BotPolling):
    """``BotPolling`` with ``skip_old_events=False`` and a controlled state directory."""

    def __init__(
        self,
        *,
        state_dir: Path,
        on_history_gap: Callable[[str], Awaitable[None]] | None = None,
        api: ABCAPI | None = None,
        group_id: int | None = None,
    ) -> None:
        super().__init__(api=api, group_id=group_id, skip_old_events=False)
        self._state_dir = Path(state_dir)
        self._on_history_gap = on_history_gap
        self._gap_reported = False

    @property
    def ts_state_path(self) -> Path:
        if self.group_id is None:
            msg = "Bot polling state path is unavailable before group_id is resolved"
            raise RuntimeError(msg)
        return self._state_dir / "bot-polling" / f"{self.group_id}.json"

    async def handle_failed_event(
        self, server: dict[str, Any], event: dict[str, Any]
    ) -> dict[str, Any]:
        failed = event.get("failed")
        kind = (
            history_gap_kind(failed)
            if isinstance(failed, int) and not isinstance(failed, bool)
            else "unknown"
        )
        if kind != "unknown" and not self._gap_reported:
            self._gap_reported = True
            logger.warning("vk long poll history gap (%s); discarded events count unknown", kind)
            if self._on_history_gap is not None:
                await self._on_history_gap(kind)
        return await super().handle_failed_event(server, event)

    async def listen(self) -> AsyncGenerator[dict[str, Any]]:
        logger.info("vk persistent cursor polling started", extra={"poller": type(self).__name__})
        self._gap_reported = False
        async for event in super().listen():
            self._gap_reported = False
            yield event


def history_gap_kind(failed_code: int) -> str:
    """Map a VK Long Poll ``failed`` code onto the owner-facing gap kind.

    Codes 2/4 (key expired / invalid version) are reconnect concerns handled inside
    VKBottle, not history gaps. The discarded count is always unknown.
    """
    return _GAP_KINDS.get(failed_code, "unknown")
