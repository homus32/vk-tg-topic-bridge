"""Unit tests for the forwarding policy: filters, source keys and composition."""

from vk_topic_bridge.domain.enums import AttachmentKind, SourceType
from vk_topic_bridge.domain.policies import forwarding_policy
from vk_topic_bridge.domain.value_objects import (
    Attachment,
    Author,
    Destination,
    Publication,
    SourceMessage,
)


def _source(
    *,
    text: str,
    has_all: bool = False,
    has_hashtag: bool = False,
    author: Author | None = None,
    attachments: tuple[Attachment, ...] = (),
) -> SourceMessage:
    return SourceMessage(
        source_type=SourceType.VK_MESSAGE,
        source_key="1:2:3",
        group_id=1,
        peer_id=2,
        conversation_message_id=3,
        author=author
        or Author(user_id=777, first_name="Иван", last_name="Петров", screen_name="ip"),
        text=text,
        has_all=has_all,
        has_hashtag=has_hashtag,
        attachments=attachments,
    )


def test_all_only_with_toggle_on_forwards() -> None:
    decision = forwarding_policy.decide("@all", auto_forward_all=True, auto_forward_hashtags=False)
    assert isinstance(decision, forwarding_policy.ForwardDecision)
    assert decision.forward is True
    assert decision.matched_all is True
    assert decision.matched_hashtag is False


def test_hashtag_only_with_toggle_on_forwards() -> None:
    decision = forwarding_policy.decide(
        "#важное", auto_forward_all=False, auto_forward_hashtags=True
    )
    assert decision.forward is True
    assert decision.matched_all is False
    assert decision.matched_hashtag is True


def test_all_and_hashtag_yield_exactly_one_decision() -> None:
    decision = forwarding_policy.decide(
        "@all #важное", auto_forward_all=True, auto_forward_hashtags=True
    )
    assert not isinstance(decision, (tuple, list))
    assert decision.forward is True
    assert decision.matched_all is True
    assert decision.matched_hashtag is True


def test_both_matches_with_toggles_off_do_not_forward() -> None:
    decision = forwarding_policy.decide(
        "@all #важное", auto_forward_all=False, auto_forward_hashtags=False
    )
    assert decision.forward is False
    assert decision.matched_all is True
    assert decision.matched_hashtag is True


def test_toggle_on_without_match_does_not_forward() -> None:
    decision = forwarding_policy.decide(
        "обычный текст без фильтров", auto_forward_all=True, auto_forward_hashtags=True
    )
    assert decision.forward is False
    assert decision.matched_all is False
    assert decision.matched_hashtag is False


def test_cyrillic_hashtag_matches() -> None:
    decision = forwarding_policy.decide(
        "смотри #важное", auto_forward_all=False, auto_forward_hashtags=True
    )
    assert decision.matched_hashtag is True
    assert decision.forward is True


def test_all_token_is_case_insensitive() -> None:
    decision = forwarding_policy.decide("@All", auto_forward_all=True, auto_forward_hashtags=False)
    assert decision.matched_all is True


def test_all_token_requires_word_boundaries() -> None:
    embedded = forwarding_policy.decide(
        "почта@all.ru", auto_forward_all=True, auto_forward_hashtags=False
    )
    extended = forwarding_policy.decide(
        "@alltogether", auto_forward_all=True, auto_forward_hashtags=False
    )
    assert embedded.matched_all is False
    assert extended.matched_all is False
    assert embedded.forward is False
    assert extended.forward is False


def test_source_key_format() -> None:
    assert forwarding_policy.source_key(42, 2000000001, 7) == "42:2000000001:7"


def test_compose_keeps_original_text_and_adds_izvk_tag() -> None:
    publication = forwarding_policy.compose_publication(
        _source(text="#важное", has_hashtag=True), Destination(chat_id=100, message_thread_id=None)
    )
    assert isinstance(publication, Publication)
    assert publication.chat_id == 100
    assert publication.message_thread_id is None
    assert publication.has_all is False
    assert publication.source.source_key == "1:2:3"
    assert "#важное" in publication.html_text
    assert "#извк" in publication.html_text
    assert "#извкважно" not in publication.html_text


def test_compose_adds_izvk_vazhno_tag_for_all() -> None:
    publication = forwarding_policy.compose_publication(
        _source(text="@all", has_all=True),
        Destination(chat_id=100, message_thread_id=55),
    )
    assert publication.message_thread_id == 55
    assert publication.has_all is True
    assert "#извк #извкважно" in publication.html_text


def test_compose_escapes_html_in_original_text() -> None:
    publication = forwarding_policy.compose_publication(
        _source(text="a & b <tag> c", has_all=True),
        Destination(chat_id=100, message_thread_id=None),
    )
    assert "a &amp; b &lt;tag&gt; c" in publication.html_text
    assert "a & b <tag> c" not in publication.html_text


def test_compose_links_author_to_numeric_profile() -> None:
    author = Author(user_id=555, first_name="Анна", last_name="&Ко", screen_name="anna")  # noqa: RUF001
    publication = forwarding_policy.compose_publication(
        _source(text="@all", has_all=True, author=author),
        Destination(chat_id=100, message_thread_id=None),
    )
    assert 'href="https://vk.com/id555"' in publication.html_text
    assert ">Анна &amp;Ко</a>" in publication.html_text  # noqa: RUF001


def test_compose_leaves_attachments_untouched() -> None:
    attachment = Attachment(
        kind=AttachmentKind.PHOTO, file_name="p.jpg", size_bytes=10, source_ref="photo1"
    )
    publication = forwarding_policy.compose_publication(
        _source(text="#важное", has_hashtag=True, attachments=(attachment,)),
        Destination(chat_id=100, message_thread_id=None),
    )
    assert publication.source.attachments == (attachment,)
