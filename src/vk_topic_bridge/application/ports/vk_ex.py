"""VK-facing port extensions for the finish plan (append-only)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class VkManualUiPort(Protocol):
    """VK API surface needed by the VK presentation layer (reuses RawVkApi request)."""

    async def send_user_message(self, user_id: int, text: str, keyboard_json: str | None) -> int:
        """``messages.send`` to one user DM; returns the sent message id."""
        ...


# Media download contract lives in telegram_ex.py ( VkMediaDownloaderPort ); the
# forwarding use case (tasks 15/16) downloads BEFORE planning and passes
# ``PlannedMedia`` (successfully downloaded items) to ``plan_publication``; failed
# downloads become per-item warning lines in the text (task 8
# ``media_failure_warning``), never OperationOutcome values.
VkMediaFacade = object
