"""#1164 rows 3 and 4: does the forcing repair keep its points, and which repair is unaffected by the fix?

Row 3 (this script measures the HEAD only: it is not on main, so the base cannot be pinned; the base collapse 102 -> 6
is the figure from the issue text). Loads a stand (default `artifacts/stands-1124/spark-s4.pob.txt`), forces the stand's
unique bundle (the `unique_probe` of `bundle_select`: Glancing Blows + Cybil's Paw, Thresher Claw in Weapon 1) through
`BuildPipeline.repair` (direction `force`, the path `scripts/run_bundles.py` takes) and prints, in plain lines, the allocated
points (`points_used` of `PobSession.mutate_nodes()`) before the repair, after it, the forced count (the number of ids in
the forced bundle). The row's criterion:
`points_used` after stays at the value before +/- the forced count; exit 1 and a `COLLAPSE` line when
|after - before| > forced count. One PobSession, the whole repair: a long run, submitted through `scripts/runs.py`; the
job's rc is the script's rc.

    python scripts/check_1164_points.py
    python scripts/check_1164_points.py --dry-run          # the bundle that would be forced, no PoB
    python scripts/runs.py submit --issue 1164 --priority P1 --pin <orch-1164 sha> -- python scripts/check_1164_points.py

Row 4 is not this script's PoB run: it is `scripts/repair_calibrate.py --record-calls` + `scripts/compare_calls.py` on
smite-s4 + Blood Magic, the stand this script's graph check names as the control (base pinned at main b0ba5fcd, head
after it with `--after <base job>`, same command both sides):

    python scripts/runs.py submit --issue 1164 --priority P1 --pin b0ba5fcd -- python scripts/repair_calibrate.py --pairs "artifacts/benchmark/20261013-0101-P2-core-3/rows/smite-s4.json:artifacts/benchmark/20261014-1638-P1-#1029-3/rows/smite-s4-with-blood_magic.json:Blood Magic" --direction force --workers 1 --tag p1164-base --record-calls artifacts/proof-1164/base
    python scripts/runs.py submit --issue 1164 --priority P1 --pin <orch-1164 sha> --after <base job> -- python scripts/repair_calibrate.py --pairs "<the same pair>" --direction force --workers 1 --tag p1164-head --record-calls artifacts/proof-1164/head
    python scripts/compare_calls.py artifacts/proof-1164/base artifacts/proof-1164/head

`--check-unaffected STAND...` is the graph check, no PoB: for each import code the class start that is not the build's own
and is adjacent to the allocation (the `TreeGraph.roots` defect needs one). With `--keystone NAME` the path that forcing the
keystone would allocate counts too. AFFECTED stands (exit 1) reproduce the defect; UNAFFECTED ones are the control whose
PoB call transcript must stay identical.

    python scripts/check_1164_points.py --check-unaffected artifacts/stands-1124/*-s4.pob.txt
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Sequence
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from replay_bench import _pipeline_state, _prepared_author  # noqa: E402
from run_bundles import DEFAULT_SOURCE_RUN, _resolved, _stand_xml, make_info_of, mastery_lines  # noqa: E402
from junkroan.optimizer.bundle_fit import GRAPH_PATH, load_bundle_graph  # noqa: E402
from junkroan.optimizer.bundle_select import stand_from_xml, unique_probe  # noqa: E402
from junkroan.optimizer.improvement_loop import WorkingBuild  # noqa: E402
from junkroan.optimizer.pipeline import BuildResult  # noqa: E402
from junkroan.optimizer.repair import RepairChoice  # noqa: E402
from junkroan.optimizer.tree_graph import TreeGraph, parse_allocated_from_xml  # noqa: E402
from junkroan.pob.session import PobSession  # noqa: E402
from junkroan.report_format import human_duration  # noqa: E402

DEFAULT_STAND = "artifacts/stands-1124/spark-s4.pob.txt"


# -- row 3: one forcing repair -----------------------------------------------------------------------------------------

def _points(pob: Any) -> int:
    return int(pob.mutate_nodes()["points_used"])


def run(pob: Any, *, code: str, prepared: Any, state_factory: Callable[..., tuple], ids: Sequence[str], mastery_lines: dict[str, str],
        gear_mode: str, seed: int, out: Callable[[str], None] = print) -> int:
    """Load `code`, force the bundle `ids` through `pipeline.repair`, print the three numbers; 1 when the points moved by more than the forced count, else 0."""

    logs: list[str] = []
    pob.load_import_code(code)
    pipeline, skeleton, gear, tree = state_factory(pob, prepared, gear_mode=gear_mode, log=logs.append)
    working = WorkingBuild(pob=pob, judging=pipeline.judging, skeleton=skeleton, gear=gear, tree=tree)
    result = BuildResult(skeleton=skeleton, objective_stat=pipeline.objective.maximize, gear_mode=gear_mode)
    before = _points(pob)
    pipeline.repair(working, result, RepairChoice(direction="force", bundle=tuple(ids), mastery_lines=dict(mastery_lines)), seed=seed)
    after = _points(pob)
    forced = len(ids)
    out(f"points_used before the repair: {before}")
    out(f"points_used after the repair: {after}")
    out(f"forced count: {forced} (the bundle's ids)")
    if abs(after - before) > forced:
        out(f"COLLAPSE: {after} points after, {before} before, more than the forced count {forced} apart")
        return 1
    out(f"no collapse: {after} points after, {before} before, within the forced count {forced}")
    return 0


def unique_job(stand: Path) -> dict[str, Any]:
    """The unique bundle the stand forces (no PoB): its ids and the mastery lines of its graph edge."""

    xml = _stand_xml(stand)
    graph = load_bundle_graph()
    bundle = unique_probe(GRAPH_PATH, xml, graph, stand_from_xml(xml), TreeGraph.load().allocatable)
    if bundle is None:
        raise SystemExit(f"no unique bundle fits {stand.name}")
    return {"ids": bundle.ids, "names": [graph.node(i).name for i in bundle.ids], "mastery_lines": mastery_lines(bundle.ids, bundle.edge)}


def measure(stand: Path, source_run: Path, seed: int) -> int:
    job = unique_job(stand)
    info = make_info_of(source_run)(stand)
    started = time.perf_counter()
    print(f"{stand.name}: forcing {' + '.join(job['names'])} ({info['stat']}, gear {info['gear_mode']}, seed {seed})", flush=True)
    with PobSession(run_id=f"check1164-{os.getpid()}") as pob:
        prepared = _prepared_author(pob, info["slug"], info["stat"], lambda line: None)
        rc = run(pob, code=stand.read_text(encoding="utf-8").strip(), prepared=prepared, state_factory=_pipeline_state,
                 ids=job["ids"], mastery_lines=job["mastery_lines"], gear_mode=info["gear_mode"], seed=seed)
    print(f"total {human_duration(time.perf_counter() - started)}")
    return rc


# -- row 4: the graph check ----------------------------------------------------------------------------------------------

def foreign_starts_next_to(stand: Path, keystone: str | None = None) -> list[tuple[str, int]]:
    """(class, start node) of every class start but the build's own that is adjacent to the stand's allocation; with a
    keystone name, to the allocation plus the shortest path forcing it would add. `TreeGraph.roots` took such a start as a
    root, so the trim then saw the own trunk as leaves (#1147)."""

    xml = _stand_xml(stand)
    graph = TreeGraph.load()
    own = ET.fromstring(xml).find("Build").get("className")
    allocated = set(parse_allocated_from_xml(xml))
    if keystone:
        wanted = keystone.strip().lower()
        ids = [n.node_id for n in graph.nodes.values() if n.kind == "keystone" and n.name.lower() == wanted]
        if not ids:
            raise SystemExit(f"no keystone named {keystone!r}")
        reach = graph.bfs_costs(allocated, max_depth=40)
        if ids[0] in reach:
            allocated |= set(reach[ids[0]][1])
    return sorted((cls, start) for cls, start in graph.class_starts.items() if cls != own and graph.neighbours(start) & allocated)


def check_unaffected(stands: Sequence[Path], keystone: str | None) -> int:
    affected = 0
    for stand in stands:
        found = foreign_starts_next_to(stand, keystone)
        affected += bool(found)
        detail = ", ".join(f"{cls} start {node}" for cls, node in found) or "no foreign class start next to the allocation"
        print(f"{stand.name}: {'AFFECTED' if found else 'UNAFFECTED'} ({detail}){' with the path to ' + keystone if keystone else ''}")
    return 1 if affected else 0


# -- the command ---------------------------------------------------------------------------------------------------------

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--stand", default=DEFAULT_STAND, help="the stand's import code file")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--source-run", default=DEFAULT_SOURCE_RUN, help="the benchmark run whose results.json knows the stand's skill")
    parser.add_argument("--dry-run", action="store_true", help="print the bundle that would be forced, open no PoB")
    parser.add_argument("--check-unaffected", nargs="+", metavar="STAND", help="the graph check of row 4 on these import code files; no PoB")
    parser.add_argument("--keystone", help="with --check-unaffected: count the path forcing this keystone adds")
    args = parser.parse_args(argv)

    if args.check_unaffected:
        return check_unaffected([_resolved(p) for p in args.check_unaffected], args.keystone)
    stand = _resolved(args.stand)
    if args.dry_run:
        job = unique_job(stand)
        print(f"{stand.name}: would force {' + '.join(job['names'])} ({', '.join(job['ids'])})")
        return 0
    return measure(stand, _resolved(args.source_run), args.seed)


if __name__ == "__main__":
    sys.exit(main())
