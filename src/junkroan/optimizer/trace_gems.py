"""Option classes of one gem candidate for the trace counters (#498); PoB-free, never raises."""

from __future__ import annotations

from typing import Iterable

from junkroan.optimizer.trace import TRACE


def _is_transfigured_name(name: str) -> bool:
    """The generator's own test (variant id of the corpus record); unknown name -> False."""

    try:
        from junkroan.search.generator import _is_transfigured
        from junkroan.search.hypothesis import active_gems, support_gems

        key = name.lower()
        record = active_gems().get(key) or support_gems().get(key)
        return bool(record) and _is_transfigured(record)
    except Exception:
        return False


def _is_vaal_name(name: str) -> bool:
    """The corpus's `is_vaal_gem` (the "Vaal " prefix only for a name the corpus does not know); never raises."""

    try:
        from junkroan.search.hypothesis import active_gems

        record = active_gems().get(name.lower())
        return bool(record.get("is_vaal_gem")) if record else name.startswith("Vaal ")
    except Exception:
        return False


def gem_classes(name: str, *, role: str, link_size: int | None = None) -> set[str]:
    """`support:<name>` / `gem:<name>`, plus `transfigured` and `links:<n>` when known."""

    out = {f"{'support' if role == 'support' else 'gem'}:{name}"}
    if _is_transfigured_name(name):
        out.add("transfigured")
    if _is_vaal_name(name):
        out.add("vaal")
    if link_size is not None:
        out.add(f"links:{link_size}")
    return out


def count_generated(names: Iterable[str], *, role: str, link_size: int | None = None) -> None:
    for name in names:
        TRACE.add_generated(gem_classes(name, role=role, link_size=link_size))


def count_evaluated(name: str, *, role: str, link_size: int | None = None) -> None:
    TRACE.add_evaluated(gem_classes(name, role=role, link_size=link_size))


ABOVE_RAIL = "above-rail"


def count_delivered_gem(name: str, *, level: int, quality: int, level_rail: int, quality_rail: int) -> None:
    """#802 rows 3-4: a gem of the delivered build, measured at the PoB boundary. A Vaal or transfigured gem whose level or
    quality is above the loadout's pair also gets the class `above-rail`, so `evaluated(above-rail) = 0` is a number read."""

    classes = gem_classes(name, role="gem")
    if classes & {"vaal", "transfigured"} and (level > level_rail or quality > quality_rail):
        classes.add(ABOVE_RAIL)
    TRACE.add_evaluated(classes)
