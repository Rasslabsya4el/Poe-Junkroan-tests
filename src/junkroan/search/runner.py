"""Process-level workers for the search: each call opens its own PobSession
(PoB is single-threaded; parallelism is processes, D-Phase 5) and returns
plain dicts so results cross process boundaries."""

from __future__ import annotations

import json
import os
import time
import traceback
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from junkroan.optimizer.objective_select import forced_keystones_of, objective_for
from junkroan.optimizer.pipeline import BuildPipeline
from junkroan.optimizer.rails import Rails
from junkroan.pob.session import PobSession
from junkroan.optimizer.trace import TRACE
from junkroan.search.forced import forced_of
from junkroan.search.generator import TWO_HAND_TYPES, SkeletonGenerator, forced_slots
from junkroan.search.hypothesis import item_bases, uniques_by_name
from junkroan.report_format import human_duration
from junkroan.search.skeleton import Skeleton


def _log_to(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a", encoding="utf-8")

    def log(msg: str) -> None:
        handle.write(msg + "\n")
        handle.flush()

    return log


def forced_violations(sk: Skeleton) -> list[str]:
    """What the skeleton lost of its request's forced directions (#510); [] when it carries all of them.
    PoB-free. A forced unique must stand in `uniques` under its name, a forced base in `rare_bases`
    with its base, a forced affix slot never becomes a unique (its rare base may still be unchosen: the
    base screen runs after this check, and in "wishlist" the gear filler picks armour bases itself)."""

    out: list[str] = []
    for slot, name in sk.forced_uniques.items():
        if sk.uniques.get(slot) != name:
            out.append(f"unique {name!r} not in {slot} (has {sk.uniques.get(slot)!r})")
    for slot, base in sk.forced_bases.items():
        if sk.rare_bases.get(slot) != base:
            out.append(f"base {base!r} not in {slot} (has {sk.rare_bases.get(slot)!r})")
    for slot in sk.forced_affixes:
        if slot in sk.uniques:
            out.append(f"forced-affix slot {slot} became a unique ({sk.uniques[slot]!r})")
    return out


def check_forced(sk: Skeleton) -> None:
    """Hand the skeleton's forced set to the trace and raise when the skeleton dropped any of it: a bug, never repaired."""

    TRACE.set_forced(forced_of(sk))
    bad = forced_violations(sk)
    if bad:
        raise ValueError("forced direction dropped: " + "; ".join(bad))


def _is_two_hander(name: str) -> bool:
    return any(rec["type"] in TWO_HAND_TYPES for rec in uniques_by_name().get(name.lower(), []))


def _unique_types(name: str) -> set[str]:
    return {rec["type"] for rec in uniques_by_name().get(name.lower(), [])}


def _weapon1_type(sk: Skeleton, picked: dict[str, str] | None) -> str | None:
    """Type of what stands in Weapon 1: a pick of this variant, else the skeleton's unique, else its rare base."""

    unique = (picked or {}).get("Weapon 1") or sk.uniques.get("Weapon 1")
    if unique:
        types = _unique_types(unique)
        return next((t for t in types if t in TWO_HAND_TYPES), next(iter(types), None))
    rec = item_bases().get(str(sk.rare_bases.get("Weapon 1") or "").lower())
    return rec.get("type") if rec else None


PAIR_CLASS = "unique-variant:two-hander+off-hand"


def _clashes_with_picked(slot: str, name: str, picked: dict[str, str] | None) -> bool:
    """Whether `name` in `slot` and the other weapon slot already in `picked` make a pair PoB refuses (#531): a
    two-hander in Weapon 1 with a picked Weapon 2 off-hand (a Quiver only stays under a Bow)."""

    if slot != "Weapon 1" or not picked or "Weapon 2" not in picked or not _is_two_hander(name):
        return False
    if "Quiver" in _unique_types(picked["Weapon 2"]):
        return "Bow" not in _unique_types(name)
    return True


def pick_unique_variant(sk: Skeleton, uniques: list[dict], min_gain: float, max_uniques: int) -> tuple[Skeleton | None, dict]:
    """The unique variant of `sk` from the screen's `uniques` (gain order): (variant or None, trace `considered` dict).
    Counts `PAIR_CLASS` under the move "unique-variant": generated = a pick refused because it would pair a two-hander
    Weapon 1 with a Weapon 2 off-hand, evaluated = variants that hold such a pair (must stay 0)."""

    picked: dict[str, str] = {}
    pairs = 0
    for u in uniques:
        name = u["name"].split(", ")[0]
        if u["gain"] < min_gain or u["slot"] in picked or len(picked) >= max_uniques:
            continue
        if unique_pick_ok(sk, u["slot"], name, picked):
            picked[u["slot"]] = name
        elif u["slot"] == "Weapon 2" and "Weapon 1" in picked and _is_two_hander(picked["Weapon 1"]) or _clashes_with_picked(u["slot"], name, picked):
            pairs += 1
    var = None
    held = 0
    if picked:
        var = Skeleton.from_json(sk.to_json())
        apply_unique_picks(var, picked)
        var.notes = (var.notes or "") + f" + uniques {picked}"
        w1 = var.uniques.get("Weapon 1")
        held = int(bool(w1 and _is_two_hander(w1) and var.uniques.get("Weapon 2")))
    considered = {"unique-variant": {PAIR_CLASS: {"generated": pairs, "evaluated": held}}}
    return var, considered


def unique_pick_ok(sk: Skeleton, slot: str, name: str, picked: dict[str, str] | None = None) -> bool:
    """Whether the search may put unique `name` in `slot` of `sk` (`picked`: the picks of the same variant so far):
    never in a slot the request fixed; a two-hander in Weapon 1 never when it would push out a fixed Weapon 2;
    in Weapon 2 never an off-hand PoB refuses (#519): anything but a Quiver under a two-hander in Weapon 1,
    a Quiver unless Weapon 1 is a Bow."""

    fixed = forced_slots(sk)
    if slot in fixed:
        return False
    if slot == "Weapon 1" and "Weapon 2" in fixed and _is_two_hander(name):
        return False
    if _clashes_with_picked(slot, name, picked):
        return False
    if slot == "Weapon 2":
        w1 = _weapon1_type(sk, picked)
        if "Quiver" in _unique_types(name):
            return w1 == "Bow"
        if w1 in TWO_HAND_TYPES:
            return False
    return True


def apply_unique_picks(var: Skeleton, picked: dict[str, str], *, replace: bool = False) -> None:
    """Put the picked uniques into `var` (`replace`: `picked` is the whole set) and drop the rare bases they replace;
    a forced slot's rare base is never dropped, a two-hander drops the shield only when Weapon 2 is not fixed."""

    if replace:
        var.uniques = dict(picked)
    else:
        var.uniques.update(picked)
    fixed = forced_slots(var)
    for slot in picked:
        if slot not in fixed:
            var.rare_bases.pop(slot, None)
    if "Weapon 1" in picked and "Weapon 2" not in fixed and _is_two_hander(picked["Weapon 1"]):
        var.rare_bases.pop("Weapon 2", None)  # two-hander: no shield


def weapon_alternative_ok(sk: Skeleton, alt: dict[str, str]) -> bool:
    """Whether the weapon alternative `alt` (D41) may replace the weapons of `sk`: it never changes a forced base
    slot, and a forced-affix slot keeps its weapon class (`sk.weapon_types`, else the class it has now)."""

    def cls(base: str | None) -> str | None:
        rec = item_bases().get(str(base or "").lower())
        return rec.get("type") if rec else None

    for slot in ("Weapon 1", "Weapon 2"):
        new = alt.get(slot)
        if slot in sk.forced_uniques:
            return False
        if slot in sk.forced_bases and new != sk.forced_bases[slot]:
            return False
        if slot in sk.forced_affixes:
            allowed = set(sk.weapon_types) if slot == "Weapon 1" and sk.weapon_types else {cls(sk.rare_bases.get(slot))}
            if new is None or cls(new) not in allowed:
                return False
    return True


def variant_screen_kept(value: float, floor_value: float) -> bool:
    """Whether a mutation variant's screen earns it the full round (#525): its screen value reaches the floor (half
    of the top finalists' screen), one rule for feasible and infeasible screens alike. Screen feasibility says
    nothing about the final (2358: rank 1 came from an infeasible screen, viol 0.042)."""

    return value >= floor_value


def variant_screen_line(tag: str, result: dict[str, Any], floor_value: float) -> tuple[bool, str]:
    """The keep verdict for one variant screen and the line `scripts/search.py` prints for it."""

    kept = variant_screen_kept(result["value"], floor_value)
    verdict = "full" if kept else "dropped (below half of the finalists screen)"
    return kept, f"  variant screen {tag}: {result['value']:,.0f} (viol {result['violation']:.3f}) in {human_duration(result['seconds'])} -> {verdict}"


def prepare_candidate(skeleton_json: str, *, log_path: str, shared_supports: list[str] | None, n_supports: int | None = None, points: int = 8, gear_mode: str = "loot") -> dict[str, Any]:
    """Fill a skeleton's blanks by PoB: bases, ascendancy nodes, and supports
    (unless a shared link is given). Returns the completed skeleton JSON.

    `gear_mode` reaches only the base screen: in "wishlist" the armour and jewellery slots
    are left to the gear filler, which chooses their bases itself (D73)."""

    t0 = time.perf_counter()
    log = _log_to(Path(log_path))
    sk = Skeleton.from_json(skeleton_json)
    TRACE.reset()  # a pool process serves many calls: the counter is per call
    check_forced(sk)
    rails = Rails.load()
    n_supports = rails.gems.main_link_max - 1 if n_supports is None else min(n_supports, rails.gems.main_link_max - 1)
    try:
        with PobSession(run_id=f"prep-{sk.ascendancy}-{os.getpid()}") as pob:
            gen = SkeletonGenerator(pob, rails, objective=objective_for(rails, sk.main_link[0], mode=sk.mode, forced_keystones=forced_keystones_of(sk)), log=log, gear_mode=gear_mode)
            sk.apply(pob, gem_level=rails.gems.level, gem_quality=rails.gems.quality, main_quality=rails.gems.main_quality)
            gen.refresh_castability()
            gen.screen_bases(sk)
            if len(sk.ascendancy_nodes) < points:
                gen.pick_ascendancy_nodes(sk, points=points)
            if shared_supports is not None and len(sk.main_link) < 1 + n_supports:
                sk.main_link = [sk.main_link[0], *[s for s in sk.main_link[1:]], *[s for s in shared_supports if s not in sk.main_link]][: 1 + n_supports]
                sk.apply_skills(pob, gem_level=rails.gems.level, gem_quality=rails.gems.quality, main_quality=rails.gems.main_quality)
            elif len(sk.main_link) < 1 + n_supports:
                gen.pick_supports(sk, n_supports=n_supports)
            picks = [{"what": p.what, "choice": p.choice, "value": p.score.value, "seconds": p.seconds} for p in gen.picks]
            # This is the only new PoB read for the rig rung. The preparation work already put
            # the skeleton's bases, ascendancy and link in the session. The rig is scored by the
            # rig's own objective (`search.rig_supports` builds the shared link the same way): a
            # bare rig has no regen or leech gear, so with the sustain relations on every rig row
            # would read infeasible and the value would be unusable as a rung.
            rig_objective = gen.objective.without_sustain()
            score = rig_objective.score(pob.stats(rig_objective.stat_keys))
        return {"ok": True, "skeleton": sk.to_json(), "picks": picks,
                "rig": {"value": score.value, "violation": score.violation, "feasible": score.feasible},
                "seconds": time.perf_counter() - t0, "considered": TRACE.considered()}
    except Exception as exc:  # a broken candidate must not kill the search
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc(), "skeleton": skeleton_json, "seconds": time.perf_counter() - t0, "considered": TRACE.considered()}


