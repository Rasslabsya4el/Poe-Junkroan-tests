"""Option classes of the day-1 flask step for the trace counter (#436).

Forbidden classes are no candidate the step can build, so they are written 0/0 to show as 0, not as absent.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from junkroan.optimizer.trace import TRACE

FORBIDDEN_CLASSES: tuple[str, ...] = (
    "flask-ilvl-over",
    "flask-base-level-over",
    "flask-enchant",
    "flask-quality",
    "flask-rare",
)

# #575: written evaluated 0 by the step (the output count is read at the end from the delivered build)
UPTIME_CLASS = "flask-active-uptime-below-100"
# #589: a life build without the Divine Life Flask; the step adds evaluated 1 when it ends so
NO_DIVINE_CLASS = "flask-life-build-without-divine"
DIVINE_BASE = "Divine Life Flask"
# #604: the mana sustain rail judges mana without flasks; a Mana Flask may count only at PoB uptime 100 %. Written
# evaluated 0 by the step; the output count (an active Mana/Hybrid Flask with uptime below 100) is read from the build.
MANA_SUSTAIN_CLASS = "mana-sustain-inactive-flask"
MANA_FLASK_MARKERS = ("Mana Flask", "Hybrid Flask")
# #1162: a craft trial of a utility flask (every flask base that is not Life / Mana / Hybrid). The day-1 rail
# `gear.flasks.flask_utility_crafting` is false, so the step builds none: evaluated 0 there. Written 0/0 by count_generated.
UTILITY_CRAFT_CLASS = "utility-flask-craft"


def flask_classes(candidate: Any) -> list[str]:
    mods = sum(1 for m in (candidate.prefix, candidate.suffix) if m is not None)
    classes = [f"flask-base:{candidate.base.kind}", f"flask-mods:{mods}"]
    if candidate.base.name == DIVINE_BASE:
        classes.append("flask-divine-life")
    if candidate.base.kind not in ("life", "mana", "hybrid"):
        classes.append(UTILITY_CRAFT_CLASS)
    return classes


def count_generated(candidates: Iterable[Any]) -> None:
    """`generated` per candidate, and the forbidden classes as 0/0; under the caller's `TRACE.move`."""

    for c in candidates:
        TRACE.add_generated(flask_classes(c))
    for forbidden in FORBIDDEN_CLASSES:
        TRACE.add_generated([forbidden], 0)
        TRACE.add_evaluated([forbidden], 0)
    TRACE.add_generated([UPTIME_CLASS], 0)
    TRACE.add_evaluated([UPTIME_CLASS], 0)
    TRACE.add_generated([NO_DIVINE_CLASS], 0)
    TRACE.add_evaluated([NO_DIVINE_CLASS], 0)
    TRACE.add_generated([MANA_SUSTAIN_CLASS], 0)
    TRACE.add_evaluated([MANA_SUSTAIN_CLASS], 0)
    TRACE.add_generated([UTILITY_CRAFT_CLASS], 0)
    TRACE.add_evaluated([UTILITY_CRAFT_CLASS], 0)


class TracingFlaskProbe:
    """Forwards every `FlaskProbe` method to `inner`; each `put_flask` counts `evaluated`."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def score(self) -> Any:
        return self._inner.score()

    def snapshot(self) -> Any:
        return self._inner.snapshot()

    def restore(self, snap: Any) -> None:
        self._inner.restore(snap)

    def defence(self) -> Any:
        return self._inner.defence()

    def put_flask(self, slot: str, candidate: Any) -> None:
        TRACE.add_evaluated(flask_classes(candidate))
        self._inner.put_flask(slot, candidate)

    def clear_flask(self, slot: str) -> None:
        self._inner.clear_flask(slot)

    def measure_active(self, slot: str, candidate: Any) -> Any:
        TRACE.add_evaluated(flask_classes(candidate))  # an as-if-active trial is a PoB read of this candidate (#589 R3)
        return self._inner.measure_active(slot, candidate)
