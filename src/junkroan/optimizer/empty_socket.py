"""Empty sockets with a fill candidate (#1156 audit, unit 2): a delivered build whose free socket takes a gem the fill step keeps.

The fill step (`SkeletonGenerator.pick_fill`) measures every candidate that fits a free socket in its first round, against
the build as it stands. The audit repeats that first round on the delivered build: each candidate is written into the skills
surface by the same `skill_payload` the fill step writes, measured, and the build is loaded back from its own XML. The
decision (`kept_fill_candidate`) is a plain function of the measured numbers and needs no PoB; `measure_fill_round` is the
thin PoB part. A finding is a socket that stays empty while PoB counts a gem for it.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from typing import Any, Sequence

from junkroan.optimizer.objective import Objective, Score
from junkroan.optimizer.rails import Rails
from junkroan.search.generator import SkeletonGenerator, fill_keeps
from junkroan.search.sockets import gem_colour
from junkroan.search.skeleton import Skeleton, SocketGroup
from junkroan.search.vaal_twin import plain_of_vaal

EMPTY_SOCKET_CHECK = "empty-socket-with-candidate"


@dataclass(frozen=True, slots=True)
class FillMeasure:
    """One candidate measured in the fill step's first round: the socket it fits and the build's (Score, TotalEHP) with it."""

    gem: str
    slot: str
    colour: str  # the colour of the free socket it fits
    score: Score
    ehp: float


def kept_fill_candidate(base: tuple[Score, float], measures: Sequence[FillMeasure], *, gain: float, max_loss: float) -> FillMeasure | None:
    """The candidate the fill step would keep first (the best passing one by (Score, TotalEHP), as `pick_fill` takes it), or None."""

    passing = [m for m in measures if fill_keeps(base, (m.score, m.ehp), gain=gain, max_loss=max_loss)]
    return max(passing, key=lambda m: (m.score, m.ehp), default=None)


def _relative(after: float, before: float) -> float:
    return (after - before) / abs(before) if before else 0.0


def empty_socket_detail(base: tuple[Score, float], best: FillMeasure) -> str:
    """`<slot> socket <colour> fits <gem>: TotalEHP +x% / objective +y%`, the shares read off the measured build."""

    base_score, base_ehp = base
    return (f"{best.slot} socket {best.colour} fits {best.gem}: "
            f"TotalEHP {_relative(best.ehp, base_ehp):+.2%} / objective {_relative(best.score.value, base_score.value):+.2%}")


def _measure(pob: Any, skeleton: Skeleton, rails: Rails, keys: Sequence[str], extra: SocketGroup | None = None) -> dict[str, Any]:
    """Write the skeleton's skills surface (plus `extra` as one more group) as the fill step does, and read `keys`."""

    trial = copy.copy(skeleton)  # a shallow copy: the delivered skeleton's own groups stay as they are
    trial.extra_groups = [*skeleton.extra_groups, *([extra] if extra is not None else [])]
    pob.set_skills(**trial.skill_payload(gem_level=rails.gems.level, gem_quality=rails.gems.quality,
                                         main_quality=rails.gems.main_quality, main_link=list(skeleton.main_link)))
    return pob.stats(keys)


def same_gem_key(name: str) -> str:
    """A gem's identity for "is it listed": lower case, a Vaal twin (vaal_delivery) counting as its plain gem."""

    return (plain_of_vaal(name) or name).strip().lower()


def with_built_groups(pob: Any, skeleton: Skeleton) -> Skeleton:
    """A copy of ``skeleton`` that also lists the gems the build holds and the skeleton does not (#1156 row 3).

    The pipeline's own skeleton lists every group it placed, the fill step's included. A stored one (the search build's sidecar
    JSON) is older than the build, and `_measure` writes the skeleton's skills over the build's: without this the base loses
    the gems placed since and the check offers the same gem again. The unit is the gem, read off PoB's readback: a gem
    missing from the skeleton's main link and groups joins the extra group that lists a gem of its built group (a copy of
    that group), else it forms a group of its own on the built group's slot (None for an unslotted group). A skeleton that
    lists every gem comes back unchanged."""

    listed = {same_gem_key(g) for grp in skeleton.extra_groups for g in grp.gems} | {same_gem_key(g) for g in skeleton.main_link}
    groups = list(skeleton.extra_groups)
    changed = False
    for built in ((pob.read_state() or {}).get("skills_state") or {}).get("socket_groups") or []:
        if not isinstance(built, dict):
            continue
        names = [str(g.get("gem_name") or "") for g in built.get("gems") or [] if isinstance(g, dict)]
        names = [n for n in names if n]
        missing = [n for n in names if same_gem_key(n) not in listed]
        if not missing:
            continue
        host = next((i for i, grp in enumerate(groups) if any(same_gem_key(g) in {same_gem_key(n) for n in names} for g in grp.gems)), None)
        if host is not None:
            groups[host] = replace(groups[host], gems=[*groups[host].gems, *missing])
        else:
            slot = built.get("slot")
            groups.append(SocketGroup(gems=missing, slot=slot if isinstance(slot, str) and slot else None,  # type: ignore[arg-type]
                                      label=str(built.get("label") or missing[0]), enabled=built.get("enabled") is not False,
                                      include_in_full_dps=bool(built.get("include_in_full_dps")), picked=True))
        listed |= {same_gem_key(n) for n in missing}
        changed = True
    if not changed:
        return skeleton
    result = copy.copy(skeleton)
    result.extra_groups = groups
    return result


def measure_fill_round(pob: Any, skeleton: Skeleton, rails: Rails, objective: Objective) -> tuple[tuple[Score, float], list[FillMeasure]] | None:
    """The fill step's first round on the built state: (base Score, base TotalEHP) and one measure per offered candidate that
    fits a free socket. None when no socket is free. The build is loaded back from its own XML afterwards (the trials are reverted).
    The config is the delivered one: a candidate's own config choices (Flesh and Stone's stance) are not tried here."""

    skeleton = with_built_groups(pob, skeleton)
    gen = SkeletonGenerator(pob, rails, objective=objective)
    free = {slot: list(colours) for slot, colours in gen._free_sockets().items() if colours}
    if not free:
        return None
    keys = tuple(dict.fromkeys((*objective.stat_keys, "TotalEHP", "ManaUnreserved", "LifeUnreserved")))
    base_xml = pob.export_xml()
    try:
        base_stats = _measure(pob, skeleton, rails, keys)
        base = (objective.score(base_stats), float(base_stats.get("TotalEHP") or 0))
        room = {"Mana": base_stats.get("ManaUnreserved"), "Life": base_stats.get("LifeUnreserved")}
        offered: list[tuple[str, str, int]] = []
        for name in gen.fill_candidates(skeleton):
            place = gen._socket_for(gem_colour(name), free)
            if place is None:
                continue
            if not all(not isinstance(room[p], (int, float)) or room[p] > 0 for p in gen._reserve_pools(name)):
                continue  # the pool it reserves from has nothing unreserved: the fill step does not measure it either
            offered.append((name, *place))
        measures: list[FillMeasure] = []
        for name, slot, index in offered:
            stats = _measure(pob, skeleton, rails, keys, SocketGroup(gems=[name], slot=slot, label=name, picked=True))
            measures.append(FillMeasure(gem=name, slot=slot, colour=free[slot][index], score=objective.score(stats),
                                        ehp=float(stats.get("TotalEHP") or 0)))
    finally:
        pob.load_xml(base_xml)
    return base, measures
