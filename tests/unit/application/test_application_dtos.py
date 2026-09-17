"""Contract tests for application DTOs and application error declarations."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime

import pytest

from vk_topic_bridge.application.dto.delivery import (
    DeliveryRecord,
    ReserveOutcome,
    ReserveRequest,
)
from vk_topic_bridge.application.dto.infrastructure import ChatAccessInfo, LongPollInfo
from vk_topic_bridge.application.dto.readiness import ReadinessState
from vk_topic_bridge.application.dto.settings import BridgeSettingsState, ToggleKind
from vk_topic_bridge.application.errors import (
    ProvisioningError,
    PublicationAmbiguousError,
    PublicationRejectedError,
    ReadinessError,
)
from vk_topic_bridge.domain.enums import PublicationStatus, ReactionStatus, SourceType
from vk_topic_bridge.domain.errors import DomainError

_NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


def _mutate(instance: object, name: str, value: object) -> None:
    setattr(instance, name, value)


def _delivery_record() -> DeliveryRecord:
    return DeliveryRecord(
        id=1,
        source_type=SourceType.VK_MESSAGE.value,
        source_key="42:100:7",
        publication_status=PublicationStatus.RESERVED,
        reaction_status=ReactionStatus.NOT_DUE,
        claim_token=None,
        lease_expires_at=None,
        send_started_at=None,
        destination_chat_id=-100123,
        destination_topic_id=7,
        telegram_message_ids=(11, 12),
        attempts=0,
        last_error_code=None,
        last_error=None,
        payload_hash="payload-hash",
        ambiguous_at=None,
        review_required=False,
        created_at=_NOW,
        updated_at=_NOW,
        completed_at=None,
    )


def test_delivery_record_mirrors_ledger_columns() -> None:
    record = _delivery_record()

    assert record.id == 1
    assert record.source_type == "vk_message"
    assert record.source_key == "42:100:7"
    assert record.publication_status is PublicationStatus.RESERVED
    assert record.reaction_status is ReactionStatus.NOT_DUE
    assert record.destination_chat_id == -100123
    assert record.destination_topic_id == 7
    assert record.telegram_message_ids == (11, 12)
    assert isinstance(record.telegram_message_ids, tuple)
    assert record.attempts == 0
    assert record.payload_hash == "payload-hash"
    assert record.review_required is False
    assert record.completed_at is None


def test_delivery_record_is_frozen() -> None:
    record = _delivery_record()

    with pytest.raises(FrozenInstanceError):
        _mutate(record, "id", 99)


def test_reserve_request_carries_destination_and_payload_hash() -> None:
    request = ReserveRequest(
        source_type=SourceType.VK_WALL,
        source_key="42:-10:7",
        destination_chat_id=-100123,
        destination_topic_id=None,
        payload_hash="hash",
    )

    assert request.source_type is SourceType.VK_WALL
    assert request.destination_topic_id is None
    assert isinstance(request.payload_hash, str)

    with pytest.raises(FrozenInstanceError):
        _mutate(request, "source_key", "other")


def test_reserve_outcome_pairs_created_flag_with_record() -> None:
    outcome = ReserveOutcome(created=True, record=_delivery_record())

    assert outcome.created is True
    assert outcome.record.source_key == "42:100:7"

    with pytest.raises(FrozenInstanceError):
        _mutate(outcome, "created", False)


def test_settings_defaults_enable_all_toggles_and_leave_chat_unset() -> None:
    state = BridgeSettingsState.defaults()

    assert state.telegram_chat_id is None
    assert state.telegram_chat_title is None
    assert state.auto_forward_all is True
    assert state.auto_forward_hashtags is True
    assert state.auto_forward_wall is True
    assert state.telegram_messages_topic_id is None
    assert state.telegram_wall_topic_id is None


def test_settings_state_is_frozen_and_replace_friendly() -> None:
    state = BridgeSettingsState.defaults()
    updated = replace(state, auto_forward_all=False, telegram_chat_id=-100123)

    assert state.auto_forward_all is True
    assert state.telegram_chat_id is None
    assert updated.auto_forward_all is False
    assert updated.telegram_chat_id == -100123

    with pytest.raises(FrozenInstanceError):
        _mutate(state, "auto_forward_all", False)


def test_toggle_kind_values_match_persisted_kinds() -> None:
    assert ToggleKind.ALL.value == "all"
    assert ToggleKind.HASHTAGS.value == "hashtags"
    assert ToggleKind.WALL.value == "wall"


def test_infrastructure_dtos_are_frozen_value_objects() -> None:
    long_poll = LongPollInfo(server="lp.vk.com", key="abc", ts="42", enabled=True)
    access = ChatAccessInfo(entity_id=-100123, is_forum=True)

    assert long_poll.enabled is True
    assert access.is_forum is True

    with pytest.raises(FrozenInstanceError):
        _mutate(long_poll, "ts", "43")
    with pytest.raises(FrozenInstanceError):
        _mutate(access, "is_forum", False)


def test_readiness_state_is_ordered_by_rank() -> None:
    assert ReadinessState.CORE_READY.value == "core_ready"
    assert ReadinessState.CHAT_REGISTERED.value == "chat_registered"
    assert ReadinessState.TOPICS_READY.value == "topics_ready"
    assert ReadinessState.DESTINATION_CONFIRMED.value == "destination_confirmed"
    assert ReadinessState.FORWARDING_ENABLED.value == "forwarding_enabled"
    assert [state.rank for state in ReadinessState] == [0, 1, 2, 3, 4]


def test_publication_errors_carry_optional_code() -> None:
    ambiguous = PublicationAmbiguousError("no response after send intent", code="timeout")
    rejected = PublicationRejectedError("message thread not found")
    bare = PublicationAmbiguousError()

    assert isinstance(ambiguous, DomainError)
    assert ambiguous.code == "timeout"
    assert "no response" in str(ambiguous)
    assert isinstance(rejected, DomainError)
    assert rejected.code is None
    assert isinstance(bare.code, type(None))


def test_provisioning_and_readiness_errors_are_domain_errors() -> None:
    assert isinstance(ProvisioningError("empty topic list"), DomainError)
    assert isinstance(ReadinessError("gate below forwarding_enabled"), DomainError)
    assert issubclass(PublicationAmbiguousError, DomainError)
    assert issubclass(PublicationRejectedError, DomainError)
