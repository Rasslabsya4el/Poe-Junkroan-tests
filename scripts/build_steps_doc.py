"""Generate docs/BUILD_STEPS.md from the pipeline's own step list and descriptions (#713).

    python scripts/build_steps_doc.py [--run <benchmark dir>] [--out docs/BUILD_STEPS.md] [--check]

The steps, their groups and order are `stage_catalog.STEPS` / `GROUPS` / `LOOP_MOVES`; the texts are
`stage_catalog.descriptions()`; median time and share come from `rows/*.json` of one benchmark run through
`stage_shares.shares`. A step or move without a description is written as "NO DESCRIPTION YET".

Default run = the latest weekly run: the newest folder of artifacts/benchmark whose name matches the gate rule of
`junkroan.runs.gates.newest_gate` (`GATE_DIR_RE`, a `...-gate-<date>` folder, newest by name). If none exists, the
times are written as "not run in this set". A conditional step (`stage_catalog.CONDITIONS`) with no time prints
"Runs only when: <condition>" instead; `--check` also fails on a step with neither a time nor a condition line (#720).

Per-move times: each row's `move_rows` lists (`move`, `seconds`); a row's move name is mapped to a LOOP_MOVES name
("gear Boots" -> "gear", "path swaps" -> "swaps", hyphen = space), a build's seconds are summed per move, and the
median is over the builds that ran it. No output carries a clock time, so regenerating gives no diff.
`--check` exits 1 when the file on disk differs from a fresh generation.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from junkroan.optimizer import stage_catalog  # noqa: E402
from junkroan.optimizer.step_description import MOVE_PREFIX  # noqa: E402
from junkroan.report_format import human_duration  # noqa: E402

_spec = importlib.util.spec_from_file_location("stage_shares", ROOT / "scripts" / "stage_shares.py")
stage_shares = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stage_shares)

NO_DESCRIPTION = "NO DESCRIPTION YET"
NOT_RUN = "not run in this set"
FIELDS = (("What it changes", "what_it_changes"), ("What it tries", "what_it_tries"),
          ("How it is judged", "how_judged"), ("What it keeps", "what_it_keeps"),
          ("When it is skipped", "when_skipped"))

INTRO = (
    "A build starts as a skeleton: a class, an ascendancy, a main skill, supports and a few chosen items. The "
    "construction steps give it a first config, gear and passive tree, one after the other, each judged by the "
    "numbers Path of Building (PoB) computes for the build after the change.\n\n"
    "Then the improvement loop tries moves (tree, gear, supports picks, kicks) again and again until no move "
    "improves the build any more (a fixed point), and the finish steps re-pick the anoint, derive the final config "
    "lanes and export the build. Every change is kept only when PoB's numbers say it is better."
)


def latest_weekly_run(artifacts: Path = ROOT / "artifacts") -> Path | None:
    from junkroan.runs.gates import newest_gate

    name = newest_gate(artifacts)
    return artifacts / "benchmark" / name if name else None

OPENING = "loop opening"


def move_name(row_move: str) -> str:
    text = row_move.replace("-", " ")
    if text.startswith("gear "):
        return "gear"
    if text == "path swaps":
        return "swaps"
    known = {m.replace("-", " "): m for m in stage_catalog.LOOP_MOVES}
    return known.get(text, row_move)


def load_run(folder: Path | None) -> dict:
    rows_dir = folder / "rows" if folder else None
    files = sorted(rows_dir.glob("*.json")) if rows_dir and rows_dir.is_dir() else []
    datas = [json.loads(p.read_text(encoding="utf-8")) for p in files]
    stages = [d["stages"] for d in datas if d.get("stages")]
    per_move: dict[str, list[float]] = {}
    opening: list[float] = []  # #720: the loop opening writes move rows (where "loop opening"), no stage of its own
    for d in datas:
        build: dict[str, float] = {}
        rows = d.get("move_rows") or []
        spent = [float(m.get("seconds") or 0) for m in rows if m.get("where") == OPENING]
        if spent:
            opening.append(sum(spent))
        for m in rows:
            name = move_name(str(m.get("move", "")))
            build[name] = build.get(name, 0.0) + float(m.get("seconds") or 0)
        for k, v in build.items():
            per_move.setdefault(k, []).append(v)
    example = next(((p.stem, d["stages"]) for p, d in zip(files, datas) if d.get("stages")), None)
    return {"name": folder.name if folder else None, "shares": stage_shares.shares(stages),
            "moves": {k: statistics.median(v) for k, v in per_move.items()},
            "opening": statistics.median(opening) if opening else None, "example": example}


def _desc_lines(desc) -> list[str]:
    if desc is None:
        return [NO_DESCRIPTION, ""]
    lines = []
    for label, attr in FIELDS:
        lines += [f"**{label}.** {getattr(desc, attr).strip()}", ""]
    lines += [f"Where: `{desc.where.strip()}`", ""]
    return lines


def _no_time(key: str, builds: int, per_build: bool = False) -> list[str]:
    """#720: a conditional step prints its condition and why it has no time; any other step "not run in this set"."""

    cond = stage_catalog.condition_of(key)
    if cond is None:
        return [f"Median time{' per build' if per_build else ''}: {NOT_RUN}.", ""]
    return [f"Runs only when: {cond}.", f"Median time: none: no build of this set ({builds} builds) met the condition.", ""]


