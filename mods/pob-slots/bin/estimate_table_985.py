"""#985 unit a: what the monitor's estimate would have said at 25 / 50 / 75 % of a FINISHED run, against the real end.

    python mods/pob-slots/bin/estimate_table_985.py            (from the repo root, PYTHONPATH=src)

Logs only, no PoB. The estimate is the add-on's own code (`estimate()` -> `_replay_est` / `_bench_est` / the history
fallback), called with the clock set to the moment and with only what existed then:
  - a replay run: its `.out` cut to the lines finished by then (a build's end is rebuilt from the pool, the way
    `replay_cells` rebuilds it: builds start in sorted order, the first `--workers` at the job's start, each later one
    when a worker frees);
  - a benchmark run: the rows finished by then (a row file's mtime is its end, `seconds` its length), the cells in the
    state they had, only runs older than this one as history.
`par` handed to the estimate = the builds in flight at that moment (what the collector sees as the job's held slots,
`locks`); the job's `workers` when none is yet.
Error = |predicted - actual| / actual, both being the time still to go ("ещё ~X"), at that moment.
"""
from __future__ import annotations

import dataclasses
import glob
import heapq
import json
import os
import re
import statistics
import sys
import time as _time
import types
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import collect  # noqa: E402

addon = collect.addon()
from junkroan.runs import build_estimate  # noqa: E402
from junkroan.runs.store import DEFAULT_LOG, Store  # noqa: E402

FRACTIONS = (0.25, 0.5, 0.75)


class _Clock:
    """The add-on's `time` with `time()` frozen at the moment under test."""
    now = 0.0

    def time(self):
        return self.now

    def __getattr__(self, name):
        return getattr(_time, name)


CLOCK = _Clock()


class _NoMemo:
    def get(self, key, stamp, make):
        return make()

    def save(self):
        pass


def _ts(s: str) -> float:
    return datetime.fromisoformat(s).timestamp()


def human(s: float | None) -> str:
    if s is None:
        return "нет оценки"
    return addon.human_duration(max(0.0, s))


# ---------------------------------------------------------------- the cases

def replay_lines(out: Path) -> list[tuple[str, str, float | None]]:
    """(reference, line, took seconds or None) of every finished-build line of a replay's `.out`, in file order."""
    got = []
    for line in out.read_text(encoding="utf-8", errors="replace").splitlines():
        r = addon._REPLAY_REF.match(line)
        if not r:
            continue
        m = addon._DONE_LINE.match(line)
        got.append((r[1], line, addon._done_s(m) if m else None))
    return got


def replay_case(j) -> dict | None:
    out = Path(j.out) if j.out else None
    if not out or not out.is_file():
        return None
    lines = replay_lines(out)
    if len(lines) < 4 or any(t is None for _, _, t in lines):
        return None  # a failed build has no length: its end cannot be rebuilt
    argv = addon._argv(j)
    pool = addon._flag(argv, "--workers")
    par = int(pool) if pool and pool.isdigit() else 5
    t0, t1 = _ts(j.start_ts), _ts(j.end_ts)
    order = sorted(range(len(lines)), key=lambda i: lines[i][0] + "-s4.pob.txt")
    free = [t0] * min(par, len(lines))
    heapq.heapify(free)
    starts, ends = {}, {}
    for i in order:
        starts[i] = heapq.heappop(free)
        ends[i] = starts[i] + lines[i][2]
        heapq.heappush(free, ends[i])
    makespan = max(ends.values()) - t0
    return {"kind": "replay", "job": j, "t0": t0, "t1": t1, "n": len(lines), "lines": lines, "starts": starts, "ends": ends,
            "fit": makespan / (t1 - t0), "par": par}


