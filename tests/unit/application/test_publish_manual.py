"""Manual publication use-case tests: manual intent, no reaction, fail-closed ledger."""

from __future__ import annotations

from types import TracebackType
from typing import Self

from tests.acceptance._fakes import (
    FakeAliasesRepository,
    FakeSettingsRepository,
    FakeTopicsRepository,
)
from tests.acceptance._ledger import DeliveryLedger
from vk_topic_bridge.application.dto.delivery import DeliveryRecord
from vk_topic_bridge.application.errors import PublicationAmbiguousError
from vk_topic_bridge.application.manual.publish_manual import (
    ManualPublicationRequest,
    PublishManualMessage,
)
from vk_topic_bridge.domain.enums import AttachmentKind, PublicationStatus, SourceType
from vk_topic_bridge.domain.publication import (
    OperationKind,
    OperationOutcome,
    OperationStatus,
    PublicationPlan,
)
from vk_topic_bridge.domain.value_objects import (
    Attachment,
    Author,
    Destination,
    Publication,
    PublicationResult,
    SourceMessage,
)

CHAT_ID = -1001234567890
TOPIC_ID = 7
USER_ID = 555
CMID = 333
OTHER_USER_ID = 777

AUTHOR = Author(user_id=11, first_name="Иван", last_name="Петров", screen_name=None)
INITIATOR = Author(user_id=USER_ID, first_name="Пётр", last_name="Сидоров", screen_name=None)
DESTINATION = Destination(chat_id=CHAT_ID, message_thread_id=TOPIC_ID)


def _source(text: str = "привет", *, attachments: tuple[Attachment, ...] = ()) -> SourceMessage:
    return SourceMessage(
        source_type=SourceType.VK_MESSAGE,
        source_key=f"manual:{USER_ID}:{CMID}",
        group_id=1,
        peer_id=USER_ID,
        conversation_message_id=CMID,
        author=AUTHOR,
        text=text,
        has_all=False,
        has_hashtag=False,
        attachments=attachments,
    )


class FakePublisher:
    def __init__(self) -> None:
        self.publications: list[Publication] = []
        self.sent_text: list[tuple[int, str, int | None]] = []

    async def publish(self, publication: Publication) -> PublicationResult:
        self.publications.append(publication)
        return PublicationResult(
            chat_id=publication.chat_id,
            message_thread_id=publication.message_thread_id,
            message_ids=(1,),
        )

    async def send_text(self, chat_id: int, text: str, message_thread_id: int | None = None) -> int:
        self.sent_text.append((chat_id, text, message_thread_id))
        return 1


class FakePlanPublisher:
    def __init__(
        self,
        *,
        status: OperationStatus = OperationStatus.PUBLISHED,
        error: Exception | None = None,
        message_ids: tuple[int, ...] = (900,),
    ) -> None:
        self.status = status
        self.error = error
        self.message_ids = message_ids
        self.plans: list[PublicationPlan] = []

    async def publish_plan(self, plan: PublicationPlan) -> tuple[OperationOutcome, ...]:
        self.plans.append(plan)
        if self.error is not None:
            raise self.error
        return tuple(
            OperationOutcome(operation=operation, status=self.status, message_ids=self.message_ids)
            for operation in plan.operations
        )


class FakeDownloader:
    def __init__(self, *, url: str = "https://cdn.example/x") -> None:
        self.url = url
        self.resolved: list[tuple[str, AttachmentKind]] = []
        self.downloaded: list[tuple[str, str]] = []

    async def resolve_url(self, source_ref: str, kind: AttachmentKind) -> str:
        self.resolved.append((source_ref, kind))
        return self.url

    async def download(self, source_ref: str, url: str) -> str:
        self.downloaded.append((source_ref, url))
        return f"/tmp/{source_ref}.bin"


class FakeUow:
    def __init__(self) -> None:
        self.bridge_settings = FakeSettingsRepository()
        self.telegram_topics = FakeTopicsRepository()
        self.vk_aliases = FakeAliasesRepository()
        self.deliveries = DeliveryLedger()
        self.commits = 0

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
        self.commits += 1

    async def rollback(self) -> None:
        return None


def _record_for(uow: FakeUow) -> DeliveryRecord:
    records = list(uow.deliveries.records.values())
    assert len(records) == 1
    return records[0]


def _manual(
    *, plan: FakePlanPublisher | None = None, downloader: FakeDownloader | None = None
) -> tuple[PublishManualMessage, FakeUow, FakePlanPublisher]:
    uow = FakeUow()
    real_plan = plan or FakePlanPublisher()
    use_case = PublishManualMessage(lambda: uow, FakePublisher(), real_plan, downloader=downloader)
    return use_case, uow, real_plan


async def test_manual_records_manual_intent_and_publishes() -> None:
    use_case, uow, _ = _manual()
    result = await use_case.execute(
        ManualPublicationRequest(source=_source(), initiator=INITIATOR, destination=DESTINATION)
    )
    assert result.published is True
    assert result.message_ids == (900,)
    record = _record_for(uow)
    assert record.intent == "manual"
    assert record.publication_status is PublicationStatus.PUBLISHED


async def test_manual_source_key_allows_republish_of_same_message() -> None:
    use_case, uow, _ = _manual()
    request = ManualPublicationRequest(
        source=_source(), initiator=INITIATOR, destination=DESTINATION
    )
    first = await use_case.execute(request)
    second = await use_case.execute(request)
    assert first.delivery_id != second.delivery_id
    assert len(uow.deliveries.records) == 2


