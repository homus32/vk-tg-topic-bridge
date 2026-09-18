"""No-configuration reconciliation (finish plan): automatic silent no-ops.

Draft table: with no chat, or with a never-configured destination, the corresponding
automatic flow silently skips — no publication, no ledger row, no notification, no 👍.
"""

from __future__ import annotations

import logging

import pytest

from tests.acceptance._fakes import make_forwarding_harness, make_source


async def test_unregistered_chat_skips_silently(caplog: pytest.LogCaptureFixture) -> None:
    harness = make_forwarding_harness(registered=False, with_notifier=True)

    with caplog.at_level(logging.DEBUG):
        outcome = await harness.use_case.execute(make_source("@all новость"))

    assert outcome.skipped is True
    assert harness.publisher.publications == []
    assert harness.publisher.sent_text == []
    assert harness.ledger.records == {}
    assert harness.vk.reaction_calls == []
    assert "telegram_chat_not_registered" in caplog.text


async def test_unconfigured_destination_skips_silently(caplog: pytest.LogCaptureFixture) -> None:
    harness = make_forwarding_harness(topic_configured=False, with_notifier=True)

    with caplog.at_level(logging.DEBUG):
        outcome = await harness.use_case.execute(make_source("@all новость"))

    assert outcome.skipped is True
    assert harness.publisher.publications == []
    assert harness.publisher.sent_text == []
    assert harness.ledger.records == {}
    assert harness.vk.reaction_calls == []
    assert "destination_not_configured" in caplog.text


async def test_unconfigured_destination_does_not_affect_other_feature_snapshot() -> None:
    harness = make_forwarding_harness(topic_configured=False)

    outcome = await harness.use_case.execute(make_source("@all новость"))

    assert outcome.reason == "unconfigured"
