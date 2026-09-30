from vk_topic_bridge.domain.policies.keyboard_policy import (
    KeyboardLimits,
    fit_keyboard_label,
    fit_keyboard_rows,
)


def test_fit_keyboard_rows_caps_rows_and_buttons_per_row() -> None:
    limits = KeyboardLimits(max_buttons=100, max_rows=5, max_buttons_per_row=5)
    rows = tuple(tuple(f"{row}-{button}" for button in range(6)) for row in range(7))

    fitted = fit_keyboard_rows(rows, limits)

    assert len(fitted.rows) == 5
    assert all(len(row) == 5 for row in fitted.rows)
    assert fitted.dropped_buttons == 17


def test_fit_keyboard_rows_caps_total_button_count() -> None:
    limits = KeyboardLimits(max_buttons=10, max_rows=5, max_buttons_per_row=5)
    rows = tuple(tuple(f"{row}-{button}" for button in range(5)) for row in range(3))

    fitted = fit_keyboard_rows(rows, limits)

    assert fitted.rows == rows[:2]
    assert fitted.dropped_buttons == 5


def test_fit_keyboard_rows_preserves_all_buttons_within_limits() -> None:
    rows = (("first", "second"), ("third",))
    limits = KeyboardLimits(max_buttons=10, max_rows=5, max_buttons_per_row=5)

    fitted = fit_keyboard_rows(rows, limits)

    assert fitted.rows == rows
    assert fitted.dropped_buttons == 0


def test_fit_keyboard_rows_does_not_count_empty_rows_as_capacity() -> None:
    rows = (("first",), (), ("second",))
    limits = KeyboardLimits(max_buttons=10, max_rows=2, max_buttons_per_row=5)

    fitted = fit_keyboard_rows(rows, limits)

    assert fitted.rows == (("first",), ("second",))
    assert fitted.dropped_buttons == 0


def test_fit_keyboard_label_preserves_label_within_limit() -> None:
    label = "а" * 40

    fitted = fit_keyboard_label(label)

    assert fitted == label


def test_fit_keyboard_label_shortens_overlong_label_to_limit() -> None:
    label = "а" * 41

    fitted = fit_keyboard_label(label)

    assert len(fitted) == 40
    assert fitted.endswith("…")
