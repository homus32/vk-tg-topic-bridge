"""US-09: the VK author is carried over into the Telegram publication.

AC-09.1 — the publication shows the author's first and last name.
AC-09.2 — the name is a hyperlink to that user's VK profile.
"""

from __future__ import annotations

from tests.acceptance._fakes import make_forwarding_harness, make_source
from vk_topic_bridge.domain.value_objects import Author

AUTHOR = Author(user_id=1234567, first_name="Елена", last_name="Кузнецова", screen_name="elena_k")


async def test_us09_ac091_publication_shows_the_author_name() -> None:
    harness = make_forwarding_harness()

    await harness.use_case.execute(make_source("#новость текст", author=AUTHOR))

    html = harness.publisher.publications[0].html_text
    assert "Елена Кузнецова" in html


async def test_us09_ac092_author_name_is_a_link_to_the_vk_profile() -> None:
    harness = make_forwarding_harness()

    await harness.use_case.execute(make_source("#новость текст", author=AUTHOR))

    html = harness.publisher.publications[0].html_text
    assert f'<a href="https://vk.com/id{AUTHOR.user_id}">Елена Кузнецова</a>' in html


async def test_us09_author_link_uses_numeric_id_not_screen_name() -> None:
    harness = make_forwarding_harness()

    await harness.use_case.execute(make_source("#новость текст", author=AUTHOR))

    html = harness.publisher.publications[0].html_text
    assert "screen_name" not in html
    assert AUTHOR.screen_name is not None
    assert AUTHOR.screen_name not in html


async def test_us09_author_name_is_html_escaped() -> None:
    risky = Author(user_id=7, first_name="A<B", last_name="C&D", screen_name=None)
    harness = make_forwarding_harness()

    await harness.use_case.execute(make_source("#новость текст", author=risky))

    html = harness.publisher.publications[0].html_text
    assert "A&lt;B C&amp;D" in html
    assert '<a href="https://vk.com/id7">' in html
