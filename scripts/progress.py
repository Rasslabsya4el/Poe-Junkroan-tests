"""Where the project stands on the road to the prototype (docs/ROADMAP.md Phase 7 was the acceptance
bar; since 2026-09-26 the work items are GitHub issues, and this script's stage rows come from the
tracker, not from ROADMAP checkboxes -- issue #30).

Prints one row per stage -- how much of it is done and out of what -- and then the State block.
Two of the rows are not tracker counts but measurements taken from the benchmark runs in
`artifacts/benchmark/`: coverage (references at or above the author) and stability (seed spread),
because those are the stage's real unit (unchanged by #30, still exact to the digit). The rest come
from `gh`: #1's sub-issues (closed / total) and the open issues by triage label. The user's request
(2026-09-15): progress counted per reference, not per roadmap item, so the table says how far the
prototype is, not how much text was ticked off.

    python scripts/progress.py            # stage table + State block
    python scripts/progress.py --refs     # also one row per reference: run used, median, status

A reference is "covered" when its latest 3-seed benchmark run has median ours/author >= 100% with
a clean audit; the best row per (slug, seed) and the meaning of "clean" are exactly what
`scripts/benchmark.py` uses for its own median table, so both agree on the same runs.

When `gh` cannot answer (not installed, no network, a non-zero exit) the tracker rows are replaced
by one line saying so; everything else (coverage, stability, --refs, the State block) still prints,
and the exit code is still 0 -- a missing tracker is not a script failure.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "tuadh_329"
BENCHMARKS = ROOT / "artifacts" / "benchmark"
REPO = "Rasslabsya4el/Poe-Junkroan"

STAMP = re.compile(r"^\d{8}-\d{4}")  # artifacts/benchmark/<YYYYMMDD-HHMM>[-tag]
MARKER = re.compile(r"Runs count from: (\d{8}-\d{4})")  # optional line in the State block
EXCLUDE = re.compile(r"Runs excluded: ([^\n(]+)")  # optional: words; a run folder containing one is skipped (experimental pipelines)

TRIAGE_LABELS = ("needs-triage", "needs-info", "ready-for-agent", "ready-for-human", "wontfix")


# ---------------------------------------------------------------- roadmap ----
# Only the State block is still read from ROADMAP.md, as a fallback when docs/STATE.md (the live
# state, since 2026-09-26) is not passed in. The 7.1-7.4 checkboxes themselves are no longer counted
# (issue #30); the frozen ROADMAP can move to docs/archive/ without this script noticing.


def phase_text(roadmap: str) -> str:
    """Phase 7 only. Tolerant: the main session edits ROADMAP.md while this runs."""
    start = roadmap.find("## Phase 7.")
    start = 0 if start < 0 else start
    end = roadmap.find("## Later", start)
    return roadmap[start:] if end < 0 else roadmap[start:end]


def state_text(phase: str) -> str:
    m = re.search(r"### State[^\n]*\n(.*?)(?=\n### |\Z)", phase, re.S)
    return m.group(1).strip() if m else ""


# ------------------------------------------------------------------ gh -------


class GhUnavailable(Exception):
    """gh is missing, offline, returned a non-zero exit, or answered with something this script
    can't parse. Callers show its message as the one offline line the issue asks for."""


def _gh(args: list[str]) -> str:
    try:
        proc = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=30, check=False)
    except OSError as e:
        raise GhUnavailable(f"gh {' '.join(args)}: {e}") from e
    if proc.returncode != 0:
        reason = (proc.stderr or proc.stdout or "").strip().splitlines()[:1]
        raise GhUnavailable(f"gh {' '.join(args)}: {reason[0] if reason else f'exit {proc.returncode}'}")
    return proc.stdout


def _gh_json(args: list[str]):
    out = _gh(args)
    try:
        return json.loads(out)
    except ValueError as e:
        raise GhUnavailable(f"gh {' '.join(args)}: invalid JSON ({e})") from e


