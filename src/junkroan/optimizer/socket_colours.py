"""Greedy socket-colour picker (#435). PoB-free: the caller scores each trial."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Sequence


@dataclass(frozen=True)
class ColourCandidate:
    slot: str
    position: int
    gem: str
    colour: str  # "R" | "G" | "B"


@dataclass
class ColourPick:
    picks: list[ColourCandidate]
    score_before: float
    score_after: float
    trials: int


def pick_colours(
    candidates: Sequence[ColourCandidate],
    trial: Callable[[list[ColourCandidate]], float],
    base_score: float,
    max_picks: Optional[int],
    *,
    better: Optional[Callable[[float, float], bool]] = None,
    on_trial: Optional[Callable[[list[ColourCandidate], float], None]] = None,
    on_round: Optional[Callable[[list[list[ColourCandidate]]], None]] = None,
) -> ColourPick:
    beats = better if better is not None else (lambda new, old: new > old)
    picks: list[ColourCandidate] = []
    score = base_score
    trials = 0
    while max_picks is None or len(picks) < max_picks:
        taken = {(p.slot, p.position) for p in picks}
        if on_round is not None:  # the options this round will try: each remaining candidate added to the picks
            on_round([picks + [c] for c in candidates if (c.slot, c.position) not in taken])
        best: Optional[ColourCandidate] = None
        best_score = score
        for cand in candidates:
            if (cand.slot, cand.position) in taken:
                continue
            attempt = picks + [cand]
            s = trial(list(attempt))
            trials += 1
            if on_trial is not None:
                on_trial(list(attempt), s)
            if beats(s, best_score):
                best, best_score = cand, s
        if best is None:
            break
        picks.append(best)
        score = best_score
    return ColourPick(picks, base_score, score, trials)