def bench_case(j) -> dict | None:
    run_dir = getattr(j, "run_dir", None)
    d = None
    if run_dir:
        for c in (addon.BENCH / Path(run_dir).name, Path(run_dir)):
            if (c / "args.json").is_file():
                d = c
                break
    if d is None:
        return None
    rows = []
    for f in sorted((d / "rows").glob("*.json")):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        end = f.stat().st_mtime
        rows.append({"stem": f.stem, "slug": r.get("slug"), "seed": r.get("seed"), "ok": bool(r.get("ok")),
                     "seconds": float(r.get("seconds") or 0), "end": end, "start": end - float(r.get("seconds") or 0)})
    if len(rows) < 2:
        return None
    args = json.loads((d / "args.json").read_text(encoding="utf-8"))
    planned = []
    vf = d / "variants.json"
    if vf.is_file():
        try:
            planned = [p for p in json.loads(vf.read_text(encoding="utf-8")).get("planned", []) if p.get("stem")]
        except (OSError, ValueError):
            planned = []
    return {"kind": "bench", "job": j, "t0": _ts(j.start_ts), "t1": _ts(j.end_ts), "n": len(rows), "rows": rows,
            "dir": d, "args": args, "planned": planned, "par": j.workers or 1}


# ---------------------------------------------------------------- the estimate at a moment

def _job_at(j, jobs, t):
    running = dataclasses.replace(j, state="running", end_ts=None)
    before = [x for x in jobs if x.id != j.id and x.end_ts and _ts(x.end_ts) <= t]
    return running, before + [running]


SCRATCH = HERE / ".cache" / "est985"  # what a run leaves here stays: nothing in this script deletes


def _predict_replay(case, t, jobs):
    j = case["job"]
    done = [i for i, e in case["ends"].items() if e <= t]
    SCRATCH.mkdir(parents=True, exist_ok=True)
    real_glob = addon.glob
    # the build files the glob finds: one per finished-build line, named after its reference (a repeated reference is
    # a variant file), so the estimate meets the same references the run printed
    seen: dict[str, int] = {}
    files = []
    for ref, _, _ in case["lines"]:
        k = seen[ref] = seen.get(ref, 0) + 1
        files.append(str(SCRATCH / (f"{ref}-s4.pob.txt" if k == 1 else f"{ref}-s4-no-v{k}.pob.txt")))
    out = SCRATCH / f"{j.id}-{int(t)}.out"
    out.write_text("".join(case["lines"][i][1] + chr(10) for i in sorted(done)), encoding="utf-8")
    if done:
        last = max(case["ends"][i] for i in done)
        os.utime(out, (last, last))
    addon.glob = types.SimpleNamespace(glob=lambda pattern, recursive=False: list(files))
    try:
        jj, jobs_t = _job_at(dataclasses.replace(j, out=str(out)), jobs, t)
        flying = sum(1 for i in range(case["n"]) if case["starts"][i] <= t < case["ends"][i])
        return addon.estimate(jj, jobs_t, None, flying or case["par"], _NoMemo()), len(done), None
    finally:
        addon.glob = real_glob


def bench_cells(case, t):
    """The cells the collector would hold at t: base slug x seed rows, the variant rows that exist or are planned."""
    args, rows = case["args"], case["rows"]
    seeds = [args.get("seed", 1) + i for i in range(args.get("seeds", 1))]
    by_stem = {r["stem"]: r for r in rows}
    cells = []

    def cell(slug, seed, stem, variant=None):
        c = {"ref": slug, "seed": seed, "state": "waiting" if variant is None else "queued"}
        r = by_stem.get(stem)
        if r and r["end"] <= t:
            c.update(state="done" if r["ok"] else "failed", took=r["seconds"])
        elif r and r["start"] <= t:
            c.update(state="running", started=r["start"])
        return c

    base_done = 0
    for slug in args.get("slugs", []):
        for seed in seeds:
            c = cell(slug, seed, f"{slug}-s{seed}")
            base_done += c["state"] in ("done", "failed")
            cells.append(c)
    base_rows = len(cells)
    stems = {}
    for p in case["planned"]:
        base = by_stem.get(p.get("after"))
        if base is None or base["end"] <= t:  # planned once its base row is finished
            stems[p["stem"]] = None
    for r in rows:
        if addon.VARIANT_RE.match(r["stem"]) and r["start"] <= t:
            stems[r["stem"]] = None
    for stem in stems:
        m = addon.VARIANT_RE.match(stem)
        if m and m["slug"] in args.get("slugs", []):
            cells.append(cell(m["slug"], int(m["seed"]), stem, variant=m["name"]))
    return cells