def sub_issues_of(issue: int, repo: str = REPO) -> list[dict]:
    """GitHub's own sub-issues API (one call): [{number, state, title, ...}, ...]. Empty (not an
    error) when the repo has none, or the endpoint isn't reachable for another reason gh still
    calls a success -- either way the caller falls back to the body task-list."""
    data = _gh_json(["api", f"repos/{repo}/issues/{issue}/sub_issues"])
    return data if isinstance(data, list) else []


def open_issues(repo: str = REPO) -> list[dict]:
    """One `gh issue list` call, all states, used for both the fallback (state of #1's referenced
    issues) and the triage-label counts (filtered to open here)."""
    data = _gh_json(["issue", "list", "-R", repo, "--state", "all", "--json",
                      "number,state,labels,title", "--limit", "200"])
    if not isinstance(data, list):
        raise GhUnavailable("gh issue list: unexpected response shape")
    # `gh issue list` says "OPEN" / "CLOSED", the REST sub-issues API "open" / "closed": one spelling here
    return [{**it, "state": str(it.get("state") or "").lower()} for it in data if isinstance(it, dict)]


TASK_REF = re.compile(r"^- \[([ x])\][^\n]*?#(\d+)", re.M)


def sub_issues_from_body(body: str, issues_by_number: dict[int, dict]) -> list[dict]:
    """Fallback when the sub-issues API returns nothing useful: '- [ ] ... #N' / '- [x] ... #N'
    task-list lines in #1's body, resolved against `issues_by_number` (a real issue's current
    state wins over a stale checkbox)."""
    out = []
    for mark, num in TASK_REF.findall(body):
        n = int(num)
        it = issues_by_number.get(n)
        state = it.get("state") if it else ("closed" if mark == "x" else "open")
        title = it.get("title", "") if it else ""
        out.append({"number": n, "state": state, "title": title})
    return out


def issue_body(issue: int, repo: str = REPO) -> str:
    data = _gh_json(["issue", "view", str(issue), "-R", repo, "--json", "body"])
    if not isinstance(data, dict):
        raise GhUnavailable(f"gh issue view {issue}: unexpected response shape")
    return data.get("body") or ""


def tracker_rows(repo: str = REPO) -> list[dict]:
    """Stage rows from the tracker (issue #30): #1's sub-issues closed/total, and open issues by
    triage label. Raises GhUnavailable when gh cannot answer -- the caller prints the one offline
    line instead."""
    issues = open_issues(repo)  # required for the label counts either way
    subs = sub_issues_of(1, repo)
    if not subs:
        by_number = {it.get("number"): it for it in issues if isinstance(it, dict)}
        subs = sub_issues_from_body(issue_body(1, repo), by_number)

    rows: list[dict] = []
    if subs:
        closed = sum(1 for it in subs if it.get("state") == "closed")
        open_titles = [str(it.get("title") or "")[:40] for it in subs if it.get("state") != "closed"]
        rows.append({"stage": "#1 acceptance", "unit": "sub-issues closed", "done": closed,
                     "of": len(subs), "note": "; ".join(open_titles)})
    else:
        rows.append({"stage": "#1 acceptance", "unit": "sub-issues closed", "done": 0, "of": 0,
                     "note": "no sub-issues found (API empty, body has no task list)"})

    open_only = [it for it in issues if it.get("state") == "open"]
    total_open = len(open_only)
    counts = {lbl: 0 for lbl in TRIAGE_LABELS}
    counts["no label"] = 0
    for it in open_only:
        names = {l.get("name") for l in (it.get("labels") or []) if isinstance(l, dict)}
        matched = [lbl for lbl in TRIAGE_LABELS if lbl in names]
        if matched:
            for lbl in matched:
                counts[lbl] += 1
        else:
            counts["no label"] += 1
    for key in (*TRIAGE_LABELS, "no label"):
        rows.append({"stage": key, "unit": "open issues", "done": counts[key], "of": total_open, "note": ""})
    return rows


