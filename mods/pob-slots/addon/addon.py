"""The pob-slots monitor's add-on for this project (Path of Exile / Path of Building): PoB runs, the laptop, the
readings queue and the one-build detail. `collect.py` (the generic collector) loads this file when
`config/orchestration.json` names it in `monitor.addon`; the laptop runs it too (`collect.remote_program` ships both
files over ssh), so it needs nothing but `collect` and the project's own `src/`.

Contract with the generic collector (`bin/collect.py`):
    fast(ctx)          -> the extra sections of the fast payload (`readings`, `runs`, `runs_error`, `laptop`, `status`)
    machine_pids(ctx)  -> (slot pids, daemon pid) of the PoB slots, for the generic `machine()`; `ctx.sections` is `fast`'s result
    MODES              -> extra command-line modes: name -> callable(*args)
    WORK_KEY / WORK_PREFIX -> the machine card's key for PoB's share and the process-name prefix that counts as PoB
    human_duration     -> the project's one duration formatter
    SESSION_KINDS      -> extra session kinds for the orch card: ((name, compiled title regex), ...)
"""
from __future__ import annotations

import glob
import heapq
import json
import math
import os
import re
import statistics
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from collect import CACHE_DIR, NO_WINDOW, NOW, REPO, hd, machine, parse_ts, remote_program, words
from junkroan.report_format import human_duration  # noqa: E402,F401

WORK_KEY = "pob"
WORK_PREFIX = "junkroan"
#: Extra session kinds for the orch card; `keymaster: job_failed j-...` is the name anomalies.py gives its sessions.
SESSION_KINDS = (("keymaster", re.compile(r"^keymaster\b", re.I)),)


# ================================================================ PoB runs (slots, queue, run cells)

BENCH = REPO / "artifacts" / "benchmark"


def bench_roots(job) -> list[Path]:
    """Where a job's benchmark folders can be. A job's `out` is `<checkout>/artifacts/runs/<name>.out` of the checkout
    its daemon runs in; the laptop's daemon works in its own checkout (`poe-junkroan-v2-daemon`, #984), so its
    `benchmark/` is not under this file's REPO (the PC's path, also the laptop's main checkout)."""
    roots = []
    out = getattr(job, "out", None)
    if out:
        p = Path(out)
        if p.parent.name == "runs" and p.parent.parent.name == "artifacts" and len(p.parents) > 2:
            roots.append(p.parents[2] / "artifacts" / "benchmark")
    if BENCH not in roots:
        roots.append(BENCH)
    return roots


def bench_dir_for(job) -> Path | None:
    argv = list(job.argv or job.cmd.split())
    if "--tag" not in argv:
        return None
    tag = argv[argv.index("--tag") + 1]
    for root in bench_roots(job):
        found = sorted(root.glob(f"*-{tag}"))
        if found:
            return found[-1]
    return None


def job_dir(job) -> Path | None:
    """The run's benchmark folder. A finished job's `run_dir` names it inside a snapshot that is
    deleted later; the same folder name under the main artifacts/benchmark (the snapshot's
    junction target) still holds it."""
    run_dir = getattr(job, "run_dir", None)
    if run_dir:
        for d in (*(root / Path(run_dir).name for root in bench_roots(job)), Path(run_dir)):
            if (d / "args.json").is_file():
                return d
    if getattr(job, "state", "running") in ("running", "queued"):
        return bench_dir_for(job)
    # A finished job without `run_dir`: a folder of its tag made while it ran (the name starts with
    # its local start minute), never the folder of an older job that had the same tag.
    start, end = _local(getattr(job, "start_ts", None)), _local(getattr(job, "end_ts", None))
    d = bench_dir_for(job)
    if d is None or start is None:
        return None
    try:
        made = datetime.strptime(d.name[:13], "%Y%m%d-%H%M").astimezone()
    except ValueError:
        return None
    return d if start - timedelta(minutes=2) <= made <= (end or NOW.astimezone()) else None


VARIANT_RE = re.compile(r"^(?P<slug>.+)-s(?P<seed>\d+)-no-(?P<name>.+)$")