def untimed_steps(run: dict) -> list[str]:
    """Steps with neither a median time nor a condition line (`--check` fails on any)."""

    steps = run["shares"]["steps"]
    return [s.name for s in stage_catalog.STEPS
            if s.name not in steps and not (s.name == OPENING and run.get("opening") is not None)
            and stage_catalog.condition_of(s.name) is None]


def generate(run: dict) -> str:
    descs = stage_catalog.descriptions()
    shares = run["shares"]
    out = ["# How a build is made", "", INTRO, ""]
    out += [f"Times are medians over the builds of the run `{run['name']}` ({shares['builds']} builds)."
            if run["name"] else "No benchmark run was read; no times.", ""]
    for group in stage_catalog.GROUPS:
        out += [f"## {group.capitalize()}", ""]
        for step in (s for s in stage_catalog.STEPS if s.group == group):
            out += [f"### {step.label}", "", f"Step name: `{step.name}`", ""]
            out += _desc_lines(descs.get(step.name))
            data = shares["steps"].get(step.name)
            if not data and step.name == OPENING and run.get("opening") is not None:
                out += [f"Median time: {human_duration(run['opening'])} (the sum of the opening's move rows, per build).", ""]
            elif data:
                out += [f"Median time: {human_duration(data['median_seconds'])}; share of the build time: "
                        f"{data['median_share'] * 100:.1f} % (ran in {data['builds']} builds).", ""]
            else:
                out += _no_time(step.name, shares["builds"])
        if group == stage_catalog.IMPROVEMENT_LOOP:
            out += ["### Loop moves", "", "The moves of one pass of the improvement loop, in the order they are tried.", ""]
            for move in stage_catalog.LOOP_MOVES:
                out += [f"#### {move}", ""]
                out += _desc_lines(descs.get(MOVE_PREFIX + move))
                sec = run["moves"].get(move)
                if sec is not None:
                    out += [f"Median time per build: {human_duration(sec)}.", ""]
                else:
                    out += _no_time(MOVE_PREFIX + move, shares["builds"], per_build=True)
    out += ["## Worked example", ""]
    if run["example"]:
        build, stages = run["example"]
        out += [f"The stages of one recorded build (`{build}`), in the order they ran.", ""]
        for s in stages:
            note = str(s.get("notes") or "").strip()
            out += [f"- {s.get('name', '')}: {human_duration(float(s.get('seconds') or 0))}"
                    + (f" ({note})" if note else "")]
        out += [""]
    else:
        out += ["No recorded build in this set.", ""]
    return "\n".join(out).rstrip("\n") + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=None)
    ap.add_argument("--out", default=str(ROOT / "docs" / "BUILD_STEPS.md"))
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    folder = Path(a.run) if a.run else latest_weekly_run()
    run = load_run(folder)
    text = generate(run)
    out = Path(a.out)
    if a.check:
        bad = untimed_steps(run)
        if bad:
            print(f"steps with neither a median time nor a condition line: {', '.join(bad)}")
            return 1
        old = out.read_text(encoding="utf-8") if out.exists() else ""
        if old == text:
            return 0
        old_l, new_l = old.splitlines(), text.splitlines()
        for i in range(max(len(old_l), len(new_l))):
            o = old_l[i] if i < len(old_l) else "<end>"
            n = new_l[i] if i < len(new_l) else "<end>"
            if o != n:
                print(f"{out}: line {i + 1} differs: disk {o!r} vs fresh {n!r}")
                break
        return 1
    out.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
