"""Calibrate the keystone repair against the recorded full rebuilds' verdicts (#1064, unit 3).

A pair is a finished parent build and one keystone variant of it. The repair runs from the parent
(`BuildPipeline.repair`, the stop rule of `junkroan.optimizer.repair`, two loop passes at most) and its verdict
("take", "drop" or "climbing") is compared with the recorded full variant: take when the variant's `ours` is at
least the parent's, drop otherwise. Direction `force`: the forced row (`-with-<x>`) against its plain parent.
Direction `forbid`: the `-no-<x>` variant against its parent. A pair whose recorded ratio lies within 0.95-1.05
is shown but not counted.

Pairs come from a benchmark run folder (`--pairs artifacts/benchmark/<run>`; only that folder's own files are
read) or from a list of `parent_row:variant_row:keystone` triples separated by `;` (rows are the
`rows/<stem>.json` files; the builds are their sibling `<stem>.pob.txt` one folder up).

    python scripts/repair_calibrate.py --pairs artifacts/benchmark/20261005-1220-gate-20261005 --direction forbid --workers 2 --tag gate
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from replay_bench import _pipeline_state, _prepared_author, begin_recording, source_info  # noqa: E402
from junkroan.optimizer.improvement_loop import WorkingBuild  # noqa: E402
from junkroan.optimizer.pipeline import BuildResult  # noqa: E402
from junkroan.optimizer.repair import REPAIR_GAIN_FLOOR, REPAIR_MAX_PASSES, RepairChoice, repair_verdict  # noqa: E402
from junkroan.pob.session import PobSession  # noqa: E402
from junkroan.report_format import human_duration  # noqa: E402
from junkroan.runs.yield_plan import limited_completions  # noqa: E402

DIRECTIONS = ("force", "forbid")
KIND_OF = {"forbid": "no", "force": "with"}  # the stem word of a variant's row in each direction (benchmark.py result_stem)
RECORDED_BAND = (0.95, 1.05)  # a recorded ratio inside this band is shown but not counted
COMPUTE_BAR = 1.0 / 3.0  # #1064 row 5: repair time at most a third of the recorded full time
_STEM = re.compile(r"^(?P<slug>.+)-s(?P<seed>\d+)(?:-(?P<kind>no|with)-(?P<key>.+))?$")
# parent_row:variant_row:keystone, where a row path may start with a drive letter (C:/...)
_TRIPLE = re.compile(r"^(?P<parent>[A-Za-z]:[\\/][^:]*|[^:]+):(?P<variant>[A-Za-z]:[\\/][^:]*|[^:]+):(?P<keystone>.+)$")


@dataclass(frozen=True)
class Pair:
    """One calibration pair: the parent's row, the variant's row, the keystone and the direction."""

    parent_row: Path
    variant_row: Path
    keystone: str
    direction: str

    @property
    def name(self) -> str:
        return self.variant_row.stem

    @property
    def parent_pob(self) -> Path:
        """The parent's import code: `<run>/<stem>.pob.txt`, the row's folder is `<run>/rows`."""

        return self.parent_row.parent.parent / f"{self.parent_row.stem}.pob.txt"


def parse_stem(stem: str) -> tuple[str, str, str | None, str | None] | None:
    """(slug, seed, kind, key) of a benchmark build stem; kind is "no", "with" or None for a plain parent."""

    match = _STEM.match(stem)
    if match is None:
        return None
    return match["slug"], match["seed"], match["kind"], match["key"]


def _row(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def _num(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _keystone_name(variant_row: Path, key: str) -> str:
    """The keystone's name: the row's own `variant` (`no <NAME>` / `with <NAME>`), else the stem's key with spaces."""

    row = _row(variant_row) or {}
    variant = str(row.get("variant") or "")
    for prefix in ("no ", "with "):
        if variant.startswith(prefix) and variant[len(prefix):].strip():
            return variant[len(prefix):].strip()
    return key.replace("_", " ")