def optimize(skeleton_json: str, *, log_path: str, screen: bool, seed: int = 1, unique_screen: bool = False,
             repick_supports: bool = False, gear_mode: str = "loot", loop_seconds: float | None = None) -> dict[str, Any]:
    """Run the pipeline on one skeleton; screen=True for the cheap ranking pass."""

    t0 = time.perf_counter()
    log = _log_to(Path(log_path))
    sk = Skeleton.from_json(skeleton_json)
    TRACE.reset()  # a pool process serves many calls: the counter is per call
    check_forced(sk)
    rails = Rails.load()
    try:
        with PobSession(run_id=f"{'screen' if screen else 'full'}-{sk.ascendancy}-{os.getpid()}-{int(time.time() * 1000) % 100000}") as pob:
            pipeline = BuildPipeline(pob, rails, log=log)
            run_args = {"seed": seed, "screen": screen, "repick_supports": repick_supports, "gear_mode": gear_mode}
            if loop_seconds is not None:
                run_args["loop_max_seconds"] = loop_seconds
            res = pipeline.run(sk, **run_args)
            score = pipeline.objective.score(pob.stats(pipeline.objective.stat_keys))
            uniques = []
            if unique_screen:
                gen = SkeletonGenerator(pob, rails, objective=pipeline.objective, log=log)
                uniques = [{"slot": s, "name": n, "value": sc.value, "gain": g} for s, n, sc, g in gen.screen_uniques(top=8, fixed=forced_slots(sk))]
        return {
            "ok": True, "skeleton": sk.to_json(), "screen": screen, "seed": seed, "value": score.value, "violation": score.violation, "feasible": score.feasible,
            "final": res.final_stats, "optimistic": res.optimistic_stats.get("CombinedDPS"), "optimistic_stats": res.saved_optimistic(), "import_code": res.import_code, "xml": res.xml,
            "stages": [{"name": s.name, "seconds": s.seconds, "value": s.score_value, "violation": s.violation, "notes": s.notes} for s in res.stages],
            "config_reasons": res.config_reasons, "uniques": uniques, "seconds": time.perf_counter() - t0, "summary": res.summary(),
            "audit": [str(f) for f in res.audit], "audit_errors": sum(1 for f in res.audit if f.severity == "error"), "floors_missed": res.floors_missed, "floors_missed": res.floors_missed, "keystones": res.keystones, "explanation": res.explanation, "picks": res.picks,
            "castability_calls": res.castability_calls, "castability_seconds": res.castability_seconds,
            "dropped_moves": res.dropped_moves, "moves": res.moves, "move_rows": res.moves,
            "pob_calls": res.pob_calls, "tree_churn": res.tree_churn,
            "ledger_construction_value": res.ledger_construction_value,
            "ledger_value_before_final_lanes": res.ledger_value_before_final_lanes,
            "ledger_identity_error": res.ledger_identity_error,
            "considered": TRACE.considered(),
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc(), "skeleton": skeleton_json, "screen": screen, "seed": seed, "seconds": time.perf_counter() - t0, "considered": TRACE.considered()}


