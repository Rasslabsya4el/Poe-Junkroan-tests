"""Small, dependency-free formatters for durations in human-facing reports."""

from __future__ import annotations

import math


def _one_decimal(value: float) -> str:
    """One decimal, with a zero fraction dropped (2.0 -> "2")."""

    text = f"{value:.1f}"
    return text[:-2] if text.endswith(".0") else text


def human_duration(seconds: float | None) -> str:
    """Format a duration with a unit a person can readily read."""

    if seconds is None or not math.isfinite(seconds):
        return "-"
    sign = "-" if seconds < 0 else ""
    value = abs(seconds)
    if value < 10:
        return f"{sign}{_one_decimal(value)} s"
    if value < 90:
        return f"{sign}{value:.0f} s"
    minutes = value / 60
    if minutes < 10:
        return f"{sign}{_one_decimal(minutes)} min"
    if minutes < 90:
        return f"{sign}{minutes:.0f} min"
    hours, remaining_minutes = divmod(int(round(minutes)), 60)
    return f"{sign}{hours} h {remaining_minutes:02d} min"


def human_rate_per_minute(gain: float, seconds: float) -> float:
    """Return ``gain`` scaled to one minute, or zero when no time elapsed."""

    if not math.isfinite(gain) or not math.isfinite(seconds) or seconds <= 0:
        return 0.0
    return gain * 60.0 / seconds