def discover_pairs(run: Path, direction: str) -> list[Pair]:
    """The pairs of one benchmark run folder: each plain `<slug>-s<seed>` with its variants of this direction.

    Only the folder's own `*.pob.txt` files are listed (no recursive walk); a variant without its plain parent is ignored."""

    if direction not in DIRECTIONS:
        raise ValueError(f"unknown direction {direction!r}; legal: {', '.join(DIRECTIONS)}")
    rows = run / "rows"
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for build in sorted(run.glob("*.pob.txt")):
        stem = build.name[: -len(".pob.txt")]
        parsed = parse_stem(stem)
        if parsed is None:
            continue
        slug, seed, kind, key = parsed
        group = groups.setdefault((slug, seed), {"plain": None, "variants": []})
        if kind is None:
            group["plain"] = stem
        elif kind == KIND_OF[direction]:
            group["variants"].append((stem, key))
    pairs: list[Pair] = []
    for group in groups.values():
        if group["plain"] is None:
            continue
        for stem, key in sorted(group["variants"]):
            variant_row = rows / f"{stem}.json"
            pairs.append(Pair(parent_row=rows / f"{group['plain']}.json", variant_row=variant_row,
                              keystone=_keystone_name(variant_row, key), direction=direction))
    return sorted(pairs, key=lambda pair: pair.name)


def _path(text: str) -> Path:
    path = Path(text.strip())
    if not path.is_absolute() and not path.exists() and (ROOT / path).exists():
        path = ROOT / path
    return path


def parse_pairs_list(text: str, direction: str) -> list[Pair]:
    """`parent_row:variant_row:keystone` triples separated by `;` (a drive letter's colon is part of its path)."""

    if direction not in DIRECTIONS:
        raise ValueError(f"unknown direction {direction!r}; legal: {', '.join(DIRECTIONS)}")
    pairs: list[Pair] = []
    for chunk in text.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        match = _TRIPLE.match(chunk)
        if match is None:
            raise ValueError(f"not a parent_row:variant_row:keystone triple: {chunk!r}")
        pairs.append(Pair(parent_row=_path(match["parent"]), variant_row=_path(match["variant"]),
                          keystone=match["keystone"].strip(), direction=direction))
    if not pairs:
        raise ValueError("--pairs named no triple")
    return pairs


@dataclass(frozen=True)
class Recorded:
    """The recorded full verdict of one pair, read from the two rows."""

    parent_value: float | None
    variant_value: float | None
    variant_seconds: float
    ratio: float | None
    recorded_verdict: str | None  # "take" or "drop"; None without two usable values
    counted: bool


def recorded_of(parent_row: Mapping[str, Any], variant_row: Mapping[str, Any]) -> Recorded:
    parent = _num(parent_row.get("ours"))
    variant = _num(variant_row.get("ours"))
    seconds = _num(variant_row.get("seconds")) or 0.0
    if parent is None or variant is None or parent <= 0:
        return Recorded(parent, variant, seconds, None, None, False)
    ratio = variant / parent
    verdict = "take" if variant >= parent else "drop"
    counted = not (RECORDED_BAND[0] <= ratio <= RECORDED_BAND[1])
    return Recorded(parent, variant, seconds, ratio, verdict, counted)


def agreement(repair: str, recorded: str | None, counted: bool) -> str:
    """"yes", "climbing" (agrees), "no: missed take", "no: false take" or "not counted"."""

    if not counted or recorded is None:
        return "not counted"
    if repair == "climbing":
        return "climbing"
    if repair == recorded:
        return "yes"
    return "no: missed take" if repair == "drop" else "no: false take"


def repair_with(pipeline: Any, working: Any, result: Any, pair: Pair) -> dict[str, Any]:
    """Run `pipeline.repair` for one pair and return its outcome as plain values with the measured repair time."""

    started = time.perf_counter()
    outcome = pipeline.repair(working, result, RepairChoice(pair.keystone, pair.direction))
    seconds = time.perf_counter() - started
    values = [float(value) for value in outcome.values]
    verdict = outcome.verdict or repair_verdict(float(outcome.start), values)
    summary = getattr(result, "summary", None)
    return {"ok": True, "start": float(outcome.start), "values": values, "gains": [float(g) for g in outcome.gains],
            "verdict": verdict, "seconds": seconds, "trace": summary() if callable(summary) else "",
            "moves": [dict(move) for move in getattr(result, "moves", None) or ()]}


