"""Run bundles of the bundle graph on stands and write the catalogue (#1147, unit 5b).

For every (bundle, stand) pair the fit check runs first (`bundle_fit.check_bundle`, no PoB call): a bundle that does not
fit gets its `does_not_fit` record in this process, with no job and no PoB session. Every other pair is one job: the
stand is loaded into PoB, the working build is made NEW (the repair mutates the skeleton, gear and tree in place, so a
build is never reused), the bundle is forced through `pipeline.repair` (direction `force`), and the main process writes
one catalogue record per job, in task order (stand name, then bundle ids), whatever order the pool finishes in.

    python scripts/run_bundles.py --acceptance --stands "artifacts/stands-1124/*-s4.pob.txt" --workers auto
    python scripts/run_bundles.py --bundles artifacts/catalogue/day1-bundles.json --stands "artifacts/stands-1124/spark-s4.pob.txt"

`--bundles` reads a JSON list of {"ids": [sorted graph node ids], "edge": <graph edge or null>, "stand": <file name,
optional>}; `--acceptance` writes that file by the issue's rule (`bundle_select`: two bundles per stand, one
`does_not_fit` probe per stand, and with `--with-unique` one unique bundle on the first stand) and runs it.
"""

from __future__ import annotations

import argparse
import glob
import json
import multiprocessing.util
import os
import subprocess
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Collection, Iterable, Iterator, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from replay_bench import _pipeline_state, _prepared_author, source_info  # noqa: E402
from junkroan.optimizer import catalogue  # noqa: E402
from junkroan.optimizer.bundle_fit import GRAPH_PATH, BundleFit, BundleGraph, check_bundle, load_bundle_graph  # noqa: E402
from junkroan.optimizer.bundle_select import acceptance_bundles, does_not_fit_probe, stand_from_xml, unique_probe  # noqa: E402
from junkroan.optimizer.improvement_loop import WorkingBuild  # noqa: E402
from junkroan.optimizer.pipeline import BuildResult  # noqa: E402
from junkroan.optimizer.repair import RepairChoice, repair_verdict  # noqa: E402
from junkroan.optimizer.trace import TRACE  # noqa: E402
from junkroan.pob.session import PobSession, decode_import_code  # noqa: E402
from junkroan.pob.slot_budget import ROLE_OTHER, available_ram_gb, busy_slots, load_budget  # noqa: E402
from junkroan.report_format import human_duration  # noqa: E402
from junkroan.runs.yield_plan import limited_completions  # noqa: E402

DEFAULT_STANDS = "artifacts/stands-1124/*-s4.pob.txt"
DEFAULT_SOURCE_RUN = "artifacts/benchmark/20261013-0101-P2-core-3"  # the run whose results.json knows the stands' skills
ACCEPTANCE_PATH = catalogue.CATALOGUE_PATH.parent / "day1-bundles.json"
GB_PER_WORKER = 1.0  # one PoB runtime process holds about 1 GB (docs/agents/machine.md)

Execute = Callable[[list[dict[str, Any]], int], Iterable[tuple[int, dict[str, Any]]]]


# -- the bundles file and the plan ------------------------------------------------------------------------------------

@dataclass(frozen=True)
class BundleSpec:
    """One bundle to run: its graph node ids (sorted), the graph edge it came from (null for a hand-made bundle) and
    the stand file name it is scoped to (None = every stand)."""

    ids: tuple[str, ...]
    edge: dict | None = None
    stand: str | None = None


@dataclass(frozen=True)
class Task:
    index: int
    stand: Path
    spec: BundleSpec
    fit: BundleFit


def load_bundles(path: Path | str) -> list[BundleSpec]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    specs: list[BundleSpec] = []
    for row in rows:
        ids = list(row["ids"])
        if not ids or ids != sorted(set(ids)):
            raise ValueError(f"bundle ids must be sorted and unique, got {ids!r}")
        specs.append(BundleSpec(ids=tuple(ids), edge=row.get("edge"), stand=row.get("stand")))
    return specs