# -- seeds (D73) --------------------------------------------------------------------------
# One skeleton built twice is two different builds: the loot roll of gear pass 1 and the
# loop's kicks take the seed, and the expected best of K seeds is 153.6 / 165.5 / 171.0 /
# 174.4 % of the author for K = 1..4 (2026-09-18, docs/research/2026-09-18-restarts-statistics.md).
# So the full stage builds every finalist `seeds` times and delivers the best; the rest are
# kept for the spread.


def seed_jobs(batch: Sequence[tuple[Any, str, int]], seeds: int) -> list[tuple[Any, str, int]]:
    """(skeleton, tag, first seed) -> one job per (skeleton, seed), seeds counting up from
    the first. The pool sees them all at once: 2 finalists x 3 seeds = 6 parallel jobs."""

    n = max(1, int(seeds))
    return [(sk, tag, int(first) + i) for sk, tag, first in batch for i in range(n)]


def _seed_rank(res: Any) -> tuple[bool, float, float, int]:
    """The objective's Score order (feasibility, then the violation, then the value), ties
    to the lowest seed. Smaller is better, so the first element of a sorted group wins."""

    return (not bool(res.get("feasible")), float(res.get("violation") or 0.0), -float(res.get("value") or 0.0), int(res.get("seed") or 0))