def trace_text(name: str, repair: Mapping[str, Any]) -> str:
    """The diagnosis print of one pair (#1064, `--trace`): the result's stage rows and loop moves, then the pipeline's log lines."""

    lines = [f"=== {name}", str(repair.get("trace") or "(no stage rows)")]
    start, values = repair.get("start"), repair.get("values") or []
    if start is not None:
        lines.append(f"--- start {float(start):,.0f}; value after each pass: " + ", ".join(f"{float(v):,.0f}" for v in values))
    lines.append("--- every loop entry (pass, where, move, value before -> after, kept)")
    for move in repair.get("moves") or ():
        lines.append(f"  pass {move.get('pass')} {move.get('where')} {move.get('move')}: {float(move.get('before') or 0):,.0f} -> "
                     f"{float(move.get('after') or 0):,.0f} kept={move.get('kept')} reverted_by_judge={move.get('reverted_by_judge', False)}")
    lines.append("--- pipeline log")
    lines += [str(line) for line in repair.get("log") or ()]
    return "\n".join(lines)


def _repair_in_pob(pair: Pair, record_calls: str | None = None) -> dict[str, Any]:
    """Load the parent's import code the way replay_bench does, then repair it. Opens a PobSession (never in tests).

    `record_calls` (#1147): a directory; every PoB call from loading the parent on, and of the repair, is recorded to
    `<dir>/<pair name>.calls.jsonl` (the author's preparation is made before the recording starts, as in replay_bench)."""

    info = source_info(pair.parent_pob)
    logs: list[str] = []
    with PobSession(run_id=f"repair-{info['slug']}-{os.getpid()}") as pob:
        prepared = _prepared_author(pob, info["slug"], info["stat"], logs.append)
        recorder = None
        if record_calls:
            recorder = begin_recording(pob, Path(record_calls) / f"{pair.name}.calls.jsonl")
            pob = recorder
        try:
            pob.load_import_code(pair.parent_pob.read_text(encoding="utf-8").strip())
            pipeline, skeleton, gear, tree = _pipeline_state(pob, prepared, gear_mode=info["gear_mode"], log=logs.append)
            working = WorkingBuild(pob=pob, judging=pipeline.judging, skeleton=skeleton, gear=gear, tree=tree)
            result = BuildResult(skeleton=skeleton, objective_stat=pipeline.objective.maximize, gear_mode=info["gear_mode"])
            outcome = repair_with(pipeline, working, result, pair)
        finally:
            if recorder is not None:
                recorder.close_recording()
        outcome["log"] = logs
        return outcome


def repair_one(pair: Pair, record_calls: str | None = None) -> dict[str, Any]:
    """One pair in one worker process; a failure becomes a row, never an exception."""

    started = time.perf_counter()
    try:
        return _repair_in_pob(pair, record_calls)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc(),
                "seconds": time.perf_counter() - started}


def missing_input(pair: Pair) -> str:
    for path, label in ((pair.parent_row, "parent row"), (pair.variant_row, "variant row"), (pair.parent_pob, "parent build")):
        if not path.is_file():
            return f"no {label}: {path}"
    return ""


def calibrate_row(pair: Pair, recorded: Recorded | None, repair: Mapping[str, Any]) -> dict[str, Any]:
    """One output row: the recorded verdict, the repair's values and verdict, and the agreement."""

    row: dict[str, Any] = {
        "pair": pair.name, "direction": pair.direction, "keystone": pair.keystone,
        "parent": pair.parent_row.stem,
        "parent_value": recorded.parent_value if recorded else None,
        "variant_value": recorded.variant_value if recorded else None,
        "ratio": recorded.ratio if recorded else None,
        "recorded_verdict": recorded.recorded_verdict if recorded else None,
        "counted": bool(recorded and recorded.counted),
        "recorded_seconds": recorded.variant_seconds if recorded else 0.0,
        "ok": bool(repair.get("ok")),
        "error": str(repair.get("error") or ""),
        "start": None, "values": [], "gains": [], "repair_verdict": "-", "agree": "failed",
        "repair_seconds": float(repair.get("seconds") or 0.0),
    }
    if not row["ok"] or recorded is None:
        if row["ok"]:
            row["agree"] = "not counted"
        return row
    row.update({"start": float(repair["start"]), "values": list(repair["values"]), "gains": list(repair["gains"]),
                "repair_verdict": str(repair["verdict"])})
    row["agree"] = agreement(row["repair_verdict"], recorded.recorded_verdict, recorded.counted)
    return row


