"""Human-facing duration and rate formatting."""

from __future__ import annotations

from junkroan.report_format import human_duration, human_rate_per_minute


def test_human_duration_uses_compact_person_sized_units() -> None:
    assert human_duration(2.84) == "2.8 s"
    assert human_duration(42) == "42 s"
    assert human_duration(95) == "1.6 min"
    assert human_duration(1191) == "20 min"
    assert human_duration(2856) == "48 min"
    assert human_duration(5300) == "88 min"
    assert human_duration(5400) == "1 h 30 min"
    assert human_duration(93900) == "26 h 05 min"
    assert human_duration(None) == "-"
    assert human_duration(float("nan")) == "-"


def test_human_duration_integral_float_renders_like_int() -> None:
    for v in (2.0, 600.0, 5400.0):
        assert human_duration(v) == human_duration(int(v))
    assert human_duration(2.0) == "2 s"
    assert human_duration(2) == "2 s"
    assert human_duration(13.8) == "14 s"


def test_human_duration_keeps_a_negative_sign_and_rate_is_per_minute() -> None:
    assert human_duration(-95) == "-1.6 min"
    assert human_rate_per_minute(10, 5) == 120
    assert human_rate_per_minute(10, 0) == 0
