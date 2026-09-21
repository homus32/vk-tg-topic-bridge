"""Wall forwarding tests: toggle-gated, wall dedup key, no reaction, fail-closed."""

from __future__ import annotations

from dataclasses import replace
from types import TracebackType
from typing import Self

from tests.acceptance._fakes import (
    FakeAliasesRepository,
    FakeSettingsRepository,
    FakeTopicsRepository,
)
from tests.acceptance._ledger import DeliveryLedger
from vk_topic_bridge.application.dto.delivery import DeliveryRecord
from vk_topic_bridge.application.forwarding.forward_wall import ForwardWallPost
from vk_topic_bridge.domain.enums import AttachmentKind, PublicationStatus, SourceType
from vk_topic_bridge.domain.publication import (
    OperationOutcome,
    OperationStatus,
    PublicationPlan,
)
from vk_topic_bridge.domain.value_objects import (
    Attachment,
    Author,
    SourceWallPost,
    TopicInfo,
)

CHAT_ID = -1001234567890
WALL_TOPIC_ID = 12
GROUP_ID = 42
OWNER_ID = -999
POST_ID = 5

AUTHOR = Author(user_id=OWNER_ID, first_name="Сообщество", last_name="", screen_name=None)


def _wall_post(
    text: str = "текст поста", *, attachments: tuple[Attachment, ...] = ()
) -> SourceWallPost:
    return SourceWallPost(
        source_type=SourceType.VK_WALL,
        source_key=f"{GROUP_ID}:{OWNER_ID}:{POST_ID}",
        group_id=GROUP_ID,
        owner_id=OWNER_ID,
        post_id=POST_ID,
        author=AUTHOR,
        text=text,
        url=f"https://vk.com/wall{OWNER_ID}_{POST_ID}",
        attachments=attachments,
    )


class FakeUow:
    def __init__(self, state: object) -> None:
        self.bridge_settings = FakeSettingsRepository(state)  # type: ignore[arg-type]
        self.telegram_topics = FakeTopicsRepository()
        self.vk_aliases = FakeAliasesRepository()
        self.deliveries = DeliveryLedger()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class FakePlanPublisher:
    def __init__(
        self,
        *,
        status: OperationStatus = OperationStatus.PUBLISHED,
        message_ids: tuple[int, ...] = (701,),
    ) -> None:
        self.status = status
        self.message_ids = message_ids
        self.plans: list[PublicationPlan] = []

    async def publish_plan(self, plan: PublicationPlan) -> tuple[OperationOutcome, ...]:
        self.plans.append(plan)
        return tuple(
            OperationOutcome(operation=operation, status=self.status, message_ids=self.message_ids)
            for operation in plan.operations
        )


class RuntimeStalePublisher(FakePlanPublisher):
    def __init__(self, *, fallback_status: OperationStatus = OperationStatus.PUBLISHED) -> None:
        super().__init__()
        self.fallback_status = fallback_status

    async def publish_plan(self, plan: PublicationPlan) -> tuple[OperationOutcome, ...]:
        self.plans.append(plan)
        status = OperationStatus.FAILED_PERMANENT if len(self.plans) == 1 else self.fallback_status
        error_code = "telegram_topic_not_found" if len(self.plans) == 1 else None
        error_message = "Bad Request: message thread not found" if error_code else None
        message_ids = self.message_ids if status is OperationStatus.PUBLISHED else ()
        return tuple(
            OperationOutcome(
                operation=operation,
                status=status,
                message_ids=message_ids,
                error_code=error_code,
                error_message=error_message,
            )
            for operation in plan.operations
        )


class FakeNotifier:
    def __init__(self) -> None:
        self.all_texts: list[str] = []

    async def notify_all(self, text: str) -> None:
        self.all_texts.append(text)

    async def notify_others(self, initiator_id: int, text: str) -> None:
        raise AssertionError("wall forwarding never broadcasts to others explicitly")


class FakeDownloader:
    def __init__(self) -> None:
        self.resolved: list[tuple[str, AttachmentKind]] = []

    async def resolve_url(self, attachment: Attachment) -> str:
        source_ref = attachment.source_ref or ""
        self.resolved.append((source_ref, attachment.kind))
        return f"https://cdn.example/{source_ref}"

    async def download(self, attachment: Attachment, url: str) -> str:
        source_ref = attachment.source_ref or ""
        _ = url
        return f"/tmp/{source_ref}.bin"


def _topics(*, include_wall: bool = True, closed: bool = False) -> list[TopicInfo]:
    topics = [
        TopicInfo(topic_id=None, title="General", is_general=True, is_closed=False, is_hidden=False)
    ]
    if include_wall:
        topics.append(
            TopicInfo(
                topic_id=WALL_TOPIC_ID,
                title="Стена",
                is_general=False,
                is_closed=closed,
                is_hidden=False,
            )
        )
    return topics