def run_repairs(pairs: list[Pair], *, workers: int, repair: Callable[[Pair], dict[str, Any]] = repair_one) -> dict[Pair, dict[str, Any]]:
    """The repair of each pair: in this process for one worker, else a pool of `workers` processes (as replay_bench)."""

    if workers <= 1:
        return {pair: repair(pair) for pair in pairs}
    results: dict[Pair, dict[str, Any]] = {}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        def submit(pair: Pair) -> Any:
            return pool.submit(repair, pair)

        for future, pair in limited_completions(submit, pairs, workers):
            results[pair] = future.result()
            print(f"  {pair.name:44s} {results[pair].get('verdict', 'FAILED')} {human_duration(float(results[pair].get('seconds') or 0.0))}", flush=True)
    return results


def calibrate(pairs: Iterable[Pair], *, workers: int, repair: Callable[[Pair], dict[str, Any]] = repair_one,
              trace: bool = False) -> list[dict[str, Any]]:
    """Every pair's row: pairs without their rows or build are rows that say why; the rest are repaired and compared."""

    pairs = list(pairs)
    recorded: dict[Pair, Recorded | None] = {}
    missing: dict[Pair, str] = {}
    for pair in pairs:
        missing[pair] = missing_input(pair)
        if missing[pair]:
            recorded[pair] = None
            continue
        parent_row, variant_row = _row(pair.parent_row), _row(pair.variant_row)
        if parent_row is None or variant_row is None:
            missing[pair] = f"unreadable row JSON: {pair.parent_row if parent_row is None else pair.variant_row}"
            recorded[pair] = None
            continue
        recorded[pair] = recorded_of(parent_row, variant_row)
    runnable = [pair for pair in pairs if not missing[pair]]
    results = run_repairs(runnable, workers=workers, repair=repair)
    if trace:
        for pair in runnable:
            print(trace_text(pair.name, results[pair]), flush=True)
    return [calibrate_row(pair, recorded[pair], results.get(pair, {"ok": False, "error": missing[pair]}))
            for pair in pairs]