def _stand_xml(path: Path) -> str:
    return decode_import_code(path.read_text(encoding="utf-8").strip())


def plan(stand_files: Iterable[Path | str], bundles: Sequence[BundleSpec], graph: BundleGraph) -> list[Task]:
    """Every (stand, bundle) pair in the order the catalogue is written (stand file name, then bundle ids), each with its fit."""

    tasks: list[Task] = []
    for path in sorted({Path(p) for p in stand_files}, key=lambda p: (p.name, str(p))):
        stand = stand_from_xml(_stand_xml(path))
        for spec in sorted((s for s in bundles if s.stand in (None, path.name)), key=lambda s: s.ids):
            tasks.append(Task(index=len(tasks), stand=path, spec=spec, fit=check_bundle(spec.ids, graph, stand)))
    return tasks


def mastery_lines(ids: Iterable[str], edge: Mapping[str, Any] | None) -> dict[str, str]:
    """The line of each mastery node of the bundle, from the graph edge it came from (`from_line` / `to_line`)."""

    lines: dict[str, str] = {}
    for end, key in (("from", "from_line"), ("to", "to_line")):
        node_id = (edge or {}).get(end)
        if node_id in set(ids) and str(node_id).startswith("mastery:") and (edge or {}).get(key):
            lines[node_id] = edge[key]
    return lines


# -- one measurement on one PoB session ---------------------------------------------------------------------------------

def _pob_call_count(pob: Any) -> int:
    return sum(int(kind.get("count", 0)) for kind in pob.pob_calls().values())


def measure_with_session(pob: Any, job: Mapping[str, Any], *, prepared: Any, state_factory: Callable[..., tuple]) -> dict[str, Any]:
    """Load the stand, make a NEW working build around it, force the bundle, and return the numbers as a plain dict.

    Nothing is reused between calls: the repair mutates the skeleton, gear and tree in place and `wire_tree` / `relane`
    hold references to the skeleton, so a copy made after wiring would still point into the old state. A failure is a
    result (`ok` False), never an exception. The catalogue is not written here."""

    started = time.perf_counter()
    try:
        pob.reset_pob_calls()
        pob.load_import_code(Path(job["stand"]).read_text(encoding="utf-8").strip())
        logs: list[str] = []
        pipeline, skeleton, gear, tree = state_factory(pob, prepared, gear_mode=job["gear_mode"], log=logs.append)
        working = WorkingBuild(pob=pob, judging=pipeline.judging, skeleton=skeleton, gear=gear, tree=tree)
        result = BuildResult(skeleton=skeleton, objective_stat=pipeline.objective.maximize, gear_mode=job["gear_mode"])
        ids = tuple(job["ids"])
        choice = RepairChoice(direction="force", bundle=ids, mastery_lines=mastery_lines(ids, job.get("edge")))
        outcome = pipeline.repair(working, result, choice, seed=job["seed"])
        metric = pipeline.objective.maximize
        final = float(pipeline.objective.score(pob.stats(pipeline.objective.stat_keys)).value)  # the state the import code opens
        values = [float(v) for v in outcome.values]
        verdict = outcome.verdict or repair_verdict(float(outcome.start), values)
        notes = [stage.notes for stage in getattr(result, "stages", ()) if stage.name == "repair pass 0" and stage.notes]
        reason = f"{verdict}: {float(outcome.start):,.0f} -> {final:,.0f} {metric} after {len(values)} pass(es)" + (f"; {notes[0]}" if notes else "")
        code = catalogue.import_code_for(pob)
        return {"ok": True, "metric": metric, "base_value": float(outcome.start), "value": final,
                "last_pass_value": values[-1] if values else None, "verdict": verdict, "passes": len(values),
                "seconds": time.perf_counter() - started, "import_code": code, "reason": reason, "pob_calls": _pob_call_count(pob)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc(), "seconds": time.perf_counter() - started}


# -- the pool ---------------------------------------------------------------------------------------------------------