def best_by_seed(results: Iterable[Any]) -> tuple[list[dict], list[dict]]:
    """Group the seeds of one finalist by `tag` and keep the best build by Score.

    Returns (winners, others): every winner carries `seed`, `seed_values` (best first) and
    `seed_runs` (one row per seed, for the report); `others` are the losing seeds' builds,
    which the search writes next to the winner so the spread is visible."""

    groups: dict[str, list[dict]] = {}
    for res in results:
        groups.setdefault(str(res.get("tag") or ""), []).append(res if isinstance(res, dict) else dict(res))
    winners: list[dict] = []
    others: list[dict] = []
    for runs in groups.values():
        runs.sort(key=_seed_rank)
        best = runs[0]
        best["seed"] = int(best.get("seed") or 0)
        best["seed_runs"] = [{"seed": int(r.get("seed") or 0), "value": float(r.get("value") or 0.0), "violation": float(r.get("violation") or 0.0),
                              "feasible": bool(r.get("feasible")), "seconds": float(r.get("seconds") or 0.0), "best": r is best}
                             for r in sorted(runs, key=lambda r: int(r.get("seed") or 0))]
        best["seed_values"] = [float(r.get("value") or 0.0) for r in runs]  # already sorted best first
        winners.append(best)
        others.extend(runs[1:])
    return winners, others


def seed_spread(values: Sequence[float]) -> float:
    """(max - min) / max over the seeds' values: what one seed of luck is worth, as a share
    of the delivered build. 0.0 for a single seed."""

    vals = [float(v) for v in values]
    if len(vals) < 2 or max(vals) <= 0:
        return 0.0
    return (max(vals) - min(vals)) / max(vals)


def format_seeds(result: Any) -> str:
    """The report's one-line account of a delivered build's seeds."""

    runs = result.get("seed_runs") or []
    if not runs:
        return ""
    values = result.get("seed_values") or sorted((float(r["value"]) for r in runs), reverse=True)
    if len(runs) == 1:
        return f"one seed (seed {int(result.get('seed') or 0)}): {values[0]:,.0f}."
    return (f"best of {len(runs)} seeds (seed {int(result.get('seed') or 0)}): " + " / ".join(f"{v:,.0f}" for v in values)
            + f"; spread {seed_spread(values):.1%} of the best.")


__all__ = ["prepare_candidate", "optimize", "seed_jobs", "best_by_seed", "seed_spread", "format_seeds"]