def _registered_state(
    *,
    wall_topic_id: int | None = WALL_TOPIC_ID,
    wall_enabled: bool = True,
    configured: bool = True,
):
    from vk_topic_bridge.application.dto.settings import BridgeSettingsState

    base = BridgeSettingsState.defaults()
    return replace(
        base,
        telegram_chat_id=CHAT_ID,
        telegram_chat_title="Тест",
        auto_forward_wall=wall_enabled,
        telegram_wall_topic_id=wall_topic_id,
        telegram_wall_topic_configured=configured,
    )


def _use_case(
    uow: FakeUow,
    *,
    publisher: FakePlanPublisher | None = None,
    downloader: FakeDownloader | None = None,
    topics: list[TopicInfo] | None = None,
    notifier: FakeNotifier | None = None,
) -> tuple[ForwardWallPost, FakePlanPublisher, FakeUow]:
    plan_publisher = publisher or FakePlanPublisher()
    uow.telegram_topics.by_chat[CHAT_ID] = list(topics if topics is not None else _topics())
    use_case = ForwardWallPost(
        uow_factory=lambda: uow,
        plan_publisher=plan_publisher,
        downloader=downloader,
        notifier=notifier,
    )
    return use_case, plan_publisher, uow


def _records(uow: FakeUow) -> list[DeliveryRecord]:
    return list(uow.deliveries.records.values())


async def test_wall_publishes_to_wall_destination() -> None:
    uow = FakeUow(_registered_state())
    use_case, publisher, _ = _use_case(uow)

    outcome = await use_case.execute(_wall_post())

    assert outcome.published is True
    plan = publisher.plans[0]
    assert plan.base.message_thread_id == WALL_TOPIC_ID
    assert plan.base.chat_id == CHAT_ID


async def test_wall_publication_contains_tag_and_original_url() -> None:
    uow = FakeUow(_registered_state())
    use_case, publisher, _ = _use_case(uow)

    await use_case.execute(_wall_post())

    html = publisher.plans[0].base.html_text
    assert "текст поста" in html
    assert "#изстенывк" in html
    assert f"https://vk.com/wall{OWNER_ID}_{POST_ID}" in html


async def test_wall_publication_keeps_link_when_text_empty() -> None:
    uow = FakeUow(_registered_state())
    use_case, publisher, _ = _use_case(uow)

    await use_case.execute(_wall_post(""))

    html = publisher.plans[0].base.html_text
    assert f"https://vk.com/wall{OWNER_ID}_{POST_ID}" in html
    assert "#изстенывк" in html


async def test_wall_uses_vk_wall_source_key_and_automatic_intent() -> None:
    uow = FakeUow(_registered_state())
    use_case, _, _ = _use_case(uow)

    await use_case.execute(_wall_post())

    record = _records(uow)[0]
    assert record.source_type == SourceType.VK_WALL.value
    assert record.source_key == f"{GROUP_ID}:{OWNER_ID}:{POST_ID}"
    assert record.intent == "automatic"
    assert record.publication_status is PublicationStatus.PUBLISHED


async def test_wall_toggle_off_skips_without_reserve() -> None:
    uow = FakeUow(_registered_state(wall_enabled=False))
    use_case, publisher, _ = _use_case(uow)

    outcome = await use_case.execute(_wall_post())

    assert outcome.skipped is True
    assert outcome.reason == "filtered"
    assert publisher.plans == []
    assert _records(uow) == []


async def test_wall_unregistered_chat_skips() -> None:
    from vk_topic_bridge.application.dto.settings import BridgeSettingsState

    uow = FakeUow(BridgeSettingsState.defaults())
    use_case, publisher, _ = _use_case(uow)

    outcome = await use_case.execute(_wall_post())

    assert outcome.skipped is True
    assert outcome.reason == "unregistered"
    assert publisher.plans == []


async def test_wall_unconfigured_destination_skips_all_io() -> None:
    uow = FakeUow(_registered_state(configured=False))
    use_case, publisher, _ = _use_case(uow)

    outcome = await use_case.execute(_wall_post())

    assert outcome.skipped is True
    assert outcome.reason == "unconfigured"
    assert publisher.plans == []
    assert _records(uow) == []


async def test_wall_general_destination_omits_thread_id() -> None:
    uow = FakeUow(_registered_state(wall_topic_id=None))
    use_case, publisher, _ = _use_case(uow, topics=_topics(include_wall=False))

    await use_case.execute(_wall_post())

    assert publisher.plans[0].base.message_thread_id is None


async def test_wall_missing_topic_falls_back_to_general_and_notifies() -> None:
    notifier = FakeNotifier()
    uow = FakeUow(_registered_state())
    use_case, publisher, _ = _use_case(uow, topics=_topics(include_wall=False), notifier=notifier)

    outcome = await use_case.execute(_wall_post())

    assert outcome.published is True
    assert publisher.plans[0].base.message_thread_id is None
    assert len(notifier.all_texts) == 1
    assert "General" in notifier.all_texts[0]


async def test_wall_closed_topic_falls_back_to_general() -> None:
    notifier = FakeNotifier()
    uow = FakeUow(_registered_state())
    use_case, publisher, _ = _use_case(uow, topics=_topics(closed=True), notifier=notifier)

    outcome = await use_case.execute(_wall_post())

    assert outcome.published is True
    assert publisher.plans[0].base.message_thread_id is None
    assert "закрыт" in notifier.all_texts[0]


