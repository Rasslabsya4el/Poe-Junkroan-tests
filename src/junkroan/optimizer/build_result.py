"""`BuildResult`, `StageRecord` and the two writers every stage of `BuildPipeline` shares (#51).

Moved out of pipeline.py unchanged; pipeline.py re-exports `BuildResult`, `StageRecord` and `REPORT_KEYS`.
Nothing here imports pipeline.py.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from junkroan.optimizer.audit import Finding, floors_cell
from junkroan.optimizer.move_ledger import render_move_table, render_pob_calls
from junkroan.optimizer import yield_probe
from junkroan.optimizer.objective import bossing_defence
from junkroan.report_format import human_duration
from junkroan.search.skeleton import Skeleton

if TYPE_CHECKING:
    from junkroan.search.generator import SkeletonGenerator


def _number(v: object) -> str:
    """A PoB number as the report prints it; a value the result does not hold reads n/a, never 0 (#1055)."""

    return f"{v:,.0f}" if isinstance(v, (int, float)) else "n/a"


REPORT_KEYS = ("CombinedDPS", "FullDPS", "Life", "EnergyShield", "TotalEHP", "FireResist", "ColdResist", "LightningResist", "ChaosResist", "EffectiveMovementSpeedMod",
               "Str", "Dex", "Int", "ReqStr", "ReqDex", "ReqInt", "ManaUnreserved", "ManaCost",
               "PhysicalMaximumHitTaken", "FireMaximumHitTaken", "ColdMaximumHitTaken", "LightningMaximumHitTaken")


@dataclass(slots=True)
class StageRecord:
    name: str
    seconds: float
    stats: dict[str, Any]
    score_value: float
    violation: float
    notes: str = ""


@dataclass(slots=True)
class BuildResult:
    skeleton: Skeleton
    objective_stat: str = "CombinedDPS"
    stages: list[StageRecord] = field(default_factory=list)
    final_stats: dict[str, Any] = field(default_factory=dict)
    conservative_stats: dict[str, Any] = field(default_factory=dict)
    optimistic_stats: dict[str, Any] = field(default_factory=dict)
    config_reasons: dict[str, str] = field(default_factory=dict)
    import_code: str = ""
    xml: str = ""
    seconds: float = 0.0
    audit: list[Finding] = field(default_factory=list)
    keystones: list[str] = field(default_factory=list)  # keystones allocated in the final tree (D40)
    picks: list[dict] = field(default_factory=list)  # what PoB chose (skill part, supports, utilities) with the value before/after
    tree_steps: list[dict] = field(default_factory=list)  # kept tree steps with their measured gains
    explanation: str = ""  # optimizer/explain.py
    mapping: list[str] = field(default_factory=list)  # optimizer/mapping.py: what pays only on maps, and what is missing (text, never a score)
    gear_mode: str = "loot"  # which day-1 gear the build wears: the loot simulation (D19) or the wishlist (D68)
    fixed_point_gain: float = 0.0  # ROADMAP 7.3: what the LAST extra pass of the loop's local moves gained after `_finish` (0 = the delivered build is at a fixed point of the extra pass, #800)
    fixed_point_note: str = ""  # "" = not checked, "kept nothing", "stopped on the <reason>", or the moves that pass kept
    fixed_point_moved: bool = False  # #800: an extra pass kept a move (`fixed_point_gain` is the LAST pass's, so 0 does not say the build is the loop's)
    fixed_point_passes: int = 0  # #800: how many extra passes ran (1 = the first kept nothing; at most 3)
    loop_stop: str = ""  # #38: "converged" (a pass kept nothing) or "time" (stopped on loop_max_seconds); "" if the loop never ran (screen, construction_only)
    pending_facts: list[str] = field(default_factory=list)  # researched facts the user has not approved that would move this build's number (D62, mechanics/pending_facts.json)
    pinnacle_ramp_dps: float | None = None  # report-only 10 s projection from the same ramp model (D78)
    pinnacle_ramp_seconds: float | None = None
    gear_shopping: list[dict[str, object]] = field(default_factory=list)  # D79: final template items and measured open-line deltas
    floors_missed: list[str] | None = None  # every floor/relation of the objective the delivered build misses, worst first (#704); None = not evaluated
    dropped_moves: list[dict[str, str]] = field(default_factory=list)  # recoverable contract failures from improvement-loop moves
    tree_leaves: list[Any] = field(default_factory=list)  # every removable leaf and its measured removal cost (tree_hygiene.py)
    castability_calls: int = 0  # full/single active-skill reads that refreshed frozen cost floors
    castability_seconds: float = 0.0
    moves: list[dict[str, Any]] = field(default_factory=list)
    weapon_base_skipped: dict[str, int] = field(default_factory=dict)
    pob_calls: dict[str, dict[str, float | int]] = field(default_factory=dict)
    tree_churn: dict[str, float] = field(default_factory=dict)
    construction_tree: list[int] = field(default_factory=list)
    ledger_construction_value: float | None = None
    ledger_value_before_final_lanes: float | None = None
    ledger_identity_error: float | None = None

    @property
    def move_rows(self) -> list[dict[str, Any]]:
        """Compatibility name used by replay bench rows."""

        return self.moves

    @property
    def scored_stat(self) -> str:
        """The PoB output the objective maximised: the one key the header, the final line and the report table name (#801)."""

        return getattr(self, "objective_stat", None) or "CombinedDPS"

    def scored_number(self) -> float | None:
        """The real number of the output the objective maximised (#1055). `final_stats` holds PoB's report keys
        and the derived values only, so a dot build's TotalDotDPS is not in it; the number is then the last
        stage's score, the objective's own value on the build that stage left (saved Contagion result: stage
        `config (final lanes)` = `value` = 37,844). None when neither holds a finite number: the caller prints n/a."""

        v = self.final_stats.get(self.scored_stat)
        if isinstance(v, (int, float)):
            return float(v)
        last = self.stages[-1].score_value if self.stages else None
        return float(last) if isinstance(last, (int, float)) and math.isfinite(last) else None

    def saved_optimistic(self) -> dict[str, Any]:
        """The optimistic-lane numbers a saved result keeps (#1057): the maximised output under its own name, plus CombinedDPS."""

        return {k: self.optimistic_stats[k] for k in dict.fromkeys((self.scored_stat, "CombinedDPS")) if isinstance(self.optimistic_stats.get(k), (int, float))}

    def summary(self) -> str:
        number = self.scored_number()
        lines = [f"build for {self.skeleton.class_name}/{self.skeleton.ascendancy} {' + '.join(self.skeleton.main_link[:1])} in {human_duration(self.seconds)}" + (f"  [objective {self.scored_stat} = {_number(number)}]" if self.scored_stat != "CombinedDPS" and number else "") + f"  [dropped moves: {len(self.dropped_moves)}]"]
        for s in self.stages:
            ramp, budget = s.stats.get("RampSeconds"), s.stats.get("RampBudget")
            lines.append(f"  {s.name:28s} {human_duration(s.seconds):>9s}  value {s.score_value:>12,.0f}  viol {s.violation:.3f}" + (f"  ramp {human_duration(float(ramp))}" + (f"/{human_duration(float(budget))}" if isinstance(budget, (int, float)) else "") if isinstance(ramp, (int, float)) else "") + f"  {s.notes}")
        f = self.final_stats
        if f:
            dps_key = self.scored_stat  # #801: the output the objective maximised, named as PoB names it
            lines.append(
                f"  final: {dps_key} {_number(number)} (optimistic {_number(self.optimistic_stats.get(dps_key))}) life {f.get('Life')} "
                f"max hit {bossing_defence(f):,.0f} ehp {f.get('TotalEHP', 0):,.0f} res {f.get('FireResist')}/{f.get('ColdResist')}/{f.get('LightningResist')}/{f.get('ChaosResist')} "
                f"attr {f.get('Str')}/{f.get('Dex')}/{f.get('Int')} req {f.get('ReqStr')}/{f.get('ReqDex')}/{f.get('ReqInt')} ms {f.get('EffectiveMovementSpeedMod', 0):.2f}"
                + (f" ramp {human_duration(float(f['RampSeconds']))}" + (f"/{human_duration(float(f['RampBudget']))}" if isinstance(f.get("RampBudget"), (int, float)) else "") if isinstance(f.get("RampSeconds"), (int, float)) else "")
            )
        if isinstance(self.pinnacle_ramp_dps, (int, float)) and isinstance(self.pinnacle_ramp_seconds, (int, float)):
            lines.append(f"  pinnacle boss ramp ({human_duration(self.pinnacle_ramp_seconds)}): {self.objective_stat} {self.pinnacle_ramp_dps:,.0f}")
        lines.append(f"  floors: {floors_cell(self.floors_missed)}")
        for finding in self.audit:
            lines.append(f"  audit {finding}")
        lines.extend(render_move_table(self.moves, heading="  loop moves"))
        lines.extend(render_pob_calls(self.pob_calls, heading="  PoB calls"))
        return "\n".join(lines)


def stage_record(pob: Any, objective: Any, result: BuildResult, name: str, t0: float, notes: str = "") -> StageRecord:
    """The record of the build PoB holds now, not yet written to the result."""

    stats = pob.stats(REPORT_KEYS)
    full = pob.stats(objective.stat_keys)
    score = objective.score(full)
    stats.update(objective.derived_values(full))
    if notes == "no change" and result.stages:
        # a stage that changed nothing must leave the number where it found it: the re-judge's restore wrote
        # minion count 1 and reported "no change" at 6% of the value through two benchmark runs (SRS, 2026-09-15)
        prev = result.stages[-1].score_value
        if prev > 0 and abs(score.value - prev) > 0.02 * prev:
            raise RuntimeError(f"stage {name!r} reported no change but the value moved {prev:,.0f} -> {score.value:,.0f}: a setter or restore is not faithful")
    return StageRecord(name=name, seconds=time.perf_counter() - t0, stats=stats, score_value=score.value, violation=score.violation, notes=notes)


def commit_stage(result: BuildResult, record: StageRecord, log: Callable[[str], Any]) -> None:
    result.stages.append(record)
    # The summary may end in the move ledger table. The stage line remains
    # the line immediately after the summary header and prior stage lines.
    line = result.summary().splitlines()[len(result.stages)]
    if len(result.stages) > 1 and result.stages[-2].score_value > 0:  # before/after of every stage in the log (7.1e)
        line += f"  [{record.score_value / result.stages[-2].score_value - 1:+.1%} vs {result.stages[-2].name}]"
    log(line)
    yield_probe.check(record.name)  # #621: a stage boundary


def record_stage(pob: Any, objective: Any, result: BuildResult, name: str, t0: float, notes: str = "", log: Callable[[str], Any] = print) -> None:
    commit_stage(result, stage_record(pob, objective, result, name, t0, notes), log)


def take_picks(result: BuildResult, gen: "SkeletonGenerator", *, before: float | None) -> None:
    for p in gen.picks:
        result.picks.append({"what": p.what, "choice": p.choice, "value": p.score.value, "before": before, "seconds": p.seconds})
