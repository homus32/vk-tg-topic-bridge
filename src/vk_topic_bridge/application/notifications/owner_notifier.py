"""Owner notification broadcast: direct confirmation + other-owners broadcast.

Notification policy (frozen draft): actionable high-signal events only — toggle
changes, General fallback, history gap, exhausted retry/failed_permanent, ambiguous
review. Per-attachment warnings stay inside the publication.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Protocol, runtime_checkable

from vk_topic_bridge.application.ports.telegram_ex import TelegramNotifierPort

logger = logging.getLogger(__name__)

_FEATURE_LABELS = {"messages": "сообщений", "wall": "постов стены"}
_REASON_LABELS = {"missing": "не найден", "closed": "закрыт", "hidden": "скрыт"}


@runtime_checkable
class NotifierLike(Protocol):
    """The only notifier surface automatic forwarding needs: one broadcast call."""

    async def notify_all(self, text: str) -> None: ...


class OwnerNotifier:
    """Sends one owner-facing message to every configured owner.

    ``notify_all(text)`` sends ``text`` (plain, no parse_mode) to every id in
    ``owner_ids``; failures for individual owners are logged and never raise, so one
    unreachable owner cannot suppress the rest of the broadcast. ``notify_others``
    skips ``initiator_id`` because the initiator already received the direct
    confirmation/keyboard update.
    """

    def __init__(
        self,
        owner_ids: frozenset[int],
        port: TelegramNotifierPort,
    ) -> None:
        self._owner_ids = owner_ids
        self._port = port

    async def notify_all(self, text: str) -> None:
        logger.debug(
            "owner notification broadcast started",
            extra={"owner_count": len(self._owner_ids), "text_length": len(text)},
        )
        for owner_id in sorted(self._owner_ids):
            await self._send_one(owner_id, text)
        logger.debug("owner notification broadcast completed")

    async def notify_others(self, initiator_id: int, text: str) -> None:
        logger.debug(
            "owner notification broadcast to others started",
            extra={"owner_count": len(self._owner_ids), "owner_id": initiator_id},
        )
        for owner_id in sorted(self._owner_ids):
            if owner_id == initiator_id:
                continue
            await self._send_one(owner_id, text)
        logger.debug("owner notification broadcast to others completed")

    async def _send_one(self, owner_id: int, text: str) -> None:
        try:
            await self._port.send_text(owner_id, text)
            logger.debug("owner notification sent", extra={"owner_id": owner_id})
        except Exception:
            logger.exception("owner notification failed for %s", owner_id)


def fallback_notification_text(
    *,
    feature: str,
    topic_id: int,
    reason: str,
) -> str:
    """Plain-text owner notification for an automatic General fallback (US-22)."""
    feature_label = _FEATURE_LABELS.get(feature, feature)
    reason_label = _REASON_LABELS.get(reason, reason)
    return (
        f"Топик назначения {feature_label} недоступен: топик {topic_id} ({reason_label}).\n"
        "Публикация отправлена в General."
    )


_STATUS_LABELS = {
    "ambiguous": "результат не подтверждён Telegram",
    "failed_permanent": "публикация отклонена Telegram",
}


def attention_notification_text(*, status: str, delivery_id: int) -> str:
    """Plain-text owner attention for a terminal delivery outcome.

    ``status`` is ``ambiguous`` (review required, never auto-retried) or
    ``failed_permanent``; the message names the status and the delivery id so the owner
    can find it under delivery diagnostics. Plain text only.
    """
    label = _STATUS_LABELS.get(status, status)
    return (
        f"Проблема с доставкой (запись #{delivery_id}): {label}.\n"  # noqa: RUF001
        "Подробности — в разделе «Диагностика доставки»."
    )


_GAP_LABELS = {
    "history_outdated": "часть истории Long Poll устарела",
    "information_lost": "часть событий VK потеряна",
}


def history_gap_notification_text(*, kind: str) -> str:
    """Plain-text owner notification for one VK Long Poll history gap episode."""
    label = _GAP_LABELS.get(kind, kind)
    return (
        f"VK Long Poll: {label}.\n"
        "Точное число пропущенных событий неизвестно; приём продолжается с нового курсора."  # noqa: RUF001
    )


# Re-exported for typing convenience in bootstrap wiring.
NotifierPortFactory = Callable[[], TelegramNotifierPort]
_Group = Iterable[int]
