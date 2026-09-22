"""Forwarding policy: filter matching, source keys and publication composition."""

import html
import re
from dataclasses import dataclass

from vk_topic_bridge.domain.value_objects import Destination, Publication, SourceMessage

HASHTAG_RE = re.compile(r"#\w+", re.UNICODE)
ALL_TOKEN_RE = re.compile(r"(?<!\w)@all(?!\w)", re.IGNORECASE)

IZVK_TAG = "#извк"
IZVK_IMPORTANT_TAG = "#извкважно"


@dataclass(frozen=True, slots=True)
class ForwardDecision:
    """Outcome of the two independent toggles for one message."""

    forward: bool
    matched_all: bool
    matched_hashtag: bool


def decide(text: str, *, auto_forward_all: bool, auto_forward_hashtags: bool) -> ForwardDecision:
    matched_all = ALL_TOKEN_RE.search(text) is not None
    matched_hashtag = HASHTAG_RE.search(text) is not None
    forward = (auto_forward_all and matched_all) or (auto_forward_hashtags and matched_hashtag)
    return ForwardDecision(
        forward=forward, matched_all=matched_all, matched_hashtag=matched_hashtag
    )


def source_key(group_id: int, peer_id: int, conversation_message_id: int) -> str:
    return f"{group_id}:{peer_id}:{conversation_message_id}"


def compose_publication(source: SourceMessage, destination: Destination) -> Publication:
    author = source.author
    tags = f"{IZVK_TAG} {IZVK_IMPORTANT_TAG}" if source.has_all else IZVK_TAG
    author_link = f'<a href="{author.profile_url}">{html.escape(author.display_name)}</a>'
    html_text = f"{author_link}\n\n{html.escape(source.text)}"
    if source.wall_post is not None:
        wall_author = source.wall_post.author
        wall_author_link = (
            f'<a href="{wall_author.profile_url}">{html.escape(wall_author.display_name)}</a>'
        )
        wall_link = f'<a href="{source.wall_post.url}">Оригинал поста</a>'
        html_text += (
            f"\n\n{wall_author_link}\n\n{html.escape(source.wall_post.text)}\n\n{wall_link}"
        )
    elif source.wall_link is not None:
        html_text += f'\n\n<a href="{source.wall_link}">Оригинал поста</a>'
    html_text += f"\n\n{tags}"
    return Publication(
        chat_id=destination.chat_id,
        message_thread_id=destination.message_thread_id,
        html_text=html_text,
        has_all=source.has_all,
        source=source,
    )
