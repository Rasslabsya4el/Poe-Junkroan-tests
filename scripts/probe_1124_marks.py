"""#1124 unit 5a: the counter probe for rows 2, 3 and 5 of the red-line marks issue.

For each stand build (a delivered `.pob.txt`) three PoB sessions, each in its own process:

1. DISCOVERY / NO MARKS: the moves (default `refine`, `gear`) run with a marks file that does not exist, so the
   search is today's. It records, outside the timed move, which red lines the search met: the lines of the nodes its
   tree trials touched, the `unsupported_lines` of every gear candidate the gate rejected, and the red lines the
   stand holds (items by rarity, allocated nodes). A line is red when PoB's own `parse_mods` says `unsupported`
   (the machinery `audit_unsupported_mods` uses); nothing is taken from memory.
2. MARKS: the probe writes its own marks file (under `artifacts/probe-1124/<stand>/`, never the repo's real file) with
   the probe value `10% increased Damage` on both lanes for the chosen lines, and runs the same moves again, same
   seed. Counters: `mark:<line>` (a node trial or a held line, `trace.py`) and, from this probe's own item classes,
   `probe-affix:` / `probe-unique:` / `probe-norecord:` per item trial (generated at the candidate, evaluated at the
   PoB trial).
3. ZERO: a marks file with only ZERO records (both lanes empty) for the held red lines; no move, only the start
   numbers.

Rows: 2 = counters (node, affix, unique > 0 / > 0; an item whose red line has no record: evaluated 0), 3 = CombinedDPS
and TotalEHP at the start with the zero records equal to those with no file, to the digit, 5 = wall time of the moves
with / without the marks (limit: 20 % slower). Row 4 (the empty-file transcript) is `compare_calls.py`, not here.

    python scripts/probe_1124_marks.py --stands "artifacts/stands-1124/spark-s4.pob.txt" --out artifacts/probe-1124
    python scripts/probe_1124_marks.py --read artifacts/probe-1124      # print rows 2, 3, 5 of a finished probe
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from junkroan.optimizer.red_line_marks import ENV_PATH  # noqa: E402
from junkroan.optimizer.trace import TRACE, register_class  # noqa: E402
import junkroan.optimizer.trace as _trace  # noqa: E402
from junkroan.report_format import human_duration  # noqa: E402

PROBE_MARK_LINE = "10% increased Damage"  # a line PoB parses fully: the point is the counters, not game truth
NO_MARKS_FILE = "no-marks.json"  # a path that never exists: `load_marks` then returns the empty store
SLOWDOWN_LIMIT_PERCENT = 20.0
DEFAULT_MOVES = ("refine", "gear")
START_KEYS = ("CombinedDPS", "TotalEHP")
LIMITS = {"node": 6, "held_node": 2, "affix": 4, "held_affix": 3, "unique": 3, "control": 3, "zero": 6}
_BRACES = re.compile(r"^(?:\{[^}]*\})+")


# -- pure parts ----------------------------------------------------------------------------------------------------


def make_records(marked: Iterable[str], zero: Iterable[str] = ()) -> list[dict[str, Any]]:
    """Marks-store records (the schema of `red_line_marks.py`): the probe value on both lanes for each marked line,
    a zero record (both lanes empty, with its reason) for each zero line. A line is written once; marked wins over zero."""

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in marked:
        if line not in seen:
            seen.add(line)
            records.append(_record(line, [PROBE_MARK_LINE], "", "probe mark"))
    for line in zero:
        if line not in seen:
            seen.add(line)
            records.append(_record(line, [], "probe zero record: a known line that carries no mark", "probe zero"))
    return records


def _record(line: str, lane: list[str], zero_reason: str, why: str) -> dict[str, Any]:
    return {"line": line, "surfaces": ["probe"], "sources": ["probe_1124_marks"], "group": "probe", "kind": "custom_mod" if lane else "none",
            "boss_lane": list(lane), "optimistic_lane": list(lane), "zero_reason": zero_reason, "why": why, "partial_part": "all of the line"}


def write_marks_file(path: Path, records: Sequence[Mapping[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(list(records), indent=1, ensure_ascii=False), encoding="utf-8")
    return path


def red_lines(parse_rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """The lines PoB's `parse_mods` shows red (`ok` false or `unsupported`), first seen order, once each."""

    out: list[str] = []
    for row in parse_rows:
        line = str(row.get("line") or "")
        if line and (not row.get("ok") or row.get("unsupported")) and line not in out:
            out.append(line)
    return out


