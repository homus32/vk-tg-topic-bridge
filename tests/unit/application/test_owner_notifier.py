"""Contract tests for OwnerNotifier and fallback notification text (plan task 4)."""

from vk_topic_bridge.application.notifications.owner_notifier import (
    OwnerNotifier,
    fallback_notification_text,
)


class _FakeNotifierPort:
    def __init__(self, failing: frozenset[int] = frozenset()) -> None:
        self.sent: list[tuple[int, str, int | None]] = []
        self._failing = failing

    async def send_text(self, chat_id: int, text: str, message_thread_id: int | None = None) -> int:
        if chat_id in self._failing:
            raise RuntimeError(f"send failed for {chat_id}")
        self.sent.append((chat_id, text, message_thread_id))
        return len(self.sent)


async def test_notify_all_sends_to_every_owner() -> None:
    port = _FakeNotifierPort()
    notifier = OwnerNotifier(owner_ids=frozenset({7, 8, 9}), port=port)

    await notifier.notify_all("hello")

    assert sorted(recipient for recipient, _, _ in port.sent) == [7, 8, 9]
    assert all(text == "hello" for _, text, _ in port.sent)
    assert all(thread is None for _, _, thread in port.sent)


async def test_notify_others_skips_initiator() -> None:
    port = _FakeNotifierPort()
    notifier = OwnerNotifier(owner_ids=frozenset({7, 8, 9}), port=port)

    await notifier.notify_others(7, "broadcast")

    assert sorted(recipient for recipient, _, _ in port.sent) == [8, 9]


async def test_notify_others_with_unknown_initiator_sends_to_all() -> None:
    port = _FakeNotifierPort()
    notifier = OwnerNotifier(owner_ids=frozenset({7, 8}), port=port)

    await notifier.notify_others(999, "broadcast")

    assert sorted(recipient for recipient, _, _ in port.sent) == [7, 8]


async def test_failing_owner_does_not_block_the_rest() -> None:
    port = _FakeNotifierPort(failing=frozenset({8}))
    notifier = OwnerNotifier(owner_ids=frozenset({7, 8, 9}), port=port)

    await notifier.notify_all("hello")

    assert sorted(recipient for recipient, _, _ in port.sent) == [7, 9]


async def test_single_owner_failure_is_swallowed() -> None:
    port = _FakeNotifierPort(failing=frozenset({7}))
    notifier = OwnerNotifier(owner_ids=frozenset({7}), port=port)

    await notifier.notify_all("hello")

    assert port.sent == []


def test_fallback_notification_text_mentions_facts_and_plain_text() -> None:
    text = fallback_notification_text(feature="messages", topic_id=42, reason="closed")

    assert "42" in text
    assert "закрыт" in text
    assert "General" in text
    assert "сообщений" in text
    assert "<" not in text
    assert "&" not in text


def test_fallback_notification_text_wall_feature() -> None:
    text = fallback_notification_text(feature="wall", topic_id=7, reason="missing")

    assert "стены" in text
    assert "7" in text
    assert "не найден" in text