def summarize(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    repaired = [row for row in rows if row["ok"]]
    counted = [row for row in repaired if row["counted"]]
    climbing = [row for row in counted if row["agree"] == "climbing"]
    repair_side = sum(float(row["repair_seconds"]) for row in counted) + sum(float(row["recorded_seconds"]) for row in climbing)
    full_side = sum(float(row["recorded_seconds"]) for row in counted)
    return {
        "pairs": len(rows),
        "counted": len(counted),
        "missed_takes": sum(row["agree"] == "no: missed take" for row in counted),
        "false_takes": sum(row["agree"] == "no: false take" for row in counted),
        "climbing": len(climbing),
        "uncounted": [row for row in repaired if not row["counted"]],
        "failed": [row for row in rows if not row["ok"]],
        "repair_side": repair_side,
        "full_side": full_side,
        "ratio": repair_side / full_side if full_side > 0 else None,
    }


def _fmt_value(value: object) -> str:
    return f"{float(value):,.0f}" if isinstance(value, (int, float)) else "-"


def _fmt_gain(value: float) -> str:
    return f"{value * 100:+.2f}%"


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_report(rows: list[Mapping[str, Any]], *, stamp: str, direction: str, workers: int, seconds: float) -> str:
    summary = summarize(rows)
    lines = [
        "# Repair calibration (#1064)",
        "",
        f"{stamp}; direction `{direction}`; {summary['pairs']} pairs ({summary['counted']} counted, "
        f"{len(summary['uncounted'])} uncounted, {len(summary['failed'])} not repaired); {workers} workers; "
        f"wall {human_duration(seconds)}.",
        f"Repair rule (`junkroan.optimizer.repair`): gain floor {REPAIR_GAIN_FLOOR:.0%} per pass, at most {REPAIR_MAX_PASSES} passes; "
        "a recorded verdict is take when the variant `ours` is at least the parent's, drop otherwise.",
        "",
        "| pair | direction | start value | value after pass 1 / pass 2 | gains | repair verdict | recorded full verdict | agree | repair time | recorded full time |",
        "|---|---|---:|---:|---|---|---|---|---:|---:|",
    ]
    for row in rows:
        ratio = f" (ratio {row['ratio']:.3f})" if isinstance(row.get("ratio"), float) else ""
        recorded = f"{row['recorded_verdict']}{ratio}" if row["recorded_verdict"] else "-"
        if not row["ok"]:
            agree = f"not repaired: {_cell(row['error'])}"
            lines.append(f"| {_cell(row['pair'])} | {row['direction']} | - | - | - | - | {recorded} | {agree} | - | "
                         f"{human_duration(float(row['recorded_seconds'])) if row['recorded_seconds'] else '-'} |")
            continue
        values = row["values"]
        gains = row["gains"]
        value_cell = " / ".join(_fmt_value(v) for v in values) if values else "-"
        gain_cell = " / ".join(_fmt_gain(g) for g in gains) if gains else "-"
        lines.append(
            f"| {_cell(row['pair'])} | {row['direction']} | {_fmt_value(row['start'])} | {value_cell} | {gain_cell} | "
            f"{row['repair_verdict']} | {recorded} | {row['agree']} | {human_duration(float(row['repair_seconds']))} | "
            f"{human_duration(float(row['recorded_seconds']))} |"
        )
    lines += [
        "",
        "## Summary",
        "",
        f"Misses: missed takes {summary['missed_takes']} / false takes {summary['false_takes']}, over {summary['counted']} counted pairs.",
        f"Climbing: {summary['climbing']} pair(s), counted as agreeing; their recorded full time is added to the repair side.",
    ]
    uncounted = ", ".join(f"{row['pair']} (ratio {row['ratio']:.3f})" for row in summary["uncounted"]) or "none"
    lines.append(f"Uncounted (recorded ratio within {RECORDED_BAND[0]:.2f}-{RECORDED_BAND[1]:.2f}, shown but not counted): {uncounted}.")
    failed = "; ".join(f"{row['pair']}: {row['error']}" for row in summary["failed"]) or "none"
    lines.append(f"Not repaired: {failed}.")
    lines += ["", f"## Compute ({direction})", ""]
    if summary["ratio"] is None:
        lines.append("No counted pair with a recorded full time: no compute ratio.")
    else:
        met = "met" if summary["ratio"] <= COMPUTE_BAR else "not met"
        lines += [
            "| side | time |",
            "|---|---:|",
            f"| repair time (+ recorded full time of climbing pairs) | {human_duration(summary['repair_side'])} |",
            f"| recorded full time over the same {summary['counted']} counted pairs | {human_duration(summary['full_side'])} |",
            "",
            f"Ratio repair / recorded full: {summary['ratio']:.3f} (bar {COMPUTE_BAR:.3f}, #1064 row 5: {met}).",
        ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pairs", required=True,
                        help="a benchmark run folder, or parent_row:variant_row:keystone triples separated by ';'")
    parser.add_argument("--direction", required=True, choices=DIRECTIONS)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--tag", required=True, help="names the output folder when --pairs is a list")
    parser.add_argument("--trace", action="store_true", help="print each pair's stage rows, loop moves and pipeline log (a diagnosis run)")
    parser.add_argument("--record-calls", metavar="DIR",
                        help="#1147: record every PoB call of each pair's repair, from loading the parent build on, to DIR/<pair>.calls.jsonl "
                             "(compare with scripts/compare_calls.py)")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    source = Path(args.pairs)
    if not source.exists() and (ROOT / source).exists():
        source = ROOT / source
    stamp = time.strftime("%Y%m%d-%H%M") + f"-{args.tag}"
    if source.is_dir():
        pairs = discover_pairs(source, args.direction)
        out_dir = source
    else:
        pairs = parse_pairs_list(args.pairs, args.direction)
        out_dir = ROOT / "artifacts" / "benchmark" / args.tag
        out_dir.mkdir(parents=True, exist_ok=True)
    if not pairs:
        parser.error(f"no {args.direction} pairs found in {source}")
    started = time.perf_counter()
    record_calls = str(Path(args.record_calls).resolve()) if args.record_calls else None
    repair = partial(repair_one, record_calls=record_calls) if record_calls else repair_one
    rows = calibrate(pairs, workers=args.workers, trace=args.trace, repair=repair)
    elapsed = time.perf_counter() - started
    report = render_report(rows, stamp=stamp, direction=args.direction, workers=args.workers, seconds=elapsed)
    path = out_dir / "report-repair.md"
    path.write_text(report, encoding="utf-8")
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