def _read_row(row_path: Path) -> dict:
    try:
        return json.loads(row_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def _fill_cell(cell: dict, d: Path, stem: str, took: list) -> None:
    """State of one cell from its row file (done/failed) or log (running); else it stays as given."""
    row_path, log_path = d / "rows" / f"{stem}.json", d / "logs" / f"{stem}.log"
    if row_path.exists():
        r = _read_row(row_path)
        ok = r.get("ok", False)
        cell.update(state="done" if ok else "failed", took=hd(r.get("seconds")),
                    stat=r.get("stat") or "CombinedDPS",
                    metrics=[
                        [label(r.get("stat") or "CombinedDPS"), r.get("ours"), r.get("author_lane") or r.get("author_raw")],
                        [label("Life"), r.get("ours_life"), r.get("author_life")],
                        [label("TotalEHP"), r.get("ours_ehp"), r.get("author_ehp")],
                        [label("PhysicalMaximumHitTaken"), r.get("ours_maxhit"), r.get("author_maxhit")],
                    ])
        if r.get("seconds"):
            took.append(r["seconds"])
    elif log_path.exists():
        started = log_path.stat().st_ctime
        stage = build_stage(log_path, started)
        cell.update(state="running", took=datetime.fromtimestamp(started).strftime("%H:%M"), started=started,
                    status=status_word(stage), **stage)


# #711: the step a running build is in comes from its log's own lines (the pipeline writes `step start: <name>` when
# a step starts and `loop pass N move <kind>` inside the improvement loop). The list of steps, their three groups and
# the line formats are the repo's `junkroan.optimizer.stage_catalog`, imported, never copied here; each group's width
# on the bar is its measured share of build time over the latest weekly run (scripts/stage_shares.py).
STAGE_LINE = re.compile(r"^  (\S.*?\S) {2,}(\d[\d.,]*) (s|min|h)\b(?: (\d+) min\b)?")
STAGE_SHARES = CACHE_DIR / "stage_shares.json"


def _catalog():
    """The repo's stage catalog, or None on a checkout that predates it (its pipeline writes no start lines either)."""
    try:
        from junkroan.optimizer import stage_catalog
        return stage_catalog
    except Exception:  # noqa: BLE001
        return None


def stage_shares(_memo: dict = {}) -> dict | None:
    """{"run", "builds", "groups": {group: share}, "steps": {step: share}}: the median share of build time per group
    and per step over the latest weekly run, as scripts/stage_shares.py counts it. Kept in bin/.cache by that run's
    folder name and the catalog's mtime; None when there is no weekly run or no catalog (then no bar is drawn)."""
    if "v" in _memo:
        return _memo["v"]
    out = None
    try:
        from junkroan.runs.gates import newest_gate
        name = newest_gate(REPO / "artifacts")
        key = [name, (REPO / "src" / "junkroan" / "optimizer" / "stage_catalog.py").stat().st_mtime]
        try:
            memo = json.loads(STAGE_SHARES.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            memo = {}
        if name and memo.get("key") == key:
            out = memo
        elif name:
            import importlib.util
            spec = importlib.util.spec_from_file_location("stage_shares", REPO / "scripts" / "stage_shares.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            res = mod.shares(mod.load_rows(REPO / "artifacts" / "benchmark" / name))
            if res["builds"]:
                out = {"key": key, "run": name, "builds": res["builds"], "groups": res["groups"],
                       "steps": {k: v["median_share"] for k, v in res["steps"].items()}}
                STAGE_SHARES.parent.mkdir(exist_ok=True)
                STAGE_SHARES.write_text(json.dumps(out), encoding="utf-8")
    except Exception:  # noqa: BLE001
        out = None
    _memo["v"] = out
    return out


def _stage_seconds(m: re.Match) -> float:
    return float(m[2].replace(",", "")) * {"s": 1, "min": 60, "h": 3600}[m[3]] + (int(m[4]) * 60 if m[4] else 0)


def build_stage(log_path: Path, started: float | None = None, now: float | None = None) -> dict:
    """Where a running build is, read from its log: `group` / `step` = its last `step start:` line (a step that has
    not started is never named), `stage` = the words of the row (in the loop «improvement loop, pass N, <move>»),
    `bar` = the three groups' widths (measured shares) and how far each is filled. No start line yet -> no `stage`
    (the row reads «запускается»); a log of an older pipeline (ended stages, no start lines) -> `after` = the last
    stage that ended, a fact, not the next one guessed. `stage_index` / `stage_count` (#985 c) = the named step's place
    among the catalog's marks (1-based, of `len(STEPS)`), given only when a start line named a catalog step; the loop's
    time fill in `bar` is a guess and is never a stage."""
    cat = _catalog()
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    lines = text.splitlines()
    if lines and not text.endswith("\n"):  # #992: a last line with no newline is still being written: not a line yet
        lines.pop()
    step, loop, ended = None, None, []
    for line in lines:
        if line.startswith("  "):
            m = STAGE_LINE.match(line)
            if m:
                ended.append((m[1], _stage_seconds(m)))
            continue
        if cat is None or not line.startswith(("step ", "loop pass ", "fixed point check ")):
            continue
        kind, val = cat.parse_log_line(line)
        if kind == "start":
            step, loop = val, None
        elif kind == "loop_move":
            loop = val
    if step is None:
        # #992 row 5: a plain word of #985's list, never the English step name; a stage the catalog does not know = «считается»
        return {"after": after_word(ended[-1][0]) or STATUS_WORDS["generic"]} if ended else {}
    st = cat.step_of(step)
    group = st.group if st else None
    if group == cat.IMPROVEMENT_LOOP:
        m = re.fullmatch(r"loop pass (\d+)", step)
        if step == "fixed point check":
            words = step + (f", {loop[1]}" if loop else "")
        elif m:
            words = f"{group}, pass {m[1]}" + (f", {loop[1]}" if loop and loop[0] == int(m[1]) else "")
        else:  # the loop's opening
            words = f"{group}, {step[5:] if step.startswith('loop ') else step}"
    else:
        words = f"{group}: {step}" if group else step
    out = {"stage": words, "group": group, "step": step}
    if st is not None:  # #985 c: the scale = the step's place among the catalog's marks, only from a real `step start:` line
        out["stage_index"] = cat.STEPS.index(st) + 1
        out["stage_count"] = len(cat.STEPS)
    if loop:
        out["move"] = loop[1]
    sh = stage_shares()
    total = sum(sh["groups"].get(g, 0.0) for g in cat.GROUPS) if sh else 0.0
    if group and total > 0:
        w = [sh["groups"].get(g, 0.0) / total for g in cat.GROUPS]

        def part(grp: str) -> float:  # of a group's steps, the measured share of those before the current one
            steps = [s for s in cat.STEPS if s.group == grp]
            weights = [sh["steps"].get(s.name, 0.0) for s in steps]
            i = steps.index(st)
            return sum(weights[:i]) / sum(weights) if sum(weights) > 0 else i / len(steps)

        if group == cat.CONSTRUCTION:
            fill = [part(group), 0.0, 0.0]
        elif group == cat.FINISH:
            fill = [1.0, 0.96, part(group)]
        elif step == "fixed point check":  # it runs after the finish steps
            fill = [1.0, 0.98, 1.0]
        else:
            # the loop has no fixed number of passes: it fills by this build's own time in it against the time its
            # construction took, scaled by the measured loop / construction ratio
            spent = sum(s for n, s in ended if cat.group_of(n) == cat.CONSTRUCTION)
            expect = spent * w[1] / w[0] if w[0] > 0 else 0.0
            el = (time.time() if now is None else now) - started - spent if started is not None else 0.0
            fill = [1.0, max(0.02, min(0.95, el / expect)) if expect > 0 else 0.02, 0.0]
        out["bar"] = {"w": [round(x, 4) for x in w], "fill": [round(x, 3) for x in fill], "at": cat.GROUPS.index(group)}
    return out


#: #985 d2: the status word of each state, the brain's table (ticket #985, comment of 2026-10-14 01:20, over the d1
#: table's states). A PoB or game term keeps its PoB spelling (Tree, Items, Config, Anoint, Flasks, Jewels, aura, gems);
#: the rest is plain Russian. Each word is written once, here; the maps below name the key of a state's word.
STATUS_WORDS = {
    "reference": "читает reference PoB",     # no start line yet: only the author lines
    "skeleton": "собирает скелет",
    "gear": "подбирает Items",
    "aura": "ставит уровни aura",
    "tree": "строит Tree",
    "tree rebuilt": "перестраивает Tree",
    "anoint": "выбирает Anoint",
    "flasks": "подбирает Flasks",
    "jewels": "подбирает Jewels",
    "picks": "перебирает gems",
    "loop gear": "улучшает Items",
    "kick tree": "встряхивает Tree",
    "kick joint": "встряхивает Tree, Items",
    "tree edit": "правит Tree",
    "fixed point": "итоговая проверка",
    "final config": "финальный Config",
    "waiting": "ждёт слот",
    "replay": "пересчитывает build",
    "done": "готово",
    "failed": "упал",
    "generic": "считается",                  # no state of the log is known (an older pipeline's log, a step not in the catalog)
}
#: the catalog's step name -> key. A step the d1 table does not list takes the nearest word (the brain confirms it).
_STEP_STATUS = {
    "skeleton applied": "skeleton",
    "config (conservative lane)": "skeleton",
    "rig gear": "gear",                           # not in the d1 table (rig-first builds only)
    "rig tree": "tree",                           # not in the d1 table
    "gear pass 1 (rig tree)": "gear",
    "gear pass 1 (empty tree)": "gear",
    "config re-derived (after gear pass 1)": "skeleton",  # not in the d1 table
    "flat-reservation aura levels": "aura",
    "supports re-picked (no number)": "picks",    # not in the d1 table: re-picks the gems
    "tree seed toward <stat>": "tree",            # not in the d1 table
    "tree greedy": "tree",
    "gear pass 2 (with tree)": "gear",
    "tree rebuilt on gear": "tree rebuilt",
    "anoint": "anoint",
    "flasks": "flasks",
    "clusters": "jewels",                         # not in the d1 table: cluster jewels
    "jewels": "jewels",
    "supports re-picked": "picks",                # not in the d1 table
    "utility links": "picks",                     # not in the d1 table: links of the gems
    "fill": "picks",                              # not in the d1 table: #1156 fills free sockets with gems
    "tree refine": "tree edit",                   # not in the d1 table: the refine move's own word
    "loop opening": "tree edit",                  # not in the d1 table: the loop's first move is refine
    "loop pass <N>": "tree edit",                 # a pass before its first move
    "repair pass <N>": "tree edit",               # #1064: the repair rule re-runs the loop moves on a finished build
    "fixed point check": "fixed point",
    "anoint re-pick": "final config",
    "config (final lanes)": "final config",
}
#: a loop move's key; the d1 table lists refine, swaps, gear, picks, kick-tree, kick-joint, the rest are nearest words
_MOVE_STATUS = {
    "refine": "tree edit", "swaps": "tree edit", "regions": "tree edit", "corridors": "tree edit",
    "ascendancy-swap": "tree edit",  # not in the d1 table: #1157 swaps ascendancy points on the tree
    "gear": "loop gear", "weapon-base": "loop gear", "picks": "picks", "aura levels": "aura", "lanes": "final config",
    "kick-tree": "kick tree", "kick-joint": "kick joint",
}


def after_word(stage_name: str) -> str | None:
    """#992 row 5: the plain word of the last stage an older pipeline's log shows as ended (the same word the step's
    own running state takes in `_STEP_STATUS`); None when the catalog does not know the stage (the caller says «считается»)."""
    cat = _catalog()
    st = cat.step_of(stage_name) if cat is not None else None
    key = _STEP_STATUS.get(st.name) if st is not None else None
    return STATUS_WORDS[key] if key else None


def status_word(stage: dict) -> str:
    """#985 d2: the status word of a running build from `build_stage`'s reading of its log. `{}` (no start line yet, only
    the author lines) is «читает reference PoB»; an older pipeline's `after` reading and a step the catalog does not know
    are «считается»; a loop step's word is its move's (`fixed point check` is one word whatever its move)."""
    if not stage:
        return STATUS_WORDS["reference"]
    cat = _catalog()
    st = cat.step_of(stage["step"]) if cat is not None and "step" in stage else None
    if st is None:
        return STATUS_WORDS["generic"]
    move = stage.get("move")
    if st.name == "fixed point check":
        key = "fixed point"
    elif move:
        key = _MOVE_STATUS.get(move, "generic")
    else:
        key = _STEP_STATUS.get(st.name, "generic")
    return STATUS_WORDS[key]


_CELL_STATUS = {"waiting": "waiting", "queued": "waiting", "done": "done", "failed": "failed", "running": "replay"}


def _stamp(cell: dict) -> None:
    """#985 d2: a cell without a reading of its own takes its word by state: a waiting or queued slot, a finished row,
    and a replay build that runs (a replay's `.out` has no stage lines, so its running build has no reading)."""
    cell.setdefault("status", STATUS_WORDS[_CELL_STATUS[cell["state"]]])


_LEAGUE_SLUG = re.compile(r"^z(\d{3})_(.+)$")


def build_class(slug: str, _memo: dict = {}) -> dict:
    """Class and ascendancy of a reference build, read off its fixture PoB (the lookup of scripts/benchmark.py
    `fixture_path`): {"class": "Duelist", "asc": "Gladiator"}, or {} when the fixture is not found."""
    if slug in _memo:
        return _memo[slug]
    fx = REPO / "tests" / "fixtures"
    paths = []
    if m := _LEAGUE_SLUG.match(slug):
        paths.append(fx / f"zizaran_{m[1]}" / "early" / f"{m[2]}.pob.txt")
    paths += [fx / "tuadh_329" / f"{slug}.pob.txt"] + [d / f"{slug}.pob.txt" for d in sorted(fx.glob("zizaran_*/early"), reverse=True)]
    out: dict = {}
    for p in paths:
        if p.is_file():
            import base64
            import zlib
            try:
                code = p.read_text(encoding="utf-8").strip().replace("-", "+").replace("_", "/")
                xml = zlib.decompress(base64.b64decode(code + "=" * (-len(code) % 4))).decode("utf-8", "replace")
                tag = re.search(r"<Build [^>]*>", xml)
                attrs = dict(re.findall(r'(className|ascendClassName)="([^"]*)"', tag[0])) if tag else {}
                out = {"class": attrs.get("className") or None, "asc": attrs.get("ascendClassName") if attrs.get("ascendClassName") not in (None, "", "None") else None}
            except (ValueError, OSError, zlib.error):
                out = {}
            break
    _memo[slug] = out
    return out


def run_kind(job) -> str:
    """#683 r5 (owner 10.10 02:3x): what a run executes, told in its row so two kinds never read as one: `benchmark`
    (scripts/benchmark.py builds from scratch and logs its steps), `replay` (replay_bench.py replays one move on
    finished builds, no step log), `tests` (pytest), `request` (`junkroan build`), else empty."""
    cmd = " ".join([job.cmd or "", *[str(a) for a in (getattr(job, "argv", None) or ())]])
    if "replay_bench.py" in cmd:
        return "replay"
    if "benchmark.py" in cmd:
        return "benchmark"
    if "pytest" in cmd:
        return "tests"
    # #995 send-back 1 (defect 5: the «Готово» row of #980's `scripts/search.py` run had no kind word): `junkroan build`
    # hands its request to scripts/search.py (src/junkroan/cli.py `_run("search.py", ...)`), so a run of that script
    # is the same kind, a build by request
    if re.search(r"(^|[\s/\\])junkroan(\.exe)?\s+build\b|junkroan(\.cli)?\s+build\b|(^|[\s/\\])search\.py\b", cmd):
        return "request"
    return ""


#: #1010: the plain name of a run's kind, the words the pane used before #985 («недельный прогон» and «прогон тикета» are
#: the owner's own words, #578; the owner took the other new names back, 2026-10-14: «Вернуть старые»).
_KIND_NAME = {
    "replay": "replay",
    "tests": "тесты",
    "request": "билд по запросу",
}
_CORE_TAG = re.compile(r"-core(?:-\d+)?$")  # `P2-core`, `P2-core-3`: runs.py derive_name, the weekly core run (#578)


def kind_name(what: str | None, job) -> str:
    """#1010: the name of a run's kind. `benchmark` is «недельный прогон» under the core tag, «прогон тикета» with a
    ticket (`--issue N`), else `benchmark`; `replay`, `tests`, `request` take their name from `_KIND_NAME`; a command
    `run_kind` does not know gets an empty name."""
    if what == "benchmark":
        if _CORE_TAG.search(getattr(job, "tag", None) or ""):
            return "недельный прогон"
        return "прогон тикета" if getattr(job, "issue", None) is not None else "benchmark"
    return _KIND_NAME.get(what or "", "")


def _is_replay(job) -> bool:
    return "replay_bench.py" in (job.cmd or "") or any("replay_bench.py" in a for a in job.argv or ())


_REPLAY_STEM = re.compile(r"^(?P<slug>.+)-s(?P<seed>\d+)(?:-(?P<variant>no-.+))?$")  # replay_bench `_SOURCE_STEM`
_REPLAY_REF = re.compile(r"^  (\S+)\s+(FAILED\b|.* -> )")
_REPLAY_TAIL = re.compile(r"^\s+(FAILED\b|.* -> )")  # #1178: what follows a build's whole stem on its `.out` line
_REPLAY_DELTA = re.compile(r"^\s+([\d,.]+) -> ([\d,.]+) ([+-][\d.]+)%")  # #1178: applied to the tail after the whole stem
REPLAY_SEEN = CACHE_DIR / "replay_seen.json"


def _replay_seen(job_id: str, done: list[str]) -> dict:
    """When this collector first saw each finished build's line of a running replay (epoch s) = that build's end.
    Lines already there at the run's first sight get None (end unknown: the caller falls back to start + took)."""
    try:
        memo = json.loads(REPLAY_SEEN.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        memo = {}
    first = job_id not in memo
    mine = memo.setdefault(job_id, {})
    new = [ref for ref in done if ref not in mine]
    if first or new:
        for ref in new:
            mine[ref] = None if first else NOW.timestamp()
        memo = dict(list(memo.items())[-40:])
        try:
            REPLAY_SEEN.parent.mkdir(exist_ok=True)
            REPLAY_SEEN.write_text(json.dumps(memo), encoding="utf-8")
        except OSError:
            pass
    return mine


def replay_cells(job) -> dict | None:
    """#683 r5 (c): a replay_bench run's squares. One per delivered build of its `--builds` glob, in the script's own
    order (sorted paths); a build is done / failed once its line is in the job's `.out` (the script prints one as each
    build ends, `_DONE_LINE`). Its pool starts builds in that order, so the first `--workers` (default 5) unfinished
    ones of a running job are the ones being computed. No benchmark folder: no `dir`, so a press opens no PoB."""
    argv = _argv(job)
    pattern = _flag(argv, "--builds")
    if not pattern:
        return None
    paths = sorted({Path(q) for part in pattern.split(";") if part.strip()
                    for q in glob.glob(str(Path(part.strip()) if Path(part.strip()).is_absolute() else REPO / part.strip()),
                                       recursive=True) if q.endswith(".pob.txt")})
    if not paths:
        return None
    cells = []
    seed0 = _flag(argv, "--seed")  # #1178: a stem with no -s<seed> runs with the job's --seed
    job_seed = int(seed0) if seed0 and seed0.isdigit() else 1
    for p in paths:
        m = _REPLAY_STEM.match(p.name[: -len(".pob.txt")])
        slug = m["slug"] if m else p.name[: -len(".pob.txt")]
        cell = {"ref": slug, "name": words(slug), "seed": int(m["seed"]) if m else job_seed, "state": "waiting", **build_class(slug)}
        if m and m["variant"]:
            cell.update(variant=m["variant"], name=f"{words(slug)} · no {words(m['variant'][3:])}")
        cells.append(cell)
    out = Path(job.out) if getattr(job, "out", None) else None
    text = out.read_text(encoding="utf-8", errors="replace") if out and out.is_file() else ""
    if not text and getattr(job, "state", "") not in ("running", "queued"):
        return None  # ended without a line of output (cancelled before it started): it built nothing
    for line in text.splitlines():
        # #1178: a line belongs to the waiting cell whose WHOLE stem it starts with (a stem may hold spaces); the longest
        # stem is tried first, so `01 a b` is never taken by `01 a`
        hit = None
        if line.startswith("  "):
            for c in sorted((c for c in cells if c["state"] == "waiting"), key=lambda c: -len(c["ref"])):
                rest = line[2 + len(c["ref"]):] if line[2:].startswith(c["ref"]) else None
                if rest is not None and _REPLAY_TAIL.match(rest):
                    hit = (c, rest)
                    break
        if hit is None:
            continue
        c, rest = hit
        t = _REPLAY_TAIL.match(rest)
        m = _DONE_LINE.match(line)
        s = _done_s(m) if m else None
        c.update(state="failed" if t[1].startswith("FAILED") else "done", took=hd(s) if s else "")
        if s:
            c["_s"] = s
        d = _REPLAY_DELTA.match(rest)
        if d:  # the main stat before -> after: all a running replay has of a finished build (owner 10.10 02:1x)
            c["delta"] = f"{d[1]} -> {d[2]} ({d[3]} %)"
    if getattr(job, "state", "") == "running":
        pool = _flag(argv, "--workers")
        par = int(pool) if pool and pool.isdigit() else 5
        # #683 r5: a running build's start, rebuilt: the pool starts builds in path order, the first `par` at the
        # job's start, each later one when a build ends (the end = when this collector first saw its line, else
        # job start + its took for the first wave); its expected length = the median took of this run's done builds.
        t0 = parse_ts(job.start_ts).timestamp() if getattr(job, "start_ts", None) else None
        seen = _replay_seen(getattr(job, "id", "") or str(out), [c["ref"] for c in cells if c.get("_s")])
        ends = sorted(e for e in (seen.get(c["ref"]) or (t0 + c["_s"] if t0 and i < par else None)
                                  for i, c in enumerate(cells) if c.get("_s")) if e)
        took = sorted(c["_s"] for c in cells if c.get("_s"))
        for c in [c for c in cells if c["state"] == "waiting"][:par]:
            c["state"] = "running"  # no stage: the `.out` lines carry none
            k = cells.index(c)
            st = t0 if k < par else (ends[k - par] if k - par < len(ends) else None)
            if st:
                c["started_est"] = int(st)
            if took:
                c["expect_s"] = int(took[len(took) // 2])
    for c in cells:
        c.pop("_s", None)
        _stamp(c)
    done = sum(c["state"] in ("done", "failed") for c in cells)
    out_p = {"done": done, "total": len(cells), "total_open": False, "eta": None, "kind": "replay", "cells": cells}
    # #683 r5: an ended run's folder (its `report:` line names it inside a snapshot whose `artifacts` is a junction to
    # this host's own artifacts): results.json + builds/<reference>.xml, read by `build` for a square's stats panel.
    rep = next((ln[len("report: "):].strip() for ln in reversed(text.splitlines()) if ln.startswith("report: ")), None)
    if rep:
        d = REPO / "artifacts" / "replay" / Path(rep.replace("\\", "/")).parent.name
        if (d / "results.json").is_file():
            out_p["dir"] = str(d)
    return out_p


def _is_search(job) -> bool:
    return run_kind(job) == "request"


# scripts/search.py's own stdout lines (search.py `full_optimize_line`, the `  full` print, `say(... failed ...)`, the
# mutation round's `say`): the full builds it plans, each full build as it ends, the variants of its mutation round
_SEARCH_PLAN = re.compile(r"^full optimize: .* = (\d+) full builds\b")
_SEARCH_DONE = re.compile(r"^  full (\S+?)(?: seed (\d+))?: ")
_SEARCH_FAILED = re.compile(r"^- full optimize failed (\S+) seed (\d+): ")
_SEARCH_MUT = re.compile(r"^mutation round: (\d+) variants of the finished builds \((.*)\)\s*$")


def search_cells(job) -> dict | None:
    """#995 send-back 1 (defect 5: a finished `scripts/search.py` run showed an empty «билды»): a search run's builds,
    read off its `.out`. Total = the full builds its `full optimize:` line plans + the variants of its mutation round;
    a build is done / failed once its `  full` / `- full optimize failed` line is there; a planned mutation variant
    with no line yet waits. No such plan line yet (still screening, or an older run's log): None. No benchmark folder:
    no `dir`, so a press opens no PoB (as a replay's)."""
    out = Path(job.out) if getattr(job, "out", None) else None
    text = out.read_text(encoding="utf-8", errors="replace") if out and out.is_file() else ""
    total, cells = 0, {}
    for line in text.splitlines():
        if m := _SEARCH_PLAN.match(line):
            total += int(m[1])
        elif m := _SEARCH_MUT.match(line):
            total += int(m[1])
            for name in (n.strip() for n in m[2].split(",")):
                cells.setdefault((name, 1), "waiting")
        elif m := _SEARCH_DONE.match(line):
            cells[(m[1], int(m[2] or 1))] = "done"
        elif m := _SEARCH_FAILED.match(line):
            cells[(m[1], int(m[2]))] = "failed"
    if not total:
        return None
    out_cells = []
    for (ref, seed), state in cells.items():
        c = {"ref": ref, "name": ref, "seed": seed, "state": state}
        _stamp(c)
        out_cells.append(c)
    done = sum(c["state"] in ("done", "failed") for c in out_cells)
    return {"done": done, "total": max(total, len(out_cells)), "total_open": False, "eta": None, "cells": out_cells}


def run_cells(job) -> dict | None:
    if _is_replay(job):
        return replay_cells(job)
    if _is_search(job):
        return search_cells(job)
    d = job_dir(job)
    if d is None or not (d / "args.json").exists():
        return None
    args = json.loads((d / "args.json").read_text(encoding="utf-8"))
    seeds = [args.get("seed", 1) + i for i in range(args.get("seeds", 1))]
    slugs = args.get("slugs", [])
    argv = list(job.argv or job.cmd.split())
    cells, took = [], []
    for slug in slugs:
        for seed in seeds:
            cell = {"ref": slug, "name": words(slug), "seed": seed, "state": "waiting", **build_class(slug)}
            _fill_cell(cell, d, f"{slug}-s{seed}", took)
            cells.append(cell)
    # Variant rows (`<slug>-s<seed>-no-<name>`): on disk now, plus every planned one (variants.json).
    stems: dict[str, None] = {}
    planned_file = d / "variants.json"
    has_plan = planned_file.is_file()
    base_rows = base_done = None
    if has_plan:
        try:
            plan = json.loads(planned_file.read_text(encoding="utf-8"))
            for p in plan.get("planned", []):
                if p.get("stem"):
                    stems[p["stem"]] = None
            base_rows, base_done = plan.get("base_rows"), plan.get("base_done")
        except (ValueError, OSError, AttributeError):
            has_plan = False
    for sub, ext in (("rows", "json"), ("logs", "log")):
        for f in sorted((d / sub).glob(f"*.{ext}")):
            stems[f.stem] = None
    for stem in stems:
        m = VARIANT_RE.match(stem)
        if not m or m["slug"] not in slugs:
            continue
        cell = {"ref": m["slug"], "name": f"{words(m['slug'])} · no {words(m['name'])}", "seed": int(m["seed"]),
                "variant": f"no-{m['name']}", "state": "queued", **build_class(m["slug"])}
        _fill_cell(cell, d, stem, took)
        cells.append(cell)
    done = sum(c["state"] in ("done", "failed") for c in cells)
    # #580 rule 3: a base row still running may add keystone rows; once every base row ended the plan is whole.
    if has_plan:
        if base_rows is None or base_done is None:
            base_rows = len(slugs) * len(seeds)
            base_done = sum(c["state"] in ("done", "failed") for c in cells[:base_rows])
        total_open = base_done < base_rows
    else:
        total_open = True
    total_open = total_open and getattr(job, "state", "running") == "running"
    for c in cells:
        _stamp(c)
    return {"done": done, "total": len(cells), "total_open": total_open, "eta": None, "dir": str(d), "cells": cells}


HISTORY_CACHE = CACHE_DIR / "history.json"


def _local(ts: str | None) -> datetime | None:
    t = parse_ts(ts)
    return t.astimezone() if t else None


def _history_counts(jobs: list) -> dict[str, dict]:
    """Rows done / total of every finished run whose folder exists. A finished run never changes,
    so its count is read once (run_cells) and kept in HISTORY_CACHE by job id; later pulls only
    check that the folder is still there."""
    try:
        cache = json.loads(HISTORY_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    out, changed = {}, False
    for j in jobs:
        if _is_replay(j) or _is_search(j):
            # #683 r5 (c): a finished replay run's squares come from its `.out`, which never changes once it ended;
            # #995: so do a finished search run's (search_cells)
            c = cache.get(j.id)
            if c is None or c.get("out") != j.out:
                p = run_cells(j)
                c = cache[j.id] = {"dir": None, "out": j.out, **({"done": p["done"], "total": p["total"]} if p else {})}
                changed = True
            if c.get("total"):
                out[j.id] = c
            continue
        if "benchmark.py" not in (j.cmd or ""):
            continue
        c = cache.get(j.id)
        if c is not None and c.get("dir") is None:
            continue  # no folder when it ended: a folder never comes back
        if c and (Path(c["dir"]) / "args.json").is_file():
            out[j.id] = c
            continue
        p = run_cells(j)
        cache[j.id] = {"dir": None} if p is None else {"dir": p["dir"], "done": p["done"], "total": p["total"]}
        if p is not None:
            out[j.id] = cache[j.id]
        changed = True
    if changed:
        HISTORY_CACHE.parent.mkdir(exist_ok=True)
        tmp = HISTORY_CACHE.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(cache), encoding="utf-8")
        os.replace(tmp, HISTORY_CACHE)
    return out


def daemon_slots() -> dict | None:
    """#622: this machine's runs daemon status (`daemon-<host>.json`, the freshest of the two: the
    PC also keeps an old laptop copy), cut to the owner's reservation fields (#621) and the age of
    its last tick. A field the daemon does not write yet comes back None."""
    best = None
    for path in (REPO / "artifacts" / "runs").glob("daemon-*.json"):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        tick = parse_ts(str(d.get("last_tick") or ""))
        if tick and (best is None or tick > best[0]):
            best = (tick, d)
    if best is None:
        return None
    tick, d = best
    return {"host": d.get("host"), "age_s": max(0, round((NOW - tick).total_seconds())), "pid": d.get("pid"),
            **{k: d.get(k) for k in ("slots_total", "slots_in_use", "reserved", "reserved_until")}}


def daemon_waits(host: str) -> dict:
    """#706: why each queued job of `host` did not start at the daemon's last step: `waits` of
    `daemon-<host>.json` = {job id: {kind, text, host_fixed}}. A daemon that does not write it yet: {}."""
    try:
        d = json.loads((REPO / "artifacts" / "runs" / f"daemon-{host}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    w = d.get("waits") if isinstance(d, dict) else None
    return {k: v for k, v in w.items() if isinstance(v, dict) and v.get("text")} if isinstance(w, dict) else {}


# ---- #699: how long a job still takes (running) or will take (queued), from what is already measured, and when
# the queue ends. `how`: `rate` = this run's own finished builds, `against` = the per-build time of the replay it is
# compared with, `history` = past builds of the same slug / past runs of the same command; None = nothing to go on.
BENCH_ROOT = REPO / "artifacts" / "benchmark"
REPLAY_ROOT = REPO / "artifacts" / "replay"
EST_CACHE = CACHE_DIR / "estimates.json"
# a replay's `.out` line per finished build: `  <reference> <before> -> <after> <gain> <human duration>` or FAILED
_DONE_LINE = re.compile(r"^  \S+\s+(?:FAILED\b.*|.* -> .*?(?:(\d+) h (\d+) min|([\d.]+) min|([\d.]+) s))\s*$")
_KEY_SKIP = ("--tag", "--against", "--workers", "--record-calls")
PRIO = ("P0", "P1", "P2")  # the store's order (`store.PRIORITIES`)


def _argv(j) -> list[str]:
    return list(j.argv or (j.cmd or "").split())


def _flag(argv: list[str], name: str) -> str | None:
    i = argv.index(name) + 1 if name in argv else 0
    return argv[i] if 0 < i < len(argv) else None


def _cmd_key(j) -> str:
    """The command with the flags that do not change its work (tag, against, workers) left out."""
    out, skip = [], False
    for a in _argv(j):
        if skip:
            skip = False
        elif a in _KEY_SKIP:
            skip = True
        else:
            out.append(a)
    return " ".join(out)


def _history_s(j, jobs) -> float | None:
    """Median run time of the past `done` jobs of the same command."""
    key = _cmd_key(j)
    took = [(parse_ts(x.end_ts) - parse_ts(x.start_ts)).total_seconds() for x in jobs
            if x.id != j.id and x.state == "done" and x.start_ts and x.end_ts and _cmd_key(x) == key]
    return statistics.median(took) if took else None


class _Memo:
    """Slow lookups (a 2.7 MB results.json, the benchmark history scan) kept in a file between pulls: a file's
    value by its mtime, a history value for 30 min."""

    def __init__(self):
        try:
            self.d = json.loads(EST_CACHE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.d = {}
        self.changed = False

    def get(self, key: str, stamp: float, make):
        hit = self.d.get(key)
        if hit and hit[0] == stamp:
            return hit[1]
        val = make()
        self.d[key] = [stamp, val]
        self.changed = True
        return val

    def save(self):
        if not self.changed:
            return
        EST_CACHE.parent.mkdir(exist_ok=True)
        tmp = EST_CACHE.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(self.d), encoding="utf-8")
        os.replace(tmp, EST_CACHE)


def _replay_against(ref: str, memo: _Memo) -> tuple[dict[str, float], float] | None:
    """What one ok build took in a replay given as a folder, a results.json or a tag: ({reference: seconds}, the
    median seconds of one build)."""
    p = Path(ref)
    p = p if p.is_absolute() else REPO / p
    if p.is_dir():
        p = p / "results.json"
    if not p.is_file():
        found = sorted(REPLAY_ROOT.glob(f"*-{ref}/results.json"))
        if not found:
            return None
        p = found[-1]

    def read():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        rows = raw.get("rows") if isinstance(raw, dict) else raw
        ok = [r for r in rows or [] if isinstance(r, dict) and r.get("ok") and r.get("seconds")]
        if not ok:
            return None
        return [{str(r["reference"]): float(r["seconds"]) for r in ok if r.get("reference")},
                statistics.median(float(r["seconds"]) for r in ok)]
    try:
        got = memo.get(f"replay:{p}", p.stat().st_mtime, read)
    except OSError:
        return None
    return (got[0], got[1]) if got else None


def _done_s(m: re.Match) -> float | None:
    h, hm, mins, s = m.groups()
    if h:
        return int(h) * 3600 + int(hm) * 60
    if mins:
        return float(mins) * 60
    return float(s) if s else None


# #985: one pool model for both kinds of run, measured on the finished runs of bin/estimate_table_985.md. A build still
# running needs at least a share of its expected length and at least a quarter of the time it has already taken: build
# lengths have a heavy tail, one that outlived its expectation is not nearly done (the old `max(per - since, 5 %)`
# said "27 s left" where 27 min were left).
_REM_FLOOR, _REM_LINDY = 0.05, 0.25


def _remaining(expect: float, age: float) -> float:
    return max(expect - age, _REM_FLOOR * expect, _REM_LINDY * age)


def _pool_end(running_rem: list[float], waiting: list[float], workers: int) -> float:
    """Seconds until a pool of `workers` has run out of work: each running build needs `running_rem`, the builds not
    started (`waiting`, in start order) each go to the worker that frees first."""
    free = list(running_rem) + [0.0] * max(0, workers - len(running_rem))
    heapq.heapify(free)
    for e in waiting:
        heapq.heappush(free, heapq.heappop(free) + e)
    return max(free) if free else 0.0


def _replay_out_lines(out: Path) -> list[tuple[str, float | None]]:
    """(reference, seconds or None for a FAILED line) per finished build in a replay's `.out`, in the file's order."""
    got = []
    for line in out.read_text(encoding="utf-8", errors="replace").splitlines():
        r = _REPLAY_REF.match(line)
        if r:
            m = _DONE_LINE.match(line)
            got.append((r[1], _done_s(m) if m else None))
    return got


def _replay_key(j) -> tuple:
    a = _argv(j)
    return _flag(a, "--builds"), _flag(a, "--move"), _flag(a, "--passes")


def _replay_prior(j, jobs, memo: _Memo) -> tuple[dict[str, float], float | None, str | None]:
    """What each reference took when the same builds were replayed before: ({reference: seconds}, the median of those,
    how it was known). The newest finished replay of the same builds, move and passes (its `.out`), then the
    `--against` replay's own results (per reference) over it."""
    argv = _argv(j)
    per: dict[str, float] = {}
    base, how = None, None
    start = parse_ts(j.start_ts) if getattr(j, "start_ts", None) else None
    key = _replay_key(j)
    same = [x for x in jobs if x.id != j.id and x.state == "done" and x.out and x.end_ts and _is_replay(x)
            and _replay_key(x) == key and (start is None or parse_ts(x.end_ts) <= start)]
    for x in sorted(same, key=lambda x: parse_ts(x.end_ts), reverse=True)[:3]:
        try:
            got = memo.get(f"replay-out:{x.out}", Path(x.out).stat().st_mtime,
                           lambda x=x: {r: s for r, s in _replay_out_lines(Path(x.out)) if s})
        except OSError:
            continue
        if got:
            per, how = dict(got), "history"
            break
    if _flag(argv, "--against"):
        ag = _replay_against(_flag(argv, "--against"), memo)
        if ag:
            per, base, how = {**per, **ag[0]}, ag[1], "against"
    if per and base is None:
        base = statistics.median(per.values())
    return per, base, how


def _replay_est(j, par: int, memo: _Memo, jobs=()) -> tuple[float, str] | None:
    """Seconds still to go of a running replay / the whole run time of a queued one. The pool is rebuilt from the
    `.out`: builds start in sorted path order, the first `--workers` at the job's start, each later one when a worker
    frees, so the unfinished builds that have started are the running ones and each one's age is known. A build is
    expected to take what its reference took in the earlier replay of the same builds, scaled by how this run's
    finished builds compare with that (a run on a busier machine is slower); no earlier replay: the mean of this run's
    finished builds."""
    argv = _argv(j)
    pattern = _flag(argv, "--builds")
    if not pattern:
        return None
    paths = sorted({q for part in pattern.split(";") if part.strip()
                    for q in glob.glob(str(Path(part.strip()) if Path(part.strip()).is_absolute() else REPO / part.strip()), recursive=True)})
    n = len(paths)
    if not n:
        return None
    pool = _flag(argv, "--workers")
    size = int(pool) if pool and pool.isdigit() else 5
    par = max(1, min(par, size))
    refs = []
    for q in paths:
        stem = Path(q).name[: -len(".pob.txt")] if q.endswith(".pob.txt") else Path(q).stem
        m = _REPLAY_STEM.match(stem)
        refs.append(m["slug"] if m else stem)
    live = j.state == "running"
    out = Path(j.out) if j.out else None
    lines = _replay_out_lines(out) if live and out and out.is_file() else []
    took: dict[int, float | None] = {}
    for ref, s in lines:
        i = next((k for k in range(n) if k not in took and refs[k] == ref), None)
        if i is None:
            i = next((k for k in range(n) if k not in took), None)
        if i is not None:
            took[i] = s
    now = time.time()
    st = parse_ts(j.start_ts) if getattr(j, "start_ts", None) else None
    t0 = min(st.timestamp(), now) if st else now
    free = [t0] * min(size, n)
    heapq.heapify(free)
    started: dict[int, float] = {}
    for i in range(n):
        if not free:
            break
        f = heapq.heappop(free)
        if i in took:
            heapq.heappush(free, f + (took[i] or 0.0))
        elif live:
            started[i] = min(f, now)
        else:
            break
    waiting = [i for i in range(n) if i not in took and i not in started]
    got = [s for s in took.values() if s]
    if not started and not waiting:
        return 0.0, "rate"
    prior, base, how = _replay_prior(j, jobs, memo)
    pairs = [(took[i], prior[refs[i]]) for i in took if took[i] and refs[i] in prior]
    scale = min(3.0, max(0.3, sum(a for a, _ in pairs) / sum(b for _, b in pairs))) if pairs else 1.0

    def expect(i: int) -> float | None:
        if refs[i] in prior:
            return scale * prior[refs[i]]
        if base:
            return scale * base
        return statistics.mean(got) if got else None
    exp = {i: expect(i) for i in [*started, *waiting]}
    if any(e is None for e in exp.values()):
        return None
    rem = [_remaining(exp[i], now - t) for i, t in started.items()]
    return _pool_end(rem, [exp[i] for i in waiting], par), "rate" if got else how


def _bench_est(p: dict, par: int, memo: _Memo) -> tuple[float, str] | None:
    """Seconds still to go of a benchmark run: each unfinished cell is expected to take what builds of its slug took in
    this run, else in the newest earlier run of the same loop budget and kind (construction-only or full), scaled by
    how this run's finished builds compare with those; a slug nobody built: the mean of this run's finished builds, else
    the weekly run's median. A running cell needs what is left of its expectation (`_remaining`)."""
    from junkroan.runs import build_estimate as be
    cells = p.get("cells") or []
    left = [c for c in cells if c["state"] not in ("done", "failed")]
    if not left:
        return (0.0, "rate") if cells else None
    d = Path(p["dir"])
    try:
        args = json.loads((d / "args.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, AttributeError):
        args = {}
    loop, cons = args.get("loop_seconds"), bool(args.get("construction_only"))
    rows = be.finished_rows(d)
    own: dict[str, list[float]] = {}
    for slug, s in rows:
        own.setdefault(slug, []).append(s)
    now = time.time()
    hist: dict[str, float | None] = {}

    def history(slug: str) -> float | None:
        if slug not in hist:
            hist[slug] = memo.get(f"bench:{slug}:{loop}:{cons}", int(now // 1800),
                                  lambda: be.history_seconds(slug, loop, BENCH_ROOT, cons))
        return hist[slug]
    pairs = [(s, history(slug)) for slug, ss in own.items() for s in ss if history(slug)]
    scale = min(3.0, max(0.3, sum(a for a, _ in pairs) / sum(b for _, b in pairs))) if pairs else 1.0
    mean_own = statistics.mean(s for _, s in rows) if rows else None

    def expect(slug: str) -> float:
        if own.get(slug):
            return statistics.median(own[slug])
        if history(slug):
            return history(slug) * scale
        if mean_own:
            return mean_own
        return memo.get(f"bench-weekly:{slug}:{loop}", int(now // 1800), lambda: be.estimate_build(slug, d, loop, BENCH_ROOT)[0])
    exp = {slug: expect(slug) for slug in {c["ref"] for c in left}}
    running = [c for c in left if c["state"] == "running" and c.get("started")]
    rem = [_remaining(exp[c["ref"]], now - c["started"]) for c in running]
    waiting = [exp[c["ref"]] for c in left if c not in running]
    return _pool_end(rem, waiting, par), "rate" if rows else "history"


def estimate(j, jobs, progress: dict | None, par: int, memo: _Memo) -> tuple[float | None, str | None]:
    """(seconds still to go for a running job / its whole run time for a queued one, how it was known)."""
    est = None
    if _is_replay(j):
        est = _replay_est(j, par, memo, jobs)
    elif progress:
        est = _bench_est(progress, par, memo)
    if est:
        return est
    h = _history_s(j, jobs)
    if h is None:
        return None, None
    if j.state == "running":
        st = parse_ts(j.start_ts)
        return max(0.0, h - ((NOW - st).total_seconds() if st else 0.0)), "history"
    return h, "history"


def plan_queue(running: list[dict], queued: list[dict], capacity: dict[str, int]) -> tuple[float, bool]:
    """When each queued job starts (`start_s` from now) and the queue's end: (seconds from now of the last known
    end, True when some job has no estimate so the real end is later). Per host: a job takes its `workers` slots once that many are free, in the store's order
    (priority, then submit); one with `--after` waits for those to end too."""
    ends: dict[str, float | None] = {r["id"]: r.get("left_s") for r in running}
    last = 0.0
    unknown = any(r.get("left_s") is None for r in running)
    for host in {r["host"] for r in running + queued}:
        frees = sorted(((r["left_s"], r.get("locks") or r["workers"]) for r in running
                        if r["host"] == host and r.get("left_s") is not None), key=lambda x: x[0])
        cap = max(capacity.get(host, 0), sum((r.get("locks") or r["workers"]) for r in running if r["host"] == host),
                  max([q["workers"] for q in queued if q["host"] == host] or [1]))
        free = cap - sum((r.get("locks") or r["workers"]) for r in running if r["host"] == host)
        t, blocked = 0.0, False
        for q in [q for q in queued if q["host"] == host]:
            need = min(q["workers"], cap)
            while free < need and frees:
                at, n = frees.pop(0)
                t, free = max(t, at), free + n
            deps = [ends[a] for a in q.get("after", []) if a in ends]  # a predecessor not live has ended
            if blocked or free < need or q.get("takes_s") is None or any(e is None for e in deps):
                blocked = True
                ends[q["id"]] = None
                continue
            start = max([t] + [e for e in deps if e is not None])
            q["start_s"] = start
            free -= need
            frees.append((start + q["takes_s"], need))
            frees.sort(key=lambda x: x[0])
            ends[q["id"]] = start + q["takes_s"]
        unknown = unknown or blocked
    known = [e for e in ends.values() if e is not None]
    return (max(known) if known else 0.0), unknown


def runs(history: bool = True) -> dict:
    from junkroan.pob import slot_budget
    from junkroan.runs.store import DEFAULT_LOG, TERMINAL_STATES, Store

    budget = slot_budget.load_budget()
    folder = slot_budget.slot_dir()
    busy = slot_budget.busy_slots(folder, budget=budget)
    jobs = Store(DEFAULT_LOG).jobs()

    def row(j, age):
        # Table columns (#587): date and start in local time; `dur` = the run time (a running job: so
        # far), or the wait of a queued one.
        start, submit, end = _local(j.start_ts), _local(j.submit_ts), _local(j.end_ts)
        first = start or submit
        what = run_kind(j)
        r = {"id": j.id, "tag": j.tag, "name": words(j.tag.replace("-", "_")), "issue": j.issue,
             "priority": j.priority, "host": j.host, "workers": j.workers, "state": j.state, "age": age,
             "date": first.strftime("%d.%m") if first else "", "start": start.strftime("%H:%M") if start else "",
             "bench": "benchmark.py" in (j.cmd or ""), "what": what, "kind_name": kind_name(what, j),
             "end": j.end_ts or j.start_ts or j.submit_ts or ""}
        if start:
            r["dur"] = hd(((end or NOW.astimezone()) - start).total_seconds())
        elif submit and j.state == "queued":
            r["dur"] = hd((NOW.astimezone() - submit).total_seconds())
        return r

    running = []
    for j in jobs:
        if j.state != "running":
            continue
        r = row(j, hd((NOW - parse_ts(j.start_ts)).total_seconds()) if j.start_ts else "")
        r["progress"] = run_cells(j)
        # The slots it holds now: the daemon widens a lone job past its submitted `workers` (#570;
        # P1-#600 on 09.10: workers 1, locks 5), so a running row shows its locks, not the ask.
        r["locks"] = sum(1 for s in busy if s.get("job") == j.id)
        running.append(r)
    queued = [row(j, hd((NOW - parse_ts(j.submit_ts)).total_seconds())) for j in jobs if j.state == "queued"]
    ended = sorted((j for j in jobs if j.state in TERMINAL_STATES),
                   key=lambda j: j.end_ts or j.start_ts or j.submit_ts or "")
    last = [j for j in ended if j.end_ts][-8:]
    # #683 r5: builds done / total of a finished run; the laptop sends only `recent` (no history), so those rows
    # carry their count too (the PC merges them into its History)
    counts = _history_counts(ended if history else last)

    def counted(r, j):
        c = counts.get(j.id)
        if c:
            r["rows_done"], r["rows_total"] = c["done"], c["total"]
        elif r["bench"] and j.start_ts:
            r["gone"] = True
        return r

    recent = []
    for j in reversed(last):
        r = row(j, hd((NOW - parse_ts(j.end_ts)).total_seconds()))
        if j.start_ts:
            r["took"] = hd((parse_ts(j.end_ts) - parse_ts(j.start_ts)).total_seconds())
        recent.append(counted(r, j))
    # #699: every live job's estimate, the queued ones' starts, the queue's end
    by_id = {j.id: j for j in jobs}
    memo = _Memo()
    for r in running:
        try:
            left, how = estimate(by_id[r["id"]], jobs, r.get("progress"), r["locks"] or r["workers"], memo)
        except Exception:  # an estimate never breaks the card
            left, how = None, None
        r.update(left_s=None if left is None else round(left), left_h=hd(left) if left is not None else "", est=how)
        if left is not None and r.get("progress"):  # #985: the clock time the laptop verdict and the status line read
            r["progress"]["eta"] = datetime.fromtimestamp(time.time() + left).strftime("%H:%M")
    queued.sort(key=lambda q: (PRIO.index(q["priority"]) if q["priority"] in PRIO else 9, by_id[q["id"]].submit_ts or ""))
    for q in queued:
        j = by_id[q["id"]]
        try:
            takes, how = estimate(j, jobs, None, j.workers or 1, memo)
        except Exception:
            takes, how = None, None
        q.update(takes_s=None if takes is None else round(takes), takes_h=hd(takes) if takes is not None else "", est=how,
                 after=list(j.after))
    waits = daemon_waits(slot_budget.current_host()) if queued else {}
    for q in queued:
        w = waits.get(q["id"])
        if w:
            q["wait"] = {"kind": str(w.get("kind") or ""), "text": str(w["text"])}
            q["host_fixed"] = bool(w.get("host_fixed"))
    # #863: a queued job whose `--after` predecessor ended failed can never start: name that predecessor (a stopped or
    # cancelled one is a deliberate stop, the anomaly's own rule, anomalies.detect_held_by_failed_predecessor)
    for q in queued:
        for a in q.get("after", []):
            p = by_id.get(a)
            if p is not None and p.state == "failed":
                q["held_by"] = {"id": p.id, "tag": p.tag}
                break
    # #1106: a queued job (no `held_by`) that waits for an `--after` predecessor still running or queued is named by that
    # predecessor's tag, the run's name the monitor prints (never a job id); a predecessor done or unknown is passed over
    for q in queued:
        if "held_by" in q:
            continue
        for a in q.get("after", []):
            p = by_id.get(a)
            if p is not None and p.state in ("queued", "running"):
                q["waits_for"] = {"tag": p.tag}
                break
    memo.save()
    cap = {slot_budget.current_host(): budget.limit_for(slot_budget.ROLE_QUEUE)}
    end_s, end_unknown = plan_queue(running, queued, cap)
    for q in queued:
        if q.get("start_s") is not None:
            q["start_h"] = hd(q["start_s"])
    at = lambda s: datetime.fromtimestamp(time.time() + s).strftime("%H:%M")
    queue_until = at(end_s) if (running or queued) and end_s else None
    out = {
        "queue_end_s": round(end_s) if (running or queued) else None, "queue_end_h": hd(end_s) if (running or queued) and end_s else "",
        "queue_end_partial": end_unknown,
        "period": budget.period, "total": budget.total, "others": budget.others,
        "slots": [{"slot": s["slot"], "role": s.get("role", "?"), "pid": s.get("pid"),
                   "age": hd(s.get("age_seconds"))} for s in busy],
        "waiting": len(slot_budget.waiting(folder)),
        "running": running, "queued": queued, "recent": recent, "queue_until": queue_until,
        "daemon": daemon_slots(),
    }
    if history:
        # #587: every finished run of the store, newest first; its squares come on a click (`cells`).
        out["history"] = [counted(row(j, ""), j) for j in reversed(ended)]
    return out


def cells(job_id: str, here: str = "") -> dict:
    """The squares of one run, live or finished (#587), on a click in the runs card. A run the PC
    queue does not hold is asked of the laptop's own queue (#667); `here` stops that hop there."""
    from junkroan.runs.store import DEFAULT_LOG, Store

    job = next((j for j in Store(DEFAULT_LOG).jobs() if j.id == job_id), None)
    if job is None and not here:
        try:
            res = subprocess.run(["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "laptop", "python", "-",
                                  "cells", job_id, "here"], input=remote_program(),
                                 capture_output=True, text=True, encoding="utf-8", timeout=30, creationflags=NO_WINDOW)
            if res.returncode == 0:
                return json.loads(res.stdout)
        except (subprocess.TimeoutExpired, ValueError):
            pass
    if job is None:
        return {"error": f"нет рана {job_id} в очереди"}
    p = run_cells(job)
    if p is None:
        return {"gone": "benchmark.py" in (job.cmd or "") and bool(job.start_ts)}
    return {"progress": p}


# ================================================================ this machine alone (`host` mode, run locally or on the laptop)

def host(*_flags) -> dict:
    """This machine alone: load split, slots, live jobs. Run locally or on the laptop over ssh (`here`: the laptop's
    pipe is cp1252, so its JSON must be ASCII; a variant row's `·` made the PC's utf-8 read fail, #984)."""
    out: dict = {}
    try:
        r = runs(history=False)
        out["runs"] = r
        out["machine"] = machine(*machine_pids(SimpleNamespace(sections={"runs": r})),
                                 work_key=WORK_KEY, work_prefix=WORK_PREFIX)
    except Exception as exc:  # noqa: BLE001
        out["error"] = repr(exc)[:200]
    return out


# ================================================================ laptop

LAPTOP_CACHE = CACHE_DIR / "laptop.json"
DAEMON_ERR = REPO / "artifacts" / "runs" / "daemon-pc.err"
#: The PC daemon tries the laptop about once a minute; failures further apart than this are two outages.
STREAK_GAP = 300


def lost_at(seen: datetime | None) -> datetime | None:
    """When the current outage began: the first failed laptop pass of the PC daemon's latest streak
    (`daemon-pc.err`, local time) after `seen` (the monitor's own last good reading), or None when
    its last failure is older than STREAK_GAP or came before `seen` (the link is back since)."""
    try:
        with DAEMON_ERR.open("rb") as fh:
            fh.seek(max(0, DAEMON_ERR.stat().st_size - 400_000))
            tail = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    stamps = []
    for line in tail.splitlines():
        if "laptop unreachable" in line or "laptop queue unreadable" in line:
            try:
                stamps.append(datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S").astimezone())
            except ValueError:
                pass
    if seen:
        stamps = [t for t in stamps if t > seen]
    if not stamps or (NOW - stamps[-1]).total_seconds() > STREAK_GAP:
        return None
    start = stamps[-1]
    for t in reversed(stamps[:-1]):
        if (start - t).total_seconds() > STREAK_GAP:
            break
        start = t
    return start


def offline(cache: dict | None) -> dict:
    """What the owner needs while the laptop cannot be reached: since when, what ran there at the
    last contact, until when it works on its own (its daemon runs its queue without the PC), and
    when the link must be back (hand-backs to tickets, its keymasters, new jobs from the PC)."""
    now = NOW.astimezone()
    out: dict = {}
    seen = parse_ts(cache.get("at")) if cache else None
    lost = lost_at(seen)
    if lost:
        out["lost"] = lost.strftime("%H:%M")
        out["lost_ago"] = hd((now - lost).total_seconds())
    if seen:
        seen = seen.astimezone()
        out["seen"] = seen.strftime("%H:%M") if seen.date() == now.date() else seen.strftime("%d.%m %H:%M")
        out["seen_ago"] = hd((now - seen).total_seconds())
    data = (cache or {}).get("data") or {}
    # The card keeps the machine's shape while it is out of reach: its cores and slots as last seen.
    if (data.get("machine") or {}).get("cores"):
        out["cores"] = data["machine"]["cores"]
    if (data.get("runs") or {}).get("total") is not None:
        out["slots_total"] = data["runs"]["total"]
    r = data.get("runs")
    if seen is None or r is None:
        out["verdict"] = "что было запущено на ноуте, монитор не застал"
        out["restore"] = "сейчас"
        return out
    out["running"] = [{"tag": j["tag"], "workers": j.get("workers"),
                       "done": (j.get("progress") or {}).get("done"), "total": (j.get("progress") or {}).get("total"),
                       "eta": (j.get("progress") or {}).get("eta")} for j in r.get("running", [])]
    out["queued"] = len(r.get("queued", []))
    ends = []
    for j in out["running"]:
        if not j["eta"]:
            ends = None
            break
        hh, mm = map(int, j["eta"].split(":"))
        end = seen.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if end < seen - timedelta(minutes=1):
            end += timedelta(days=1)
        ends.append(end)
    queued = f"; в очереди {out['queued']}: стартуют сами, конец не оценить" if out["queued"] else ""
    if not out["running"] and not out["queued"]:
        out["verdict"] = "ноут был пустой: связь нужна, только чтобы дать ему работу"
        out["restore"] = "когда понадобится ноут"
    elif not out["running"]:
        out["verdict"] = f"ранов не было{queued}"
        out["restore"] = "сейчас (результаты в тикет приходят только по связи)"
    elif ends is None:
        out["verdict"] = f"раны идут сами, конец не оценить{queued}"
        out["restore"] = "сейчас"
    else:
        until = max(ends)
        if until > now and not out["queued"]:
            out["verdict"] = f"работает само до ~{until:%H:%M}: раны идут без связи"
            out["restore"] = f"к ~{until:%H:%M} (тогда hand-back в тикет)"
        elif until > now:
            out["verdict"] = f"раны идут сами до ~{until:%H:%M}{queued}"
            out["restore"] = f"к ~{until:%H:%M} (тогда hand-back в тикет)"
        else:
            out["verdict"] = f"по оценке раны кончились к ~{until:%H:%M}{queued}"
            out["restore"] = "сейчас: результаты ждут связи"
    return out


def merge_laptop(r: dict, lap: dict) -> None:
    """#667: the laptop runs its own daemon and store (#647/#648), so its runs never reach the PC
    queue; the runs card gets them from the laptop's reading: running and queued rows appended,
    its latest finished rows merged into History by end time. A laptop out of reach keeps its last
    known running and queued rows, marked `stale`."""
    lr = (lap or {}).get("runs")
    if (lap or {}).get("error"):
        # #683 r5: the link is down, the laptop's daemon goes on by itself: its running and queued rows stay as
        # last read, marked `stale` with the time of that reading, until the laptop answers again.
        last = lap.get("last") or {}
        since = (lap.get("offline") or {}).get("seen")
        for k in ("running", "queued"):
            r[k] = r[k] + [dict(j, stale=True, stale_since=since) for j in last.get(k, [])]
        return
    if not lr:
        return
    r["running"] = r["running"] + lr.get("running", [])
    r["queued"] = r["queued"] + lr.get("queued", [])
    if "history" in r:
        r["history"] = sorted(r["history"] + lr.get("recent", []), key=lambda x: x.get("end") or "", reverse=True)


LAPTOP_EVERY = 25   # a good reading younger than this is reused: one ssh per ~25 s, not per 5-s pull
LAPTOP_BACKOFF = 60  # after a failed ssh no new attempt for this long (a dead link cost 5-25 s a pull)
LAPTOP_WAIT = 2.0    # #984: the most one pull waits for ssh; a slower answer is picked up by a later pull
LAPTOP_PENDING_MAX = 30  # an ssh still silent after this long counts as a failed reading
#: `here` = ASCII JSON (the laptop's pipe is cp1252); the keep-alive flags end an ssh whose link died by itself.
LAPTOP_SSH = ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "ServerAliveInterval=5",
              "-o", "ServerAliveCountMax=3", "laptop", "python", "-", "host", "here"]


def last_runs(cache: dict | None) -> dict:
    """The laptop's running and queued rows as of its last good reading (shown faded while the link is down)."""
    r = ((cache or {}).get("data") or {}).get("runs") or {}
    return {"running": r.get("running", []), "queued": r.get("queued", [])}


def _age_fields(cache: dict | None) -> dict:
    """How old the last good reading is: `age_s` (seconds, None = never read) and `age` for a human."""
    at = parse_ts((cache or {}).get("at"))
    if at is None:
        return {"age_s": None, "age": ""}
    s = max(0, int((NOW - at).total_seconds()))
    return {"age_s": s, "age": hd(s)}


def _stamped(cache: dict) -> dict:
    return {**cache["data"], **_age_fields(cache)}


def _down(cache: dict | None, why: str) -> dict:
    return {"error": why, "offline": offline(cache), "last": last_runs(cache), **_age_fields(cache)}


def _save(cache: dict) -> None:
    LAPTOP_CACHE.parent.mkdir(exist_ok=True)
    LAPTOP_CACHE.write_text(json.dumps(cache), encoding="utf-8")


def _answer(path: Path):
    """The laptop's JSON from the file ssh writes to, or None while it is not whole yet."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def laptop() -> dict:
    """`host here` on the laptop: this very file piped to `ssh laptop python - host here`. A good reading is
    kept in LAPTOP_CACHE (`at`, `data`) and reused for LAPTOP_EVERY; a failure is stamped there too
    (`failed_at`, `error`) and holds ssh off for LAPTOP_BACKOFF; without the link the pane shows
    `offline` built from the last good reading instead of ssh's own words.

    #984: one pull waits LAPTOP_WAIT for ssh at most. A slower ssh keeps running on its own, writing to a file next
    to the cache (`pending` in the cache names it); the next pulls return the last good data (`age_s`, `age`
    say how old) until that file holds the whole answer, or LAPTOP_PENDING_MAX passes and the reading failed."""
    try:
        cache = json.loads(LAPTOP_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = None
    good_at = parse_ts((cache or {}).get("at"))
    fail_at = parse_ts((cache or {}).get("failed_at"))
    if good_at and (fail_at is None or fail_at < good_at) and (NOW - good_at).total_seconds() < LAPTOP_EVERY:
        return _stamped(cache)
    if fail_at and (good_at is None or good_at < fail_at) and (NOW - fail_at).total_seconds() < LAPTOP_BACKOFF:
        return _down(cache, cache.get("error") or "ssh")
    out_file = LAPTOP_CACHE.with_suffix(".out")
    pending = (cache or {}).get("pending")
    why = None
    if pending:
        data = _answer(out_file)
        if data is not None:
            cache = {"at": NOW.isoformat(), "data": data}
            _save(cache)
            return _stamped(cache)
        started = parse_ts(pending.get("at"))
        if started and (NOW - started).total_seconds() < LAPTOP_PENDING_MAX:
            return _stamped(cache) if (cache.get("data")) else _down(cache, "ssh pending")
        why = "ssh timeout"
    else:
        LAPTOP_CACHE.parent.mkdir(exist_ok=True)
        prog_file = LAPTOP_CACHE.with_suffix(".prog")
        prog_file.write_text(remote_program(), encoding="utf-8")
        with prog_file.open("rb") as fin, out_file.open("wb") as fout,                 LAPTOP_CACHE.with_suffix(".err").open("wb") as ferr:
            proc = subprocess.Popen(LAPTOP_SSH, stdin=fin, stdout=fout, stderr=ferr, creationflags=NO_WINDOW)
        try:
            rc = proc.wait(timeout=LAPTOP_WAIT)
        except subprocess.TimeoutExpired:
            _save({**(cache or {}), "pending": {"at": NOW.isoformat(), "pid": proc.pid}})
            return _stamped(cache) if (cache or {}).get("data") else _down(cache, "ssh pending")
        data = _answer(out_file) if rc == 0 else None
        if data is not None:
            cache = {"at": NOW.isoformat(), "data": data}
            _save(cache)
            return _stamped(cache)
        try:
            err = LAPTOP_CACHE.with_suffix(".err").read_text(encoding="utf-8", errors="replace")
        except OSError:
            err = ""
        why = (err.strip().splitlines() or [f"ssh rc {rc}"])[-1][:200] if rc else "ssh answer unreadable"
    cache = {k: v for k, v in {**(cache or {}), "failed_at": NOW.isoformat(), "error": why}.items() if k != "pending"}
    _save(cache)
    return _down(cache, why)


# ================================================================ readings

READINGS = REPO / "artifacts" / "readings" / "queue.json"


def readings() -> dict:
    """#591: the builds the brain queued for the owner to read, newest first; `run_dir` made
    absolute so `openpob` finds the run wherever the pane's python starts."""
    if not READINGS.is_file():
        return {"updated": None, "rows": []}
    data = json.loads(READINGS.read_text(encoding="utf-8"))
    rows = [dict(r) for r in data.get("rows") or []]
    for r in rows:
        if r.get("run_dir"):
            r["run_dir"] = str((REPO / r["run_dir"]).resolve())
    # Newest batch first; one `readings.py add` batch spans a few seconds, so rows of the same
    # minute keep the file's own order (the brain's ranking), never reshuffled by the second.
    rows.sort(key=lambda r: (r.get("added_at") or "")[:16], reverse=True)
    cache = _load_json(READING_FACTS) or {}
    seen: dict = {}
    for r in rows:
        try:
            r.update(_reading_facts(r, cache, seen))
        except Exception:  # a row the collector cannot word is still drawn, by its own fields
            pass
    if seen != cache:
        try:
            READING_FACTS.parent.mkdir(parents=True, exist_ok=True)
            READING_FACTS.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return {"updated": data.get("updated"), "rows": rows}


READING_FACTS = CACHE_DIR / "reading_facts.json"


def _load_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _ru(n: int, one: str, few: str, many: str) -> str:
    return one if n % 10 == 1 and n % 100 != 11 else few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


def _stat_words(text: str) -> str:
    """PoB's output names inside a sentence, as PoB's own UI labels them (`PhysicalMaximumHitTaken` -> `Phys Max Hit`)."""
    label("Life")  # fills _LABELS
    return re.sub(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b", lambda m: label(m[0]) if m[0] in (_LABELS or {}) else m[0], text)


def _finding_words(f: str) -> tuple[bool, str]:
    """One finding of the build's own check (`[severity] check: detail`, optimizer/audit.py) in a reader's words:
    (is it an error, the sentence). The kinds a delivered build really carries are worded here; any other keeps its
    own sentence, PoB's output names as PoB's UI labels them."""
    m = re.match(r"\[(\w+)\] ([^:]+): (.*)$", f, re.S)
    if not m:
        return False, _stat_words(f)
    bad, check, detail = m[1] == "error", m[2], m[3]
    if check == "not modelled by PoB":
        return bad, "PoB не считает: " + re.sub(r": worth zero in every number here$", "", detail)
    if check == "fixed point":
        g = re.search(r"gained ([+-]?[\d.]+)\s*%", detail)
        return bad, "поиск остановился рано" + (f": ещё один проход дал {g[1]} %" if g else "")
    if check == "floor":
        return bad, _floor_words(detail.replace(" = ", " ", 1))
    return bad, f"{check}: {_stat_words(detail)}"


def _floor_words(x: str) -> str:
    """A missed floor of the objective (`<stat> <observed> < <floor>`, audit.py missed_constraints) as a sentence."""
    if g := re.match(r"(\w+) (\S+) ([<>]) (\S+)$", x):
        return f"ниже порога защиты: {label(g[1])} {g[2]} при {'пороге' if g[3] == '<' else 'потолке'} {g[4]}"
    return "ниже порога защиты: " + _stat_words(x)


def _reading_facts(r: dict, cache: dict, seen: dict) -> dict:
    """#683 r5 (owner 10.10 12:1x, on the Builds tab: «хватит сюда нести тупо вериблы из кода»): what a reading's row
    and its open build say in a reader's words, never a slug or an output's code name:
    `name` (the main skill of a request's build, else the reference's words, as a square says it), `var` (what the
    variant lacks: «без Blood Magic»), `class` / `asc` (the row's face), `metric_label` + `ours_h` (the main number
    under PoB's own UI label, formatted as the stats table formats it), `errors` / `warnings` / `floors_bad` (the
    build's own check; None = not known), `said` = that check as sentences for the open build ([is it bad, text]).
    A request's facts come from its `<ref>.json` (skeleton, audit, floors_missed), cached by the file's mtime."""
    out: dict = {"name": words(re.sub(r"^\d+\s+", "", r.get("ref") or "")), "var": "", "class": None, "asc": None,
                 "errors": None, "warnings": None, "floors_bad": None, "said": []}
    v = r.get("variant") or ""
    if v:
        out["var"] = f"без {words(v[3:])}" if v.startswith("no-") else words(v.replace("-", "_"))
    if r.get("metric"):
        out["metric_label"] = label(r["metric"])
        out["ours_h"] = _fmt(r["metric"], r["ours"]) if r.get("ours") is not None else ""
    if m := re.match(r"(\d+) errors? / (\d+) warnings?", r.get("audit") or ""):
        out["errors"], out["warnings"] = int(m[1]), int(m[2])
    if r.get("floors"):
        out["floors_bad"] = r["floors"] != "ok"
    js = Path(r.get("run_dir") or "") / f"{r.get('ref')}.json"
    if r.get("rank") is None or not js.is_file():
        out.update({k: v for k, v in build_class(r.get("ref") or "").items() if v})
    else:
        key, mt = str(js), js.stat().st_mtime
        if (cache.get(key) or {}).get("mtime") == mt:
            got = cache[key]
        else:
            d = _load_json(js) or {}
            sk = d.get("skeleton")
            sk = (json.loads(sk) if isinstance(sk, str) else sk) or {}
            got = {"mtime": mt, "skill": (sk.get("main_link") or [None])[0], "class": sk.get("class_name"),
                   "asc": sk.get("ascendancy"),
                   "without": [*(sk.get("forbid_keystones") or []), *(sk.get("forbid_supports") or []), *(sk.get("forbid_utilities") or [])],
                   "audit": d.get("audit") if isinstance(d.get("audit"), list) else None, "floors_missed": d.get("floors_missed")}
        seen[key] = got
        out["name"] = got["skill"] or out["name"]
        out["class"], out["asc"] = got["class"], got["asc"]
        if got["without"]:
            out["var"] = "без " + ", ".join(got["without"])
        if got["audit"] is not None:
            found = [_finding_words(str(f)) for f in got["audit"]]
            out["errors"], out["warnings"] = sum(1 for b, _ in found if b), sum(1 for b, _ in found if not b)
            out["said"] += [[b, t] for b, t in sorted(found, key=lambda x: not x[0])]
        if got["floors_missed"] is not None:
            out["floors_bad"] = bool(got["floors_missed"])
            out["said"] += [[True, t] for t in map(_floor_words, got["floors_missed"]) if [True, t] not in out["said"]]
    # a row whose check is known only as the queue's own strings: the counts, and a failed floor's own string
    if out["floors_bad"] and not any("порог" in t for _, t in out["said"]):
        out["said"].append([True, _floor_words(r.get("floors") or "")])
    return out


# ================================================================ one build (detail on press)

# ---------------------------------------------------------------- build (one cell, on press)

#: poe.ninja-like groups of the <PlayerStat stat=...> PoB saved in the build XML, names as PoB
#: writes them. A percent stat gets no ours/author ratio; a charge shows "count/max".
PCT_STATS = {"PhysicalDamageReduction", "EffectiveBlockChance", "EffectiveSpellBlockChance",
             "EffectiveSpellSuppressionChance", "FireResist", "ColdResist", "LightningResist", "ChaosResist",
             "HitChance", "CritChance", "CritMultiplier", "ManaUnreservedPercent", "LifeUnreservedPercent"}
ALWAYS = {"Str", "Dex", "Int", "Life", "Mana", "FireResist", "ColdResist", "LightningResist", "ChaosResist",
          "TotalEHP", "PhysicalMaximumHitTaken"}
#: Main skill first: the owner reads the damage before the character (10.10, #683 r5 pt 3).
GROUPS = (
    ("Main skill", ("FullDPS", "CombinedDPS", "TotalDPS", "TotalDotDPS", "BleedDPS", "IgniteDPS", "PoisonDPS",
                    "AverageDamage", "Speed", "HitChance", "CritChance", "CritMultiplier", "ManaCost")),
    ("Character", ("Str", "Dex", "Int", "PowerCharges", "FrenzyCharges", "EnduranceCharges",
                   "EffectiveMovementSpeedMod")),
    ("Defensive", ("Life", "EnergyShield", "Mana", "ManaUnreserved", "Ward", "Armour", "Evasion",
                   "PhysicalDamageReduction", "EffectiveBlockChance", "EffectiveSpellBlockChance",
                   "EffectiveSpellSuppressionChance", "FireResist", "ColdResist", "LightningResist", "ChaosResist",
                   "TotalEHP", "PhysicalMaximumHitTaken", "FireMaximumHitTaken", "ColdMaximumHitTaken",
                   "LightningMaximumHitTaken", "ChaosMaximumHitTaken")),
    ("Recovery", ("LifeRegenRecovery", "LifeLeechGainRate", "ManaRegenRecovery", "ManaLeechGainRate",
                  "EnergyShieldRegenRecovery", "EnergyShieldLeechGainRate", "EnergyShieldRecharge")),
)
BUILDS = Path.home() / "Documents" / "Path of Building" / "Builds"
POB_EXE = Path.home() / "AppData" / "Roaming" / "Path of Building Community" / "Path of Building.exe"


# Stat labels as PoB's own sidebar writes them (Modules/BuildDisplayStats.lua, `{ stat = ..., label = ... }`),
# read from the owner's PoB at run time, never typed here. Where PoB has several labels for one stat
# (by skill type), PREFER picks one of PoB's own; a stat PoB never labels splits its CamelCase name.
POB_DISPLAY = POB_EXE.parent / "Modules" / "BuildDisplayStats.lua"
PREFER = {"Speed": "Attack/Cast Rate", "PoisonDPS": "Poison DPS", "LightningMaximumHitTaken": "Lightning Max Hit",
          "LifeRegenRecovery": "Life Recovery", "ManaRegenRecovery": "Mana Recovery",
          "EnergyShieldRegenRecovery": "ES Recovery"}
#: The repo's pinned PoB holds the same file: read where the owner's PoB is not installed (the laptop, a test).
VENDOR_DISPLAY = REPO / "vendor" / "pob" / "source" / "src" / "Modules" / "BuildDisplayStats.lua"
_LABELS: dict[str, list[str]] | None = None
_PC: set[str] | None = None


def _display_text() -> str:
    for p in (POB_DISPLAY, VENDOR_DISPLAY):
        try:
            return p.read_text(encoding="utf-8")
        except OSError:
            continue
    return ""


def pc_stats() -> set[str]:
    """#1013: the stats PoB saves as a ratio (CritMultiplier 1.5) and shows times 100 ("150%"): `pc = true` in
    BuildDisplayStats.lua, scaled by Build.lua `FormatStat` (`statVal * (statData.pc and 100 or 1)`)."""
    global _PC
    if _PC is None:
        _PC = {m.group(1) for m in re.finditer(r'\{\s*stat\s*=\s*"(\w+)"[^\n]*?\bpc\s*=\s*true', _display_text())}
    return _PC


def label(stat: str) -> str:
    global _LABELS
    if _LABELS is None:
        _LABELS = {}
        for m in re.finditer(r'\{\s*stat\s*=\s*"(\w+)"\s*,\s*label\s*=\s*"([^"]*)"', _display_text()):
            _LABELS.setdefault(m.group(1), []).append(m.group(2))
    have = _LABELS.get(stat)
    if have:
        return PREFER[stat] if PREFER.get(stat) in have else have[0]
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stat)


def _fmt(stat: str, v: float | None) -> str:
    if v is None:
        return "-"
    if stat in pc_stats():
        v = v * 100
    if stat in PCT_STATS:
        return f"{v:.0f}%"
    if stat in ("Speed", "EffectiveMovementSpeedMod"):
        return f"{v:.2f}"
    a = abs(v)
    if a >= 1e6:
        return f"{v / 1e6:.2f}M"
    if a >= 1e5:
        return f"{v / 1e3:.0f}k"
    if a < 100 and v != int(v):
        return f"{v:.1f}"
    return f"{v:,.0f}"


def _build_facts(xml: str) -> dict:
    from xml.etree import ElementTree as ET

    root = ET.fromstring(xml)
    b = root.find("Build")
    stats: dict[str, float] = {}
    for ps in (b.findall("PlayerStat") if b is not None else []):
        try:
            stats[ps.get("stat")] = float(ps.get("value"))
        except (TypeError, ValueError):
            pass
    skill = None
    skills = root.find("Skills")
    if b is not None and skills is not None:
        sets = skills.findall("SkillSet") or [skills]
        active = skills.get("activeSkillSet") or "1"
        sset = next((x for x in sets if x.get("id") == active), sets[0])
        try:
            g = sset.findall("Skill")[int(b.get("mainSocketGroup") or 1) - 1]
            gems = [x for x in g.findall("Gem")
                    if not (x.get("skillId") or "").startswith("Support") and x.get("enabled") != "false"]
            skill = gems[int(g.get("mainActiveSkill") or 1) - 1].get("nameSpec") if gems else None
        except (IndexError, ValueError):
            skill = None
    cls = level = None
    if b is not None:
        cls = " / ".join(x for x in (b.get("className"), b.get("ascendClassName")) if x and x != "None")
        level = b.get("level")
    return {"stats": stats, "skill": skill, "class": cls, "level": level}


def _benchmark_pob_file(d: Path, ref: str, seed: str, variant: str = "") -> Path:
    """Where scripts/benchmark.py (`_pob_build_dir`, `persist_completed_row`) already wrote this
    build into PoB's Builds folder."""
    n = d.name
    return BUILDS / "Junkroan" / f"benchmark {n[:4]}-{n[4:6]}-{n[6:8]} {n[9:]}" / f"{ref} s{seed}{' ' + variant if variant else ''}.xml"


def _on_laptop(mode: str, *args: str) -> dict:
    """`mode` run on the laptop: this very file piped to `ssh laptop python - <mode> <args> here` (a folder of a run the
    laptop made lives there). An empty argument would vanish on the remote command line, so it travels as `_`."""
    try:
        res = subprocess.run(["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "laptop", "python", "-", mode,
                              *[a or "_" for a in args], "here"], input=remote_program(),
                             capture_output=True, text=True, encoding="utf-8", timeout=50, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        return {"error": "ноутбук не ответил за 50 s"}
    if res.returncode != 0:
        return {"error": f"ноутбук: {(res.stderr.strip().splitlines() or [f'ssh rc {res.returncode}'])[-1][:160]}"}
    try:
        return json.loads(res.stdout)
    except ValueError:
        return {"error": "ноутбук вернул не JSON"}


def _author_facts(d: Path, ref: str, row: dict) -> dict | None:
    """The author's build of a benchmark run folder `d`: `author/<ref>-<regime>.json` `state_xml`."""
    regime = row.get("author_regime")
    cands = ([d / "author" / f"{ref}-{regime}.json"] if regime else []) + sorted((d / "author").glob(f"{ref}-*.json"))
    for ap in cands + [d / "author" / f"{ref}.json"]:  # an older run kept one author file per build
        if ap.is_file():
            try:
                return _build_facts(json.loads(ap.read_text(encoding="utf-8"))["state_xml"])
            except (ValueError, KeyError, TypeError):
                continue
    return None


def _stat_groups(ours: dict, author: dict | None, main_stat: str) -> list[dict]:
    groups = []
    for title, names in GROUPS:
        names = [n for n in names if n != main_stat]
        if title == "Main skill":
            names.insert(0, main_stat)
        rows = []
        for n in names:
            o = ours["stats"].get(n)
            a = author["stats"].get(n) if author else None
            if n.endswith("Charges"):
                om = ours["stats"].get(n + "Max")
                am = author["stats"].get(n + "Max") if author else None
                if not (o or a or om or am):
                    continue
                rows.append([label(n), f"{_fmt(n, o)}/{_fmt(n, om)}", f"{_fmt(n, a)}/{_fmt(n, am)}" if author else "-", None])
                continue
            if n not in ALWAYS and n != main_stat and not (o or a):
                continue
            pct = round(o / a * 100) if (o is not None and a and n not in PCT_STATS) else None
            rows.append([label(n), _fmt(n, o), _fmt(n, a) if author else "-", pct])
        if rows:
            groups.append({"title": title, "rows": rows})
    return groups


def _is_replay_dir(d: Path) -> bool:
    return (d / "results.json").is_file() and not (d / "args.json").is_file()


def _replay_parts(d: Path, ref: str, seed: str, variant: str) -> dict:
    """One build of a replay_bench run folder `d` (artifacts/replay/<stamp>): its results.json row (matched by the
    delivered file it started from), the final build (`final_build`, else builds/<reference>.xml), and the benchmark
    folder that delivered the start, which holds the author's build and the start's own row."""
    stem = f"{ref}-s{seed}{'-' + variant if variant else ''}"
    try:
        res = json.loads((d / "results.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"error": "итоги этого рана не читаются"}
    row = next((r for r in res.get("rows", []) if re.split(r"[\\/]", str(r.get("source") or ""))[-1] == f"{stem}.pob.txt"), None)
    if row is None:
        return {"error": "этого билда нет в итогах рана"}
    src = re.split(r"[\\/]", str(row.get("source") or ""))
    bench = BENCH / src[-2] if len(src) >= 2 else None
    final = None
    for name in ([re.split(r"[\\/]", str(row["final_build"]))[-1]] if row.get("final_build") else []) + [f"{ref}.xml"]:
        if (d / "builds" / name).is_file():
            final = d / "builds" / name
            break
    return {"stem": stem, "res": res, "row": row, "bench": bench, "final": final,
            "bench_row": _read_row(bench / "rows" / f"{stem}.json") if bench else {},
            "pob_file": BUILDS / "Junkroan" / "monitor" / f"junkroan replay {d.name} {stem}.xml"}


def _replay_build(d: Path, ref: str, seed: str, variant: str) -> dict:
    """#683 r5: the stats panel of a replay run's square: ours = the build the replayed move delivered, compared with
    the author's build of the benchmark run it started from; `note` = the replay's own before -> after."""
    from junkroan.pob.session import encode_import_code

    p = _replay_parts(d, ref, seed, variant)
    if p.get("error"):
        return p
    row, bench_row = p["row"], p["bench_row"]
    if not row.get("ok") or p["final"] is None:
        return {"error": "билд не досчитан: " + ("проверка упала с ошибкой" if row.get("error") else "итогового PoB нет")}
    xml = p["final"].read_text(encoding="utf-8")
    ours = _build_facts(xml)
    author = _author_facts(p["bench"], ref, bench_row) if p["bench"] else None
    main_stat = row.get("stat") or bench_row.get("stat") or "CombinedDPS"
    before, after = row.get("value_before"), row.get("value_after")
    note = None
    if before is not None and after is not None:
        gain = row.get("gain_percent")
        note = (f"replay {p['res'].get('move') or ''}: {label(main_stat)} {_fmt(main_stat, before)} -> {_fmt(main_stat, after)}"
                + (f" ({gain:+.2f} %)" if gain is not None else "") + (f" · {hd(row['seconds'])}" if row.get("seconds") else ""))
    return {
        "name": words(ref), "seed": int(seed), "class": ours["class"], "level": ours["level"],
        "skill": ours["skill"], "author_skill": author["skill"] if author else None,
        "author_class": author["class"] if author else None, "author_level": author["level"] if author else None,
        "author": author is not None, "groups": _stat_groups(ours, author, main_stat), "code": encode_import_code(xml),
        "pob_file": str(p["pob_file"]), "pob_file_exists": p["pob_file"].is_file(), "note": note,
        "pobbin_id": None, "pobbin_url": None, "author_pobbin_url": bench_row.get("author_pobbin_url"),
    }


def _is_request_dir(d: Path) -> bool:
    """A `junkroan build` request's folder (artifacts/search-<skill>/<stamp>): ranked builds beside report.md, no
    `rows/` of a benchmark run."""
    return not (d / "rows").is_dir() and not (d / "args.json").is_file() and not (d / "results.json").is_file()


def _request_parts(d: Path, ref: str, seed: str) -> dict:
    """#730: one ranked build of a request folder: its import code (`<ref>.pob.txt` is the rank's best seed; another
    seed of the rank is `<ref>-s<seed>.pob.txt`) and its row of the reading queue (pobb.in id, metric, rank, audit)."""
    code_path = next((p for p in (d / f"{ref}-s{seed}.pob.txt", d / f"{ref}.pob.txt") if p.is_file()), None)
    row = {}
    if READINGS.is_file():
        try:
            rows = json.loads(READINGS.read_text(encoding="utf-8")).get("rows") or []
        except (OSError, ValueError):
            rows = []
        row = next((r for r in rows if r.get("ref") == ref and str(r.get("seed")) == str(seed) and r.get("run_dir")
                    and (REPO / r["run_dir"]).resolve() == d.resolve()), {})
    return {"code_path": code_path, "row": row}


def _request_build(d: Path, ref: str, seed: str) -> dict:
    """#730: the stats panel of a build made from a request: PoB's own saved stats of its import code, no author."""
    from junkroan.pob.session import decode_import_code

    p = _request_parts(d, ref, seed)
    if p["code_path"] is None:
        return {"error": "билд не досчитан: итогового PoB нет"}
    code = p["code_path"].read_text(encoding="utf-8").strip()
    ours, row = _build_facts(decode_import_code(code)), p["row"]
    main_stat = row.get("metric") or _read_row(d / f"{ref}.json").get("stat") or "CombinedDPS"
    note = " · ".join(x for x in (f"rank {row['rank']}" if row.get("rank") is not None else "",
                                  f"audit: {row['audit']}" if row.get("audit") else "",
                                  f"floors: {row['floors']}" if row.get("floors") else "") if x)
    return {
        "name": row.get("run_name") or words(ref), "seed": int(seed), "class": ours["class"], "level": ours["level"],
        "skill": ours["skill"], "author_skill": None, "author_class": None, "author_level": None, "author": False,
        "groups": _stat_groups(ours, None, main_stat), "code": code, "pob_file": "", "pob_file_exists": False,
        "note": note or None, "pobbin_id": row.get("pobbin_id"),
        "pobbin_url": f"https://pobb.in/{row['pobbin_id']}" if row.get("pobbin_id") else None, "author_pobbin_url": None,
    }


def build(run_dir: str, ref: str, seed: str, variant: str = "", here: str = "") -> dict:
    """poe.ninja-like stat panel of one finished cell: ours from `<ref>-s<seed>.pob.txt` (decoded by
    the repo's own `junkroan.pob.session.decode_import_code`), the author's from the run's
    `author/<ref>-<regime>.json` `state_xml`. A replay run's folder goes to `_replay_build`, a request's
    folder to `_request_build`; a folder this host lacks is the laptop's run, asked of the laptop
    (`here` stops that hop there)."""
    from junkroan.pob.session import decode_import_code

    variant = "" if variant == "_" else variant
    d = Path(run_dir)
    if not d.is_dir():
        return {"error": "папка этого рана не найдена"} if here else _on_laptop("build", run_dir, ref, seed, variant)
    if _is_replay_dir(d):
        return _replay_build(d, ref, seed, variant)
    if _is_request_dir(d):
        return _request_build(d, ref, seed)
    sfx = f"-{variant}" if variant else ""
    code_path = d / f"{ref}-s{seed}{sfx}.pob.txt"
    if not code_path.is_file():
        return {"error": "билд не досчитан: итогового PoB нет"}
    code = code_path.read_text(encoding="utf-8").strip()
    ours = _build_facts(decode_import_code(code))
    row = _read_row(d / "rows" / f"{ref}-s{seed}{sfx}.json")
    author = _author_facts(d, ref, row)
    pob_file = _benchmark_pob_file(d, ref, seed, variant)
    return {
        "name": words(ref), "seed": int(seed), "class": ours["class"], "level": ours["level"],
        "skill": ours["skill"], "author_skill": author["skill"] if author else None,
        "author_class": author["class"] if author else None, "author_level": author["level"] if author else None,
        "author": author is not None, "groups": _stat_groups(ours, author, row.get("stat") or "CombinedDPS"), "code": code,
        "pob_file": str(pob_file), "pob_file_exists": pob_file.is_file(),
        "pobbin_id": row.get("pobbin_id"), "pobbin_url": row.get("pobbin_url"),
        "author_pobbin_url": row.get("author_pobbin_url"),
    }


def _launch_pob(link: str | None = None) -> None:
    # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW: PoB outlives this script.
    subprocess.Popen([str(POB_EXE)] + ([link] if link else []), cwd=str(POB_EXE.parent), creationflags=0x8 | 0x200 | NO_WINDOW,
                     close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _open_pobbin(url_or_id: str | None, who: str) -> dict:
    pobbin_id = url_or_id.rstrip("/").rsplit("/", 1)[-1] if url_or_id else None
    if not pobbin_id:
        return {"error": "у этого билда нет PoB автора на pobb.in" if who == "author" else "у этого билда нет ссылки pobb.in"}
    _launch_pob(f"pob://pobbin/{pobbin_id}")
    return {"ok": True, "link": f"pob://pobbin/{pobbin_id}", "where": f"pobb.in/{pobbin_id}"}


def _open_xml(xml_path: Path, xml: str) -> dict:
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    xml_path.write_text(xml, encoding="utf-8")
    _launch_pob()
    return {"ok": True, "pob_file": str(xml_path), "where": " › ".join(xml_path.relative_to(BUILDS).parts)}


def openpob(run_dir: str, ref: str, seed: str, who: str = "ours", variant: str = "") -> dict:
    """Start the owner's PoB detached, no console. PoB takes on its command line only a
    `pob://<site>/<id>` link it downloads from that site (Modules/Main.lua, BuildSiteTools.lua),
    never a local file or code, so the build waits in PoB's own Builds folder: the benchmark's copy
    when it is there, else one written here from the import code under Builds/Junkroan/monitor/.
    `who="author"` opens the author's build, which exists only as its pobb.in upload (#572).
    A replay run's build is written there from its final XML; a laptop run's comes from the laptop's `build`."""
    from junkroan.pob.session import decode_import_code

    d = Path(run_dir)
    sfx = f"-{variant}" if variant else ""
    if not POB_EXE.is_file():
        return {"error": f"Path of Building не найден: {POB_EXE}"}
    if not d.is_dir():  # a run the laptop made: its panel's data carries the import code and the author's link
        b = _on_laptop("build", run_dir, ref, seed, variant)
        if b.get("error"):
            return b
        if who == "author":
            return _open_pobbin(b.get("author_pobbin_url"), who)
        if b.get("pobbin_id"):
            return _open_pobbin(b["pobbin_id"], who)
        return _open_xml(BUILDS / "Junkroan" / "monitor" / f"junkroan laptop {d.name} {ref} s{seed}{sfx}.xml",
                         decode_import_code(b["code"]))
    if _is_replay_dir(d):
        p = _replay_parts(d, ref, seed, variant)
        if p.get("error"):
            return p
        if who == "author":
            return _open_pobbin(p["bench_row"].get("author_pobbin_url"), who)
        if p["final"] is None:
            return {"error": "у этого replay нет итогового PoB"}
        return _open_xml(p["pob_file"], p["final"].read_text(encoding="utf-8"))
    if _is_request_dir(d):  # #730: by the queue row's pobb.in id, else from the rank's import code
        p = _request_parts(d, ref, seed)
        if who == "author":
            return _open_pobbin(None, who)
        if p["row"].get("pobbin_id"):
            return _open_pobbin(p["row"]["pobbin_id"], who)
        if p["code_path"] is None:
            return {"error": "у этого билда нет итогового PoB"}
        return _open_xml(BUILDS / "Junkroan" / "monitor" / f"junkroan request {d.name} {ref}.xml",
                         decode_import_code(p["code_path"].read_text(encoding="utf-8")))
    # #572: a build the benchmark uploaded to pobb.in opens straight from there (PoB's own
    # `pob://pobbin/<id>`, the link its Main.lua imports on start); no upload on a click.
    row = _read_row(d / "rows" / f"{ref}-s{seed}{sfx}.json")
    if who == "author":
        return _open_pobbin(row.get("author_pobbin_url"), who)
    if row.get("pobbin_id"):
        return _open_pobbin(row["pobbin_id"], who)
    code_path = d / f"{ref}-s{seed}{sfx}.pob.txt"
    xml_path = _benchmark_pob_file(d, ref, seed, variant)
    if not xml_path.is_file():
        if not code_path.is_file():
            return {"error": "у этого билда нет итогового PoB"}
        return _open_xml(BUILDS / "Junkroan" / "monitor" / f"junkroan {d.name} {ref} s{seed}{sfx}.xml",
                         decode_import_code(code_path.read_text(encoding="utf-8")))
    _launch_pob()
    return {"ok": True, "pob_file": str(xml_path), "where": " › ".join(xml_path.relative_to(BUILDS).parts)}


# ================================================================ the contract with the generic collector

def machine_pids(ctx) -> tuple[set[int], int | None]:
    """The PoB slot pids and the daemon's pid the generic `machine()` splits the load by (`ctx.sections` = what `fast`
    returned: its `runs`)."""
    r = ctx.sections.get("runs") or {}
    return {s["pid"] for s in r.get("slots", []) if s.get("pid")}, (r.get("daemon") or {}).get("pid")


def fast(ctx) -> dict:
    """The add-on's sections of the fast payload: readings, runs (or runs_error), laptop, status."""
    out: dict = {}
    from concurrent.futures import ThreadPoolExecutor
    pool = ThreadPoolExecutor(1)
    lap = pool.submit(laptop)
    try:
        out["readings"] = readings()
    except Exception as exc:  # noqa: BLE001
        out["readings"] = {"updated": None, "rows": [], "error": repr(exc)[:200]}
    try:
        out["runs"] = runs()
    except Exception as exc:  # noqa: BLE001
        out["runs_error"] = repr(exc)[:200]
    try:
        out["laptop"] = lap.result(timeout=LAPTOP_WAIT + 1)
    except Exception as exc:  # noqa: BLE001
        # #984: whatever went wrong, the last good reading (with its age) stands in; never a bare error row.
        try:
            cache = json.loads(LAPTOP_CACHE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = None
        out["laptop"] = _stamped(cache) if (cache or {}).get("data") else _down(cache, repr(exc)[:200])
    r = out.get("runs")
    if r:
        merge_laptop(r, out["laptop"])
        parts = [f"PoB {len(r['slots'])}/{r['total']} slots"]
        if r["waiting"]:
            parts.append(f"{r['waiting']} waiting")
        for run in r["running"][:1]:
            p = run.get("progress")
            parts.append(f"{run['tag']} {p['done']}/{p['total']}" + (f" ~{p['eta']}" if p.get("eta") else "")
                         if p else run["tag"])
        if len(r["running"]) > 1:
            parts.append(f"+{len(r['running']) - 1} runs")
        if r["queued"]:
            parts.append(f"queued {len(r['queued'])}")
        out["status"] = " · ".join(parts)
    return out


#: extra command-line modes: `python collect.py <mode> <args...>`
MODES = {"build": build, "openpob": openpob, "cells": cells, "host": host}