def stat_parts(lines: Iterable[str]) -> list[str]:
    """A node's stat lines cut at their newlines, as `judging.write_marks` looks a held line up by its parts."""

    return [part.strip() for line in lines for part in str(line).split("\n") if part.strip()]


def counter(considered: Mapping[str, Mapping[str, Mapping[str, int]]], cls: str) -> tuple[int, int]:
    """(generated, evaluated) of one trace class summed over every move of `TRACE.considered()`."""

    generated = evaluated = 0
    for classes in considered.values():
        entry = classes.get(cls)
        if entry:
            generated += int(entry.get("generated", 0))
            evaluated += int(entry.get("evaluated", 0))
    return generated, evaluated


@dataclass(frozen=True)
class ItemLines:
    """The item lines the probe's own trace classes look for: marked rare affix lines, marked unique lines, and the
    control (red lines with NO record)."""

    affix: set[str] = field(default_factory=set)
    unique: set[str] = field(default_factory=set)
    control: set[str] = field(default_factory=set)


def item_classes(raw: str, sets: ItemLines) -> set[str]:
    """`probe-affix:` / `probe-unique:` / `probe-norecord:` classes of one item raw: its lines with the leading
    `{...}` tags (range, crafted, variant) taken off. A unique counts only against the unique set, a rare against the
    affix set; the control counts on any item."""

    lines = [_BRACES.sub("", ln.strip()).strip() for ln in str(raw).splitlines() if ln.strip()]
    unique = bool(lines) and lines[0].lower().startswith("rarity:") and lines[0].split(":", 1)[1].strip().lower() == "unique"
    out: set[str] = set()
    for line in lines:
        if unique and line in sets.unique:
            out.add(f"probe-unique:{line}")
        elif not unique and line in sets.affix:
            out.add(f"probe-affix:{line}")
        if line in sets.control:
            out.add(f"probe-norecord:{line}")
    return out


def register_item_classes(sets: ItemLines) -> Callable[[dict], Iterable[str]]:
    """Put the probe's item classes into the trace; returns the function for `unregister_item_classes`."""

    def classes(trial: dict) -> Iterable[str]:
        item = trial.get("item") if isinstance(trial, dict) else None
        raw = item.get("raw") if isinstance(item, dict) else None
        return item_classes(raw, sets) if isinstance(raw, str) else ()

    register_class(classes)
    return classes


def unregister_item_classes(fn: Callable[[dict], Iterable[str]]) -> None:
    if fn in _trace._REGISTRY:
        _trace._REGISTRY.remove(fn)


class RejectedLines:
    """The `unsupported_lines` of the gear candidates the gate looked at, counted."""

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()

    def add(self, lines: Iterable[str]) -> None:
        self._counts.update(str(line) for line in lines)

    def count(self, line: str) -> int:
        return self._counts[line]

    def lines(self) -> list[str]:
        # Counter keeps first-seen order for ties (dict order), `sorted` is stable
        return sorted(self._counts, key=lambda line: -self._counts[line])


@dataclass(frozen=True)
class Selection:
    """The red lines the probe marks (node, affix, unique) and the control left without a record."""

    node: list[str]
    affix: list[str]
    unique: list[str]
    control: list[str]

    def marked(self) -> list[str]:
        return list(dict.fromkeys([*self.node, *self.affix, *self.unique]))

    def item_lines(self) -> ItemLines:
        return ItemLines(affix=set(self.affix), unique=set(self.unique), control=set(self.control))