_SESSION: list[Any] = []  # the process's one PobSession, opened by its first job
_MEAN_PARTS: dict[tuple[str, str], Any] = {}  # per author: `mean_parts` as its preparation set it


def _worker_session() -> Any:
    if not _SESSION:
        pob = PobSession(run_id=f"bundles-{os.getpid()}").__enter__()
        multiprocessing.util.Finalize(None, pob.close, exitpriority=10)  # closed when the worker process exits
        _SESSION.append(pob)
    return _SESSION[0]


def measure_job(job: dict[str, Any]) -> dict[str, Any]:
    """One job in a pool process (a failure is a result)."""

    started = time.perf_counter()
    try:
        TRACE.reset()
        pob = _worker_session()
        key = (job["slug"], job["stat"])
        prepared = _prepared_author(pob, job["slug"], job["stat"], lambda line: None)
        # preparing an author sets `pob.mean_parts` (a random-element skill); a later job of another author must not inherit it
        pob.mean_parts = _MEAN_PARTS.setdefault(key, pob.mean_parts)
        return measure_with_session(pob, job, prepared=prepared, state_factory=_pipeline_state)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc(), "seconds": time.perf_counter() - started}


def pool_execute(jobs: list[dict[str, Any]], workers: int) -> Iterator[tuple[int, dict[str, Any]]]:
    """The jobs on a pool of `workers` processes, each holding one PobSession for all its jobs; yields in completion order."""

    with ProcessPoolExecutor(max_workers=workers) as pool:
        for future, job in limited_completions(lambda j: pool.submit(measure_job, j), jobs, workers):
            try:
                result = future.result()
            except Exception as exc:  # a worker process that died
                result = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "seconds": 0.0}
            yield job["index"], result


# -- the run ----------------------------------------------------------------------------------------------------------

def _names(ids: Iterable[str], graph: BundleGraph) -> str:
    return " + ".join(graph.node(i).name for i in ids)


def run_bundles(stands: Iterable[Path | str], bundles: Sequence[BundleSpec], out: Path | str, *, graph: BundleGraph, seed: int,
                workers: int, commit: str, info_of: Callable[[Path], Mapping[str, Any]],
                execute: Execute | None = None) -> list[dict[str, Any]]:
    """Plan, measure and append the records to `out`; returns one row per task, in task order."""

    tasks = plan(stands, bundles, graph)
    infos = {task.stand: info_of(task.stand) for task in tasks}
    shas = {path: catalogue.stand_sha256(path) for path in infos}
    entries: dict[int, tuple[dict[str, Any], catalogue.CatalogueRecord | None]] = {}
    written = 0

    def flush() -> None:
        nonlocal written
        while written < len(tasks) and written in entries:
            record = entries[written][1]
            if record is not None:
                catalogue.append(out, record)
            written += 1

    def row_of(task: Task, **fields: Any) -> dict[str, Any]:
        row = {"stand": task.stand.name, "bundle": _names(task.spec.ids, graph), "base_value": None, "value": None, "gain": None,
               "verdict": "", "seconds": 0.0, "pob_calls": 0, "ok": True, "error": ""}
        row.update(fields)
        return row

    def record_of(task: Task, **fields: Any) -> catalogue.CatalogueRecord:
        return catalogue.CatalogueRecord(bundle=list(task.spec.ids), edge=task.spec.edge, stand=task.stand.name, stand_sha256=shas[task.stand],
                                         seed=seed, commit=commit, **fields)

    jobs: list[dict[str, Any]] = []
    for task in tasks:
        info = infos[task.stand]
        if not task.fit.fits:
            record = record_of(task, metric=info["stat"], base_value=None, value=None, verdict=catalogue.DOES_NOT_FIT, reason=task.fit.reason,
                               seconds=0, passes=0, import_code=None)
            entries[task.index] = (row_of(task, verdict=catalogue.DOES_NOT_FIT), record)
            continue
        jobs.append({"index": task.index, "stand": str(task.stand), "ids": list(task.spec.ids), "edge": task.spec.edge, "seed": seed,
                     "stat": info["stat"], "gear_mode": info["gear_mode"], "slug": info["slug"]})
    flush()

    if jobs:
        for index, result in (execute or pool_execute)(jobs, workers):
            task = tasks[index]
            if result.get("ok"):
                record = record_of(task, metric=result["metric"], base_value=result["base_value"], value=result["value"], verdict=result["verdict"],
                                   reason=result["reason"], seconds=float(result["seconds"]), passes=int(result["passes"]), import_code=result["import_code"])
                entries[index] = (row_of(task, base_value=record.base_value, value=record.value, gain=record.gain, verdict=record.verdict,
                                         seconds=record.seconds, pob_calls=int(result.get("pob_calls", 0))), record)
            else:
                entries[index] = (row_of(task, verdict="FAILED", ok=False, error=str(result.get("error", "")), seconds=float(result.get("seconds") or 0.0)), None)
            row = entries[index][0]
            print(f"  {row['stand']:34s} {row['bundle']:60.60s} {row['verdict']:9s} {human_duration(row['seconds'])}", flush=True)
            flush()
    for task in tasks:  # a job the executor never answered
        if task.index not in entries:
            entries[task.index] = (row_of(task, verdict="FAILED", ok=False, error="no result came back"), None)
    flush()
    return [entries[i][0] for i in range(len(tasks))]