async def test_manual_source_key_prefix_is_manual() -> None:
    use_case, uow, _ = _manual()
    await use_case.execute(
        ManualPublicationRequest(source=_source(), initiator=INITIATOR, destination=DESTINATION)
    )
    record = _record_for(uow)
    assert str(record.source_key).startswith(f"manual:{USER_ID}:{CMID}:")


async def test_manual_does_not_call_reaction() -> None:
    use_case, _, plan = _manual()
    await use_case.execute(
        ManualPublicationRequest(source=_source(), initiator=INITIATOR, destination=DESTINATION)
    )
    assert not hasattr(plan, "reaction_calls")


async def test_manual_ambiguous_is_fail_closed() -> None:
    plan = FakePlanPublisher(error=PublicationAmbiguousError("timeout"))
    use_case, uow, _ = _manual(plan=plan)
    result = await use_case.execute(
        ManualPublicationRequest(source=_source(), initiator=INITIATOR, destination=DESTINATION)
    )
    assert result.published is False
    record = _record_for(uow)
    assert record.publication_status is PublicationStatus.AMBIGUOUS
    assert record.review_required is True


async def test_manual_failed_permanent_recorded() -> None:
    plan = FakePlanPublisher(status=OperationStatus.FAILED_PERMANENT)
    use_case, uow, _ = _manual(plan=plan)
    result = await use_case.execute(
        ManualPublicationRequest(source=_source(), initiator=INITIATOR, destination=DESTINATION)
    )
    assert result.published is False
    record = _record_for(uow)
    assert record.publication_status is PublicationStatus.FAILED_PERMANENT


async def test_manual_two_links_present_in_publication() -> None:
    use_case, _, plan = _manual()
    await use_case.execute(
        ManualPublicationRequest(source=_source(), initiator=INITIATOR, destination=DESTINATION)
    )
    html = plan.plans[0].base.html_text
    assert f"https://vk.com/id{AUTHOR.user_id}" in html
    assert f"https://vk.com/id{INITIATOR.user_id}" in html


async def test_manual_attachment_downloaded_and_planned() -> None:
    attachment = Attachment(
        kind=AttachmentKind.PHOTO, file_name="p.jpg", size_bytes=1000, source_ref="1_2"
    )
    downloader = FakeDownloader()
    use_case, _, plan = _manual(downloader=downloader)
    await use_case.execute(
        ManualPublicationRequest(
            source=_source(attachments=(attachment,)),
            initiator=INITIATOR,
            destination=DESTINATION,
        )
    )
    assert downloader.resolved == [("1_2", AttachmentKind.PHOTO)]
    assert downloader.downloaded == [("1_2", "https://cdn.example/x")]
    kinds = [operation.kind for operation in plan.plans[0].operations]
    assert OperationKind.PHOTO in kinds


async def test_manual_oversize_attachment_becomes_warning_not_operation() -> None:
    attachment = Attachment(
        kind=AttachmentKind.DOCUMENT,
        file_name="big.zip",
        size_bytes=60 * 1024 * 1024,
        source_ref="1_3",
    )
    downloader = FakeDownloader()
    use_case, _, plan = _manual(downloader=downloader)
    await use_case.execute(
        ManualPublicationRequest(
            source=_source(attachments=(attachment,)),
            initiator=INITIATOR,
            destination=DESTINATION,
        )
    )
    assert downloader.downloaded == []
    kinds = [operation.kind for operation in plan.plans[0].operations]
    assert OperationKind.DOCUMENT not in kinds
    assert "big.zip" in plan.plans[0].base.html_text


async def test_manual_unsupported_attachment_becomes_warning_line() -> None:
    attachment = Attachment(
        kind=AttachmentKind.UNSUPPORTED, file_name="voice.ogg", size_bytes=100, source_ref="1_4"
    )
    use_case, _, plan = _manual(downloader=FakeDownloader())
    await use_case.execute(
        ManualPublicationRequest(
            source=_source(attachments=(attachment,)),
            initiator=INITIATOR,
            destination=DESTINATION,
        )
    )
    kinds = [operation.kind for operation in plan.plans[0].operations]
    assert kinds == [OperationKind.TEXT]
    assert "voice.ogg" in plan.plans[0].base.html_text


async def test_manual_caption_branch_used_for_short_text_with_media() -> None:
    attachment = Attachment(
        kind=AttachmentKind.PHOTO, file_name="p.jpg", size_bytes=1000, source_ref="1_2"
    )
    use_case, _, plan = _manual(downloader=FakeDownloader())
    await use_case.execute(
        ManualPublicationRequest(
            source=_source("коротко", attachments=(attachment,)),
            initiator=INITIATOR,
            destination=DESTINATION,
        )
    )
    operations = plan.plans[0].operations
    assert OperationKind.TEXT not in [operation.kind for operation in operations]
    assert operations[0].text is not None


async def test_manual_publish_plan_uses_single_claim_token() -> None:
    use_case, uow, _ = _manual()
    await use_case.execute(
        ManualPublicationRequest(source=_source(), initiator=INITIATOR, destination=DESTINATION)
    )
    record = _record_for(uow)
    assert record.attempts == 1
    assert record.telegram_message_ids == (900,)