def plan_selection(found: Mapping[str, Any], limits: Mapping[str, int] = LIMITS) -> tuple[Selection, list[str]]:
    """What to mark, from what the no-marks run met (`found`: `held_affix`, `held_unique`, `held_node` = lists of red
    lines the stand holds; `touched_node` = {red line: trials that touched it}; `rejected` = {red line: times the
    gate saw it}). Returns the selection and the zero lines (held red lines, for the zero-record run).

    Nodes: the most touched candidate lines, then a few held ones. Affix: the most often rejected candidate lines (the
    ones the gate drops today) plus a few held ones; the control is the NEXT most rejected, left without a record."""

    touched = found.get("touched_node") or {}
    node = sorted(touched, key=lambda line: -touched[line])[: limits["node"]]
    node += [line for line in (found.get("held_node") or []) if line not in node][: limits["held_node"]]
    rejected = found.get("rejected") or {}
    ranked = sorted(rejected, key=lambda line: -rejected[line])
    affix = ranked[: limits["affix"]]
    control = ranked[limits["affix"]: limits["affix"] + limits["control"]]
    # no gate rejection left over (measured: no rare candidate carries a red line): the control is a touched node line left
    # without a record, read through the `mark:` class like the marked nodes
    control += [line for line in sorted(touched, key=lambda line: -touched[line]) if line not in node][: limits["control"] - len(control)]
    affix += [line for line in (found.get("held_affix") or []) if line not in affix][: limits["held_affix"]]
    unique = list(found.get("held_unique") or [])[: limits["unique"]]
    held = [*(found.get("held_affix") or []), *(found.get("held_unique") or []), *(found.get("held_node") or [])]
    return Selection(node=node, affix=affix, unique=unique, control=control), list(dict.fromkeys(held))[: limits["zero"]]


def _best(considered: Mapping, lines: Sequence[str], *prefixes: str) -> dict[str, Any]:
    """The line with the most evaluations over its classes (one per prefix, summed)."""

    best: dict[str, Any] | None = None
    for line in lines:
        counts = [counter(considered, prefix + " ".join(line.split())) for prefix in prefixes]
        g, e = sum(c[0] for c in counts), sum(c[1] for c in counts)
        row = {"line": line, "generated": g, "evaluated": e}
        if best is None or (e, g) > (best["evaluated"], best["generated"]):
            best = row
    return best or {"line": None, "generated": 0, "evaluated": 0}


def row2(considered: Mapping, selection: Selection) -> dict[str, dict[str, Any]]:
    """Row 2: node, affix and unique each `generated > 0 and evaluated > 0` on their best line; the control
    (a red line with no record) `evaluated == 0`. No line to look at is a failure, never a silent pass."""

    out: dict[str, dict[str, Any]] = {}
    # a held red affix (a magic Flask line on the stands) is counted by the lane writers as `mark:`; a gear candidate
    # with a red line would be `probe-affix:` (none was ever generated on the stands: row `affix_gate`, information only)
    for kind, lines, prefixes in (("node", selection.node, ("mark:",)), ("affix", selection.affix, ("mark:", "probe-affix:")), ("unique", selection.unique, ("mark:",))):
        row = _best(considered, lines, *prefixes)
        row["ok"] = bool(row["generated"] > 0 and row["evaluated"] > 0)
        out[kind] = row
    gate = _best(considered, selection.affix, "probe-affix:")
    gate["ok"] = None
    out["affix_gate"] = gate
    control = _best(considered, selection.control, "probe-norecord:", "mark:")
    control["ok"] = bool(selection.control) and control["evaluated"] == 0
    out["control"] = control
    return out


def row2_ok(verdict: Mapping[str, Mapping[str, Any]]) -> bool:
    return all(row["ok"] for row in verdict.values() if row["ok"] is not None)


def row3(without: Mapping[str, Any], zero: Mapping[str, Any]) -> dict[str, Any]:
    """Row 3: the start numbers with a zero record against none, equal to the digit (exact float equality)."""

    keys = list(dict.fromkeys([*without, *zero]))
    diff = [key for key in keys if key not in without or key not in zero or without[key] != zero[key]]
    return {"equal": not diff, "diff": diff, "without": dict(without), "zero": dict(zero)}