# -- the table --------------------------------------------------------------------------------------------------------

def _measured(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [r for r in rows if r.get("ok") and r.get("verdict") != catalogue.DOES_NOT_FIT]


def seconds_summary(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    seconds = [float(r["seconds"]) for r in _measured(rows)]
    return {"measured": len(seconds), "mean": sum(seconds) / len(seconds) if seconds else 0.0, "max": max(seconds, default=0.0)}


def _number(value: Any) -> str:
    return "-" if value is None else f"{float(value):,.0f}"


def render_table(rows: Sequence[Mapping[str, Any]]) -> str:
    lines = ["| stand | bundle | base_value | value | gain | verdict | duration |", "|---|---|---:|---:|---:|---|---:|"]
    for r in rows:
        gain = "-" if r.get("gain") is None else f"{float(r['gain']):+.1%}"
        duration = human_duration(float(r["seconds"])) if r.get("ok") and r.get("verdict") != catalogue.DOES_NOT_FIT else "-"
        lines.append(f"| {r['stand']} | {r['bundle']} | {_number(r.get('base_value'))} | {_number(r.get('value'))} | {gain} | {r['verdict']} | {duration} |")
    s = seconds_summary(rows)
    lines += ["", f"measured: {s['measured']}; mean {human_duration(s['mean'])}, max {human_duration(s['max'])} per measured bundle"]
    for r in rows:
        if not r.get("ok"):
            lines.append(f"FAILED {r['stand']} {r['bundle']}: {r['error']}")
    return "\n".join(lines)


# -- workers ----------------------------------------------------------------------------------------------------------

def _free_slots() -> int:
    budget = load_budget()
    return budget.limit_for(ROLE_OTHER) - len(busy_slots(budget=budget))


def _ram_workers() -> int:
    return int((available_ram_gb() - load_budget().min_free_ram_gb) / GB_PER_WORKER)


def resolve_workers(requested: int | str, jobs: int, free_slots: Callable[[], int] | None = None,
                    ram_workers: Callable[[], int] | None = None) -> int:
    """A number is kept (never wider than the jobs, at least 1); "auto" = the free slots, bounded by RAM and the jobs."""

    if str(requested).strip().lower() == "auto":
        count = min((free_slots or _free_slots)(), (ram_workers or _ram_workers)(), jobs)
    else:
        count = min(int(requested), jobs)
    return max(1, count)


# -- the acceptance set ---------------------------------------------------------------------------------------------------

def write_acceptance(stand_files: Iterable[Path | str], graph_json: Path | str, out: Path | str, *, graph: BundleGraph,
                     tree_allocatable: Collection[int], with_unique: bool) -> list[dict[str, Any]]:
    """Per stand (in file-name order): its two acceptance bundles and the does-not-fit probe; with `with_unique`, the unique
    probe on the first stand. Written to `out` as a bundles file."""

    entries: list[dict[str, Any]] = []
    for position, path in enumerate(sorted((Path(p) for p in stand_files), key=lambda p: p.name)):
        xml = _stand_xml(path)
        stand = stand_from_xml(xml)
        found = list(acceptance_bundles(graph_json, xml, graph, stand, tree_allocatable))
        found.append(does_not_fit_probe(graph_json, graph, stand))
        if with_unique and position == 0:
            found.append(unique_probe(graph_json, xml, graph, stand, tree_allocatable))
        entries += [{"ids": list(b.ids), "edge": b.edge, "stand": path.name} for b in found if b is not None]
    target = Path(out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return entries


# -- the command ------------------------------------------------------------------------------------------------------

def _resolved(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def make_info_of(source_run: Path) -> Callable[[Path], dict[str, Any]]:
    """The skill, stat and gear mode of a stand: from its own benchmark row, else from the row of the same name in the run
    that made the stands (stands carry no results.json, and the fallback of `source_info` is CombinedDPS / loot)."""

    def info_of(path: Path) -> dict[str, Any]:
        info = source_info(path)
        if not info.get("result_row"):
            info = source_info(source_run / path.name)
        if not info.get("result_row"):
            raise ValueError(f"no benchmark row for stand {path.name} in {source_run}: its stat and gear mode are not known")
        return info

    return info_of


def _commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument("--bundles", help="a bundles JSON file")
    what.add_argument("--acceptance", action="store_true", help="write the acceptance bundles of the stands (the issue's rule) and run them")
    parser.add_argument("--with-unique", action="store_true", help="with --acceptance: add the unique probe on the first stand")
    parser.add_argument("--stands", default=DEFAULT_STANDS, help="a glob of stand files (import codes)")
    parser.add_argument("--out", default=str(catalogue.CATALOGUE_PATH), help="the catalogue file; records are appended")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--workers", default="auto", help="a number, or auto = the free slots bounded by RAM")
    parser.add_argument("--source-run", default=DEFAULT_SOURCE_RUN, help="the benchmark run whose results.json knows the stands' skills")
    parser.add_argument("--dry-run", action="store_true", help="write the acceptance file if asked, print the plan with the fit checks, run nothing")
    args = parser.parse_args(argv)

    pattern = args.stands if Path(args.stands).is_absolute() else str(ROOT / args.stands)
    stands = sorted(Path(p) for p in glob.glob(pattern))
    if not stands:
        parser.error(f"--stands matched no files: {args.stands}")
    graph = load_bundle_graph()
    if args.acceptance:
        from junkroan.optimizer.tree_graph import TreeGraph

        bundles_path = ACCEPTANCE_PATH
        write_acceptance(stands, GRAPH_PATH, bundles_path, graph=graph, tree_allocatable=TreeGraph.load().allocatable, with_unique=args.with_unique)
    else:
        bundles_path = _resolved(args.bundles)
    bundles = load_bundles(bundles_path)
    tasks = plan(stands, bundles, graph)
    measurable = sum(1 for t in tasks if t.fit.fits)
    if args.dry_run:
        for t in tasks:
            print(f"{t.index:3d} {t.stand.name:34s} {'fits' if t.fit.fits else 'does_not_fit: ' + t.fit.reason:s} {_names(t.spec.ids, graph)}")
        print(f"{len(tasks)} tasks, {measurable} to measure")
        return 0
    workers = resolve_workers(args.workers, measurable)
    print(f"{len(tasks)} tasks ({measurable} to measure, {len(tasks) - measurable} does_not_fit) on {workers} worker(s)", flush=True)
    started = time.perf_counter()
    rows = run_bundles(stands, bundles, _resolved(args.out), graph=graph, seed=args.seed, workers=workers, commit=_commit(),
                       info_of=make_info_of(_resolved(args.source_run)))
    print(render_table(rows))
    print(f"total {human_duration(time.perf_counter() - started)}")
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
