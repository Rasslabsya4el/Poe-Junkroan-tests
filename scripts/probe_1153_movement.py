"""#1153 row 2: the movement pair on a delivered SEARCH build, trace counters on.

    python scripts/probe_1153_movement.py "<delivered .pob.txt>" [--seed N]

`replay_bench.py` prepares an author from a benchmark reference; a search output (A1, B1) has none. This loads the
delivered build, derives the objective the way `BuildPipeline.run` does (`objective_for(rails, main skill, mode)`),
builds the replay state with `replay_bench._pipeline_state`, and runs the `utilities` move (`utilities_replay`):
the utility pick step as `pipeline.py` gates and calls it. The picker is greedy, so the seed names the run only.
Prints the trace table (move x class, generated/evaluated) restricted to the movement classes, and the movement
gems the build holds before and after.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from replay_bench import _pipeline_state, trace_table_lines, utilities_replay  # noqa: E402
from build_from_skeleton import skeleton_from_xml  # noqa: E402
from junkroan.optimizer.objective_select import forced_keystones_of, objective_for  # noqa: E402
from junkroan.optimizer.pipeline import BuildResult  # noqa: E402
from junkroan.optimizer.rails import Rails  # noqa: E402
from junkroan.optimizer.trace import TRACE  # noqa: E402
from junkroan.pob.session import PobSession  # noqa: E402
from junkroan.report_format import human_duration  # noqa: E402
from junkroan.search.generator import movement_kind, movement_rails  # noqa: E402


def movement_gems(skeleton, rails) -> dict[str, list[str]]:
    """The movement gems the build holds, by slot, and the groups they sit in (enabled only)."""

    mv = movement_rails(rails)
    held: dict[str, list[str]] = {"spell": [], "skill": []}
    for grp in skeleton.extra_groups:
        for gem in grp.gems:
            kind = movement_kind(gem, mv)
            if kind and grp.enabled:
                held[kind].append(f"{gem} [{' + '.join(grp.gems)}]")
    return held


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("build", help="a delivered .pob.txt")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    path = Path(args.build)
    started = time.perf_counter()
    rails = Rails.load()
    TRACE.reset()
    with PobSession(run_id=f"probe1153-{path.stem[:20]}") as pob:
        pob.load_import_code(path.read_text(encoding="utf-8").strip())
        skeleton0 = skeleton_from_xml(pob.export_xml(), pob=pob, log=lambda m: None)
        objective = objective_for(rails, skeleton0.main_link[0], rails.objective(), mode=skeleton0.mode, forced_keystones=forced_keystones_of(skeleton0))
        prepared = SimpleNamespace(rails=rails, objective=objective)
        pipeline, skeleton, _gear, _tree = _pipeline_state(pob, prepared, gear_mode="loot", log=lambda m: None)
        before_stats = pob.stats(objective.stat_keys)
        before = objective.score(before_stats)
        held_before = movement_gems(skeleton, rails)
        result = BuildResult(skeleton=skeleton, objective_stat=objective.maximize, gear_mode="loot")
        note = utilities_replay(pipeline, result, skeleton)
        after = objective.score(pob.stats(objective.stat_keys))
        held_after = movement_gems(skeleton, rails)
        considered = TRACE.considered()
    movement = {m: {c: v for c, v in per.items() if c.startswith("movement-")} for m, per in considered.items()}
    movement = {m: per for m, per in movement.items() if per}
    print(f"build: {path.name}  seed {args.seed}  main {skeleton.main_link[0]}  stat {objective.maximize}")
    print(f"value {before.value:,.0f} -> {after.value:,.0f} (violation {before.violation:.3f} -> {after.violation:.3f})")
    print(f"utilities picked: {note}")
    print(f"movement before: {held_before}")
    print(f"movement after:  {held_after}")
    print()
    print("\n".join(trace_table_lines(movement)))
    print()
    print(f"took {human_duration(time.perf_counter() - started)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