def row5(without_seconds: float, marks_seconds: float) -> dict[str, Any]:
    """Row 5: the marks run's wall time against the run without marks; slower than 20 % parks the issue."""

    if not without_seconds or without_seconds <= 0:
        return {"percent": None, "ok": False, "without_seconds": without_seconds, "marks_seconds": marks_seconds}
    percent = (marks_seconds / without_seconds - 1.0) * 100.0
    return {"percent": percent, "ok": percent < SLOWDOWN_LIMIT_PERCENT, "without_seconds": without_seconds, "marks_seconds": marks_seconds}


def report_lines(stand: str, *, row2: Mapping[str, Mapping[str, Any]] | None, row3: Mapping[str, Any], row5: Mapping[str, Any]) -> list[str]:
    out = [f"### {stand}"]
    if row2 is not None:
        out.append("row 2 (trace counters at the PoB boundary):")
        for kind, row in row2.items():
            verdict_word = "INFO" if row["ok"] is None else ("OK" if row["ok"] else "FAIL")
            out.append(f"  {kind}: generated {row['generated']}, evaluated {row['evaluated']}, {verdict_word}  [{row['line']}]")
    out.append(f"row 3 (zero record vs none): {'equal to the digit' if row3['equal'] else 'DIFFERENT ' + ', '.join(row3['diff'])}; "
               + ", ".join(f"{k}={row3['without'].get(k)!r}/{row3['zero'].get(k)!r}" for k in START_KEYS if k in row3["without"] or k in row3["zero"]))
    percent = row5["percent"]
    out.append(f"row 5 (cost): without marks {human_duration(row5['without_seconds'])}, with marks {human_duration(row5['marks_seconds'])}, "
               + (f"{percent:+.1f}% ({'under' if row5['ok'] else 'OVER'} the {SLOWDOWN_LIMIT_PERCENT:.0f}% limit)" if percent is not None else "no baseline time"))
    return out


# -- PoB parts: one stand run in its own process -------------------------------------------------------------------


def _parse_red(pob: Any, lines: Sequence[str]) -> list[str]:
    unique = list(dict.fromkeys(line for line in lines if line))
    return red_lines(pob.parse_mods(unique)) if unique else []


def _held_red_lines(pob: Any) -> dict[str, list[str]]:
    """The red lines the loaded build holds: rare / unique item affixes (by the slot's rarity) and allocated nodes."""

    from junkroan.optimizer.audit import held_mod_entries

    state = pob.read_state()
    slots = (state.get("items_state") or {}).get("slots") or {}
    rarity = {str(slot): str(((entry or {}).get("item") or {}).get("rarity") or "").lower() for slot, entry in slots.items()}
    items = [(line, src) for line, src in held_mod_entries({"items_state": state.get("items_state")})]
    nodes = [(line, src) for line, src in held_mod_entries({"tree_state": state.get("tree_state")})]
    item_lines = stat_parts(line for line, _ in items)
    node_lines = stat_parts(line for line, _ in nodes)
    red = set(_parse_red(pob, [*item_lines, *node_lines]))
    out: dict[str, list[str]] = {"held_affix": [], "held_unique": [], "held_node": []}
    for line, slot in items:
        key = "held_unique" if rarity.get(slot) == "unique" else "held_affix"
        if line in red and line not in out[key]:
            out[key].append(line)
    out["held_node"] = [line for line in node_lines if line in red]
    out["held_node"] = list(dict.fromkeys(out["held_node"]))
    return out