# ------------------------------------------------------------ benchmarks ----


def load_runs(benchmark_dir: Path) -> list[tuple[str, list[dict]]]:
    """(stamp, rows) per benchmark folder, oldest first; unreadable or aborted runs skipped."""
    runs: list[tuple[str, list[dict]]] = []
    if not benchmark_dir.is_dir():
        return runs
    for d in sorted(p for p in benchmark_dir.iterdir() if p.is_dir()):
        if not STAMP.match(d.name):
            continue
        try:
            rows = json.loads((d / "results.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(rows, list):
            continue
        runs.append((d.name, [r for r in rows if isinstance(r, dict) and r.get("ok")]))
    return runs


def _violation(row: dict) -> float:
    stages = row.get("stages") or []
    return sum(float(s.get("violation") or 0.0) for s in stages[-1:])


def best_rows(rows: list[dict], slug: str) -> dict[object, dict]:
    """Best row per seed for one slug -- the same key scripts/benchmark.py uses: audit clean first,
    then the lowest violation, then the highest DPS. Keystone variants compete with the plain run."""
    best: dict[object, tuple[tuple, dict]] = {}
    for r in rows:
        if r.get("slug") != slug:
            continue
        key = ((r.get("audit_errors") or 0) == 0, -max(0.0, _violation(r)), r.get("ours") or 0)
        seed = r.get("seed")
        if seed not in best or key > best[seed][0]:
            best[seed] = (key, r)
    return {seed: row for seed, (_key, row) in best.items()}


def is_clean(row: dict) -> bool:
    return (row.get("audit_errors") or 0) == 0 and _violation(row) <= 1e-9


def reference_row(slug: str, runs: list[tuple[str, dict[object, dict]]]) -> dict:
    """One reference's standing. `runs` is (stamp, best-row-per-seed) oldest first, already
    filtered to qualifying runs that have at least one row for this slug."""
    row = {"slug": slug, "run": "-", "seeds": 0, "median": None, "min": None, "max": None,
           "spread": None, "errors": 0, "measured": False, "covered": False, "status": "no run"}
    if not runs:
        return row
    three = [r for r in runs if len(r[1]) >= 3]
    stamp, best = (three or runs)[-1]
    ratios = sorted(float(r.get("ratio_lane") or 0.0) for r in best.values() if is_clean(r))
    row.update(run=stamp, seeds=len(ratios), errors=sum(r.get("audit_errors") or 0 for r in best.values()))
    if three:
        row["measured"] = True
        if len(ratios) >= 3:
            row.update(median=ratios[len(ratios) // 2], min=ratios[0], max=ratios[-1],
                       spread=ratios[-1] - ratios[0])
            row["covered"] = row["median"] >= 1.0
            row["status"] = "covered" if row["covered"] else "below author"
        else:
            # the latest 3-seed run did not finish clean: no fallback to an older run, the
            # reference is measured and infeasible until it is rerun
            row["status"] = "infeasible"
        return row
    pool = [r for r in best.values() if is_clean(r)] or list(best.values())
    value = max(float(r.get("ratio_lane") or 0.0) for r in pool)
    row.update(median=value, min=value, max=value)
    row["status"] = f"1 seed only: {value:.0%}" + ("" if row["seeds"] else " (audit errors)")
    return row


def references(fixtures_dir: Path, benchmark_dir: Path, marker: str | None, excluded: tuple[str, ...] = ()) -> list[dict]:
    runs = [(stamp, rows) for stamp, rows in load_runs(benchmark_dir)
            if (marker is None or stamp[:13] >= marker) and not any(word and word in stamp for word in excluded)]
    out = []
    for path in sorted(fixtures_dir.glob("*.pob.txt")) if fixtures_dir.is_dir() else []:
        slug = path.name[: -len(".pob.txt")]
        per_run = [(stamp, best) for stamp, best in ((s, best_rows(rows, slug)) for s, rows in runs) if best]
        out.append(reference_row(slug, per_run))
    return out


# ---------------------------------------------------------------- report ----


def report(roadmap: str, fixtures_dir: Path, benchmark_dir: Path,
           state: str | None = None) -> tuple[list[dict], list[dict], str]:
    """(stage rows, reference rows, State text). `state` is docs/STATE.md when it exists (since
    2026-09-26 the live state; the ROADMAP's State block is a frozen log) and carries the markers.
    Since issue #30 the stage rows here are only the benchmark-measured ones (coverage, stability);
    the tracker rows (#1's sub-issues, open issues by triage label) come from `tracker_rows()`,
    which needs `gh` and so is kept separate from this pure function."""
    if state is None:
        state = state_text(phase_text(roadmap))
    m = MARKER.search(state)
    marker = m.group(1) if m else None
    e = EXCLUDE.search(state)
    excluded = tuple(w.strip() for w in e.group(1).split(",") if w.strip()) if e else ()
    refs = references(fixtures_dir, benchmark_dir, marker, excluded)
    measured = [r for r in refs if r["measured"]]
    stages: list[dict] = [{
        "stage": "7.2 coverage",
        "unit": "references at or above the author (3-seed median, audit clean)",
        "done": sum(1 for r in refs if r["covered"]),
        "of": len(refs),
        "note": f"runs since {marker}" if marker else "all runs",
    }, {
        "stage": "7.3 stability",
        "unit": "references with seed spread <= 10 points",
        "done": sum(1 for r in measured if r["covered"] and (r["spread"] or 0) <= 0.10),
        "of": len(measured),
        "note": f"{len(measured)} of {len(refs)} references measured",
    }]
    return stages, refs, state


def _num(x: float) -> str:
    return f"{x:g}"


def _pct(x: float | None) -> str:
    return "-" if x is None else f"{x:.0%}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Phase 7 progress: stages, coverage, State block.")
    ap.add_argument("--refs", action="store_true", help="also print one row per reference")
    ap.add_argument("--root", type=Path, default=ROOT,
                     help="repo root to read docs/ROADMAP.md, docs/STATE.md, tests/fixtures and "
                          "artifacts/benchmark from (default: this script's own repo). Lets a "
                          "worktree checkout of the script read another checkout's artifacts, e.g. "
                          "to diff coverage/stability before vs. after a change to this file.")
    args = ap.parse_args(argv)
    root: Path = args.root
    fixtures_dir = root / "tests" / "fixtures" / "tuadh_329"
    benchmark_dir = root / "artifacts" / "benchmark"
    roadmap = (root / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    state_file = root / "docs" / "STATE.md"
    live_state = state_file.read_text(encoding="utf-8").strip() if state_file.exists() else None
    stages, refs, state = report(roadmap, fixtures_dir, benchmark_dir, state=live_state)

    try:
        tracker = tracker_rows()
        offline_note = None
    except GhUnavailable as e:
        tracker = []
        offline_note = str(e)

    if offline_note:
        print(f"tracker rows unavailable: {offline_note}\n")

    print("| stage | unit | done | of | note |")
    print("|---|---|---|---|---|")
    for s in [*tracker, *stages]:
        print(f"| {s['stage']} | {s['unit']} | {_num(s['done'])} | {_num(s['of'])} | {s['note']} |")

    if args.refs:
        print("\n| reference | run | seeds | median | min | max | audit | status |")
        print("|---|---|---|---|---|---|---|---|")
        for r in refs:
            audit = "-" if r["run"] == "-" else ("clean" if not r["errors"] else f"{r['errors']} errors")
            print(f"| {r['slug']} | {r['run']} | {r['seeds']} | {_pct(r['median'])} | {_pct(r['min'])} "
                  f"| {_pct(r['max'])} | {audit} | {r['status']} |")

    if state:
        print("\n" + state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