async def test_wall_runtime_stale_topic_falls_back_to_general_and_notifies() -> None:
    notifier = FakeNotifier()
    publisher = RuntimeStalePublisher()
    uow = FakeUow(_registered_state())
    use_case, _, _ = _use_case(uow, publisher=publisher, notifier=notifier)

    outcome = await use_case.execute(_wall_post())

    assert outcome.published is True
    assert [plan.base.message_thread_id for plan in publisher.plans] == [WALL_TOPIC_ID, None]
    assert len(notifier.all_texts) == 1
    assert "General" in notifier.all_texts[0]
    records = _records(uow)
    named_record = next(
        record for record in records if record.destination_topic_id == WALL_TOPIC_ID
    )
    fallback_record = next(record for record in records if record.destination_topic_id is None)
    assert named_record.publication_status is PublicationStatus.FAILED_PERMANENT
    assert fallback_record.publication_status is PublicationStatus.PUBLISHED
    assert fallback_record.source_key.endswith(":general-fallback")


async def test_wall_runtime_general_fallback_keeps_ambiguous_fail_closed() -> None:
    notifier = FakeNotifier()
    publisher = RuntimeStalePublisher(fallback_status=OperationStatus.ACCEPTED_UNKNOWN)
    uow = FakeUow(_registered_state())
    use_case, _, _ = _use_case(uow, publisher=publisher, notifier=notifier)

    outcome = await use_case.execute(_wall_post())

    assert outcome.published is False
    assert outcome.reason == "ambiguous"
    assert [plan.base.message_thread_id for plan in publisher.plans] == [WALL_TOPIC_ID, None]
    records = _records(uow)
    assert any(
        record.publication_status is PublicationStatus.FAILED_PERMANENT for record in records
    )
    assert any(record.publication_status is PublicationStatus.AMBIGUOUS for record in records)
    assert len(notifier.all_texts) == 1
    assert "Проблема с доставкой" in notifier.all_texts[0]  # noqa: RUF001


async def test_wall_never_notifies_on_healthy_destination() -> None:
    notifier = FakeNotifier()
    uow = FakeUow(_registered_state())
    use_case, _, _ = _use_case(uow, topics=_topics(), notifier=notifier)

    await use_case.execute(_wall_post())

    assert notifier.all_texts == []


async def test_wall_never_sets_reaction() -> None:
    uow = FakeUow(_registered_state())
    use_case, _, _ = _use_case(uow)

    await use_case.execute(_wall_post())

    record = _records(uow)[0]
    from vk_topic_bridge.domain.enums import ReactionStatus

    assert record.reaction_status is ReactionStatus.NOT_DUE


async def test_wall_attachment_becomes_media_operation() -> None:
    attachment = Attachment(
        kind=AttachmentKind.PHOTO, file_name="p.jpg", size_bytes=1000, source_ref=f"{OWNER_ID}_11"
    )
    downloader = FakeDownloader()
    uow = FakeUow(_registered_state())
    use_case, publisher, _ = _use_case(uow, downloader=downloader)

    await use_case.execute(_wall_post(attachments=(attachment,)))

    assert downloader.resolved == [(f"{OWNER_ID}_11", AttachmentKind.PHOTO)]
    from vk_topic_bridge.domain.publication import OperationKind

    kinds = [operation.kind for operation in publisher.plans[0].operations]
    assert OperationKind.PHOTO in kinds


async def test_wall_permanent_failure_is_recorded() -> None:
    uow = FakeUow(_registered_state())
    use_case, _, _ = _use_case(
        uow, publisher=FakePlanPublisher(status=OperationStatus.FAILED_PERMANENT)
    )

    outcome = await use_case.execute(_wall_post())

    assert outcome.published is False
    assert _records(uow)[0].publication_status is PublicationStatus.FAILED_PERMANENT


async def test_wall_ambiguous_is_never_retried() -> None:
    uow = FakeUow(_registered_state())
    use_case, _, _ = _use_case(
        uow, publisher=FakePlanPublisher(status=OperationStatus.ACCEPTED_UNKNOWN)
    )

    outcome = await use_case.execute(_wall_post())

    assert outcome.published is False
    assert outcome.reason == "ambiguous"
    record = _records(uow)[0]
    assert record.publication_status is PublicationStatus.AMBIGUOUS
    assert record.review_required is True


async def test_wall_dedup_uses_wall_key_not_message_key() -> None:
    uow = FakeUow(_registered_state())
    use_case, _, _ = _use_case(uow)

    await use_case.execute(_wall_post())

    keys = list(uow.deliveries.records.keys())
    assert len(keys) == 1
    assert keys[0].startswith("vk_wall:")


async def test_duplicate_wall_event_reuses_published_delivery() -> None:
    uow = FakeUow(_registered_state())
    use_case, publisher, _ = _use_case(uow)

    first = await use_case.execute(_wall_post())
    second = await use_case.execute(_wall_post())

    assert first.published is True
    assert second.published is True
    assert second.reason == "already_published"
    assert len(publisher.plans) == 1
    assert len(_records(uow)) == 1