def stand_run(job: Mapping[str, Any]) -> dict[str, Any]:
    """One stand, one config, one process: the start numbers, then each move timed; `job`: stand, marks (a path, None =
    no marks), moves, seed, record (collect what the search met), item_lines (the probe's item classes)."""

    os.environ[ENV_PATH] = str(job["marks"]) if job.get("marks") else str(Path(job["out"]) / NO_MARKS_FILE)
    import replay_bench as rb  # noqa: E402  (imports the whole optimizer; only the stand process needs it)
    from junkroan.optimizer import gear_filler, improvement_loop, wishlist_gear
    from junkroan.optimizer.improvement_loop import LoopPlan, WorkingBuild
    from junkroan.optimizer.pipeline import BuildResult
    from junkroan.optimizer.tree_optimizer import TreeOptimizer
    from junkroan.pob.session import PobSession

    path = Path(job["stand"])
    info = rb.source_info(path)
    logs: list[str] = []
    rejected = RejectedLines()
    touched: Counter[int] = Counter()
    originals: list[tuple[Any, str, Any]] = []
    if job.get("record"):
        for module in (gear_filler, improvement_loop, wishlist_gear):
            original = module.red_lines_blocking

            def watching(lines, *args, _original=original, **kwargs):
                lines = list(lines)
                rejected.add(lines)
                return _original(lines, *args, **kwargs)

            originals.append((module, "red_lines_blocking", original))
            module.red_lines_blocking = watching
        measure = TreeOptimizer._measure

        def measuring(self, trials, keys, stats, _measure=measure):
            for trial in trials:
                touched.update(int(n) for key in ("add", "path", "remove") for n in (trial.get(key) or ()))
            return _measure(self, trials, keys, stats)

        originals.append((TreeOptimizer, "_measure", measure))
        TreeOptimizer._measure = measuring
    registered = register_item_classes(ItemLines(**{k: set(v) for k, v in (job.get("item_lines") or {}).items()})) if job.get("item_lines") else None
    started = time.perf_counter()
    try:
        with PobSession(run_id=f"probe1124-{info['slug']}-{os.getpid()}") as pob:
            prepared = rb._prepared_author(pob, info["slug"], info["stat"], logs.append)
            TRACE.reset()  # the counters are this stand's own, not the author rebuild's
            pob.load_import_code(path.read_text(encoding="utf-8").strip())
            pipeline, skeleton, gear, tree = rb._pipeline_state(pob, prepared, gear_mode=info["gear_mode"], log=logs.append)
            start = {key: pob.stats((key,)).get(key) for key in START_KEYS}
            held = _held_red_lines(pob) if job.get("record") else {}
            result = BuildResult(skeleton=skeleton, objective_stat=pipeline.objective.maximize, gear_mode=info["gear_mode"])
            seconds: dict[str, float] = {}
            for move in job.get("moves") or ():
                t0 = time.perf_counter()
                pipeline.improve(WorkingBuild(pob=pob, judging=pipeline.judging, skeleton=skeleton, gear=gear, tree=tree), result,
                                 LoopPlan.replay(move, seed=int(job["seed"]), passes=1))
                seconds[move] = time.perf_counter() - t0
            found: dict[str, Any] = {}
            if job.get("record"):  # after the timed moves: PoB parses the lines the search met
                lines_of: dict[str, int] = {}
                for nid, n in touched.items():
                    node = tree.graph.node(nid)
                    if node is not None and node.kind in TreeOptimizer.MARK_NODE_KINDS:
                        for part in stat_parts(node.stats or ()):
                            lines_of[part] = lines_of.get(part, 0) + n
                red_nodes = set(_parse_red(pob, list(lines_of)))
                red_rejected = set(_parse_red(pob, rejected.lines()))
                found = {**held, "touched_node": {line: n for line, n in lines_of.items() if line in red_nodes},
                         "rejected": {line: rejected.count(line) for line in rejected.lines() if line in red_rejected},
                         "rejected_all": len(rejected.lines())}
            return {"ok": True, "stand": path.name, "marks": job.get("marks"), "start": start, "seconds": seconds,
                    "considered": TRACE.considered(), "found": found, "logs": logs[-20:], "total_seconds": time.perf_counter() - started}
    except Exception as exc:  # noqa: BLE001 - a failed run is a report row
        import traceback

        return {"ok": False, "stand": path.name, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc(), "logs": logs[-20:]}
    finally:
        for owner, name, original in originals:
            setattr(owner, name, original)
        if registered is not None:
            unregister_item_classes(registered)