def _predict_bench(case, t, jobs):
    j = case["job"]
    cells = bench_cells(case, t)
    tmp = SCRATCH / f"{j.id}-{int(t)}"
    (tmp / "rows").mkdir(parents=True, exist_ok=True)
    (tmp / "args.json").write_text(json.dumps(case["args"]))
    for r in case["rows"]:
        if r["end"] <= t:
            (tmp / "rows" / f"{r['stem']}.json").write_text(json.dumps(
                {"slug": r["slug"], "seconds": r["seconds"], "ok": r["ok"]}))
    own = case["dir"].name
    build_estimate._runs_newest_first = lambda root, _own=own: sorted(
        (p for p in root.iterdir() if p.is_dir() and p.name < _own), key=lambda p: p.name, reverse=True)
    build_estimate._from_history.cache_clear()
    jj, jobs_t = _job_at(j, jobs, t)
    flying = sum(c["state"] == "running" for c in cells)
    res = addon.estimate(jj, jobs_t, {"cells": cells, "dir": str(tmp)}, flying or case["par"], _NoMemo())
    return res, sum(c["state"] in ("done", "failed") for c in cells), None


def predict(case, t, jobs):
    CLOCK.now = t
    addon.time = CLOCK
    addon.NOW = datetime.fromtimestamp(t, tz=timezone.utc)
    return (_predict_replay if case["kind"] == "replay" else _predict_bench)(case, t, jobs)


# ---------------------------------------------------------------- the table

def candidates(jobs):
    out = []
    for j in jobs:
        if j.state != "done" or not j.start_ts or not j.end_ts:
            continue
        cmd = " ".join([j.cmd or "", *(j.argv or ())])
        if "replay_bench.py" in cmd:
            case = replay_case(j)
        elif "benchmark.py" in cmd:
            case = bench_case(j)
        else:
            continue
        if case and (case["t1"] - case["t0"]) >= 600:
            out.append(case)
    return out


def measure(case, jobs):
    rows = []
    dur = case["t1"] - case["t0"]
    for f in FRACTIONS:
        t = case["t0"] + f * dur
        (left, how), n_done, eta = predict(case, t, jobs)
        actual = case["t1"] - t
        err = None if left is None else abs(left - actual) / actual
        eta_err = None if eta is None else abs(eta - actual) / actual
        rows.append({"f": f, "pred": left, "how": how, "actual": actual, "err": err, "done": n_done,
                     "eta_err": eta_err})
    return rows


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="write the raw numbers here")
    ap.add_argument("--only", help="comma-separated job ids")
    a = ap.parse_args(argv)
    (HERE / ".cache").mkdir(exist_ok=True)
    jobs = Store(DEFAULT_LOG).jobs()
    cases = candidates(jobs)
    if a.only:
        keep = set(a.only.split(","))
        cases = [c for c in cases if c["job"].id in keep]
    result = []
    for c in cases:
        j = c["job"]
        m = measure(c, jobs)
        result.append({"id": j.id, "tag": j.tag, "kind": c["kind"], "builds": c["n"], "fit": c.get("fit"),
                       "dur": c["t1"] - c["t0"], "par": c["par"], "rows": m})
    if a.json:
        Path(a.json).write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


if __name__ == "__main__":
    for r in main(sys.argv[1:]):
        print(r["id"], r["kind"], r["tag"], r["builds"], f"fit={r['fit']}", human(r["dur"]))
        for x in r["rows"]:
            e = "-" if x["err"] is None else f"{x['err'] * 100:.0f}%"
            print("   ", int(x["f"] * 100), human(x["pred"]), x["how"], "vs", human(x["actual"]), e)
