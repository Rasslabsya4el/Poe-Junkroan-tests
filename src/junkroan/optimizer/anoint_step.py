"""Anoint step logic: pick the best amulet anoint by measured score (pure, no PoB).

Scores are `objective.score(...)` values: higher is better. The caller supplies
`measure(name_or_None) -> score`; None means "no anoint".
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class AnointPick:
    chosen: str | None
    score_before: float
    score_after: float
    measured: int
    ranked: tuple[tuple[str, float], ...]


def _decide(
    names: Sequence[str],
    measure: Callable[[str | None], float],
) -> AnointPick:
    before = measure(None)
    scored = [(n, measure(n)) for n in names]
    ranked = tuple(sorted(scored, key=lambda p: -p[1]))  # stable: ties keep order
    if ranked and ranked[0][1] > before:
        return AnointPick(ranked[0][0], before, ranked[0][1], len(scored), ranked)
    return AnointPick(None, before, before, len(scored), ranked)


def _dedup(names: Sequence[str], exclude: Collection[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n in exclude or n in seen:
            continue
        seen.add(n)
        out.append(n)
    return out


def pick_anoint(
    candidates: Sequence[str],
    measure: Callable[[str | None], float],
    *,
    exclude: Collection[str] = (),
) -> AnointPick:
    return _decide(_dedup(candidates, exclude), measure)


def repick_anoint(
    first: AnointPick,
    current: str | None,
    measure: Callable[[str | None], float],
    *,
    exclude: Collection[str] = (),
    top: int = 10,
) -> AnointPick:
    names = [n for n, _ in first.ranked[:top]]
    if current is not None:
        names.append(current)
    return _decide(_dedup(names, exclude), measure)