def _in_process(job: Mapping[str, Any]) -> dict[str, Any]:
    with ProcessPoolExecutor(max_workers=1) as pool:
        return pool.submit(stand_run, dict(job)).result()


def probe_stand(stand: Path, out: Path, *, moves: Sequence[str], seed: int, skip_zero: bool = False) -> dict[str, Any]:
    name = stand.name[: -len(".pob.txt")] if stand.name.endswith(".pob.txt") else stand.stem
    folder = out / name
    folder.mkdir(parents=True, exist_ok=True)
    base = {"stand": str(stand), "out": str(folder), "moves": list(moves), "seed": seed}
    none = _in_process({**base, "marks": None, "record": True})
    _dump(folder / "none.json", none)
    if not none.get("ok"):
        return {"stand": name, "error": none.get("error")}
    selection, zero = plan_selection(none["found"])
    write_marks_file(folder / "marks.json", make_records(selection.marked()))
    write_marks_file(folder / "zero.json", make_records([], zero))
    _dump(folder / "selection.json", {"node": selection.node, "affix": selection.affix, "unique": selection.unique, "control": selection.control, "zero": zero})
    item_lines = {"affix": sorted(selection.affix), "unique": sorted(selection.unique), "control": sorted(selection.control)}
    marks = _in_process({**base, "marks": str(folder / "marks.json"), "record": False, "item_lines": item_lines})
    _dump(folder / "marks-run.json", marks)
    zero_run = None if skip_zero else _in_process({**base, "marks": str(folder / "zero.json"), "record": False, "moves": []})
    if zero_run is not None:
        _dump(folder / "zero-run.json", zero_run)
    return {"stand": name, "folder": str(folder)}


def _dump(path: Path, data: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str), encoding="utf-8")


def read_folder(folder: Path) -> list[str]:
    """Rows 2, 3 and 5 of one stand's finished runs, as printed lines."""

    try:
        none = json.loads((folder / "none.json").read_text(encoding="utf-8"))
        marks = json.loads((folder / "marks-run.json").read_text(encoding="utf-8"))
        sel = json.loads((folder / "selection.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"### {folder.name}", f"not finished: {exc}"]
    if not (none.get("ok") and marks.get("ok")):
        return [f"### {folder.name}", f"run failed: {none.get('error') or marks.get('error')}"]
    selection = Selection(node=sel["node"], affix=sel["affix"], unique=sel["unique"], control=sel["control"])
    zero_path = folder / "zero-run.json"
    zero = json.loads(zero_path.read_text(encoding="utf-8")) if zero_path.exists() else {}
    r3 = row3(none["start"], zero.get("start") or {})
    r5 = row5(sum(none["seconds"].values()), sum(marks["seconds"].values()))
    return report_lines(folder.name, row2=row2(marks["considered"], selection), row3=r3, row5=r5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stands", help="glob of stand .pob.txt builds")
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "probe-1124"))
    parser.add_argument("--moves", default=",".join(DEFAULT_MOVES))
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--skip-zero", action="store_true", help="leave the zero-record run out (row 3)")
    parser.add_argument("--read", metavar="DIR", help="print rows 2, 3 and 5 of a finished probe folder and exit")
    args = parser.parse_args()
    if args.read:
        for folder in sorted(p for p in Path(args.read).iterdir() if p.is_dir()):
            print("\n".join(read_folder(folder)))
        return 0
    if not args.stands:
        parser.error("--stands or --read is required")
    moves = [m for m in args.moves.split(",") if m]
    out = Path(args.out)
    for stand in sorted(Path(p) for p in glob.glob(args.stands)):
        started = time.perf_counter()
        probe_stand(stand, out, moves=moves, seed=args.seed, skip_zero=args.skip_zero)
        name = stand.name[: -len(".pob.txt")]
        print("\n".join(read_folder(out / name)), flush=True)
        print(f"({name} took {human_duration(time.perf_counter() - started)})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
