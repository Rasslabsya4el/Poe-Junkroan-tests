"""#796 unit 0: the collector's payloads, recorded from stubbed sources and compared as JSON.

    python -m pytest -q mods/pob-slots/bin/test_payload_snapshot.py     (from the repo root, like the other bin tests)

Five payloads are collected: `fast` with the laptop reachable, `fast` with the laptop out of reach, `tickets`, `slow`
and `orch` (the modes of `collect.py`'s `__main__`). Every external source is stubbed from `fixtures/payload/`:
`gh` / `ssh` / `merge-status` through one fake `subprocess.run`, the clock (`NOW`, `datetime`, `time`), the run store and
slot budget, the process table, the daemon files, the benchmark folders, the readings queue and the token meter. Nothing
reads `var/`, `artifacts/`, `~/.claude`, PoB or the network, and every cache file of the collector goes to a temp folder.
A payload's folder path is written as `<ROOT>`. The recorded result of each is `fixtures/payload/expected/<case>.json`
(keys sorted, 1-space indent, LF).

To record the expected files again (ONLY when a payload is meant to change; the refactor that moves code between
modules must leave them byte for byte as they are):

    PAYLOAD_SNAPSHOT_REGEN=1 python -m pytest -q mods/pob-slots/bin/test_payload_snapshot.py

Where a name lives is told in ONE place: `OWNERS` and `PAYLOADS` below. A module that takes over code (the add-on)
is added to `OWNERS`; `seam` then patches that name in every owner that has it.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2]))
sys.path.insert(0, str(HERE.parents[2] / "scripts"))

import collect  # noqa: E402

FX = HERE / "fixtures" / "payload"
EXPECTED = FX / "expected"

# ---- the one place that knows which module holds which name (retarget here when code moves) ----
ADDON = collect.addon()  # the project's add-on (`monitor.addon`): its names are patched the same way
OWNERS = [collect, ADDON]
PAYLOADS = {"fast": lambda: collect.fast(), "tickets": lambda: collect.tickets(),
            "slow": lambda: collect.slow(), "orch": lambda: collect.orch()}
# the cases: (file name, payload, laptop state)
CASES = [("fast_online", "fast", "online"), ("fast_offline", "fast", "offline"),
         ("tickets", "tickets", "online"), ("slow", "slow", "online"), ("orch", "orch", "online")]
# the command lines the collector reads through psutil (`_cmdline`), by fake pid: fixture values, never the host's.
# pid 5000 is a live CLI session (`is_session` needs a command line, collect.py:709), so its agents share is non-zero.
CMDLINES = {5000: r"C:\Users\user\.local\bin\claude.exe"}
# -------------------------------------------------------------------------------------------------


def seam(mp: pytest.MonkeyPatch, name: str, value) -> None:
    """Patch `name` in every owner module that has it."""
    hit = [m for m in OWNERS if hasattr(m, name)]
    assert hit, f"no owner module has {name}"
    for m in hit:
        mp.setattr(m, name, value)


def owned(name: str):
    return next(getattr(m, name) for m in OWNERS if hasattr(m, name))


UTC = timezone.utc


class FakeDT(datetime):
    """The collector's `datetime`: now is 2026-10-11 12:00 UTC; local time is UTC on any machine."""

    @classmethod
    def now(cls, tz=None):
        base = cls(2026, 10, 11, 12, 0, 0)
        return base if tz is None else base.replace(tzinfo=UTC).astimezone(tz)

    @classmethod
    def fromtimestamp(cls, ts, tz=None):
        return super().fromtimestamp(ts, tz or UTC)

    def astimezone(self, tz=None):
        base = self if self.tzinfo else self.replace(tzinfo=UTC)
        return datetime.astimezone(base, tz or UTC)


NOW = FakeDT(2026, 10, 11, 12, 0, 0, tzinfo=UTC)
T0 = NOW.timestamp()


class FixedPath(type(Path())):
    """The benchmark folders' `.log` files carry a fixed creation time (a copied file has today's)."""

    def stat(self, **kw):
        r = super().stat(**kw)
        if self.suffix == ".log":
            t = int(T0 - 300)
            return os.stat_result(tuple(r)[:7] + (t, t, t))
        return r


def load(name: str):
    return json.loads((FX / "inputs" / name).read_text(encoding="utf-8"))


def copy_tree(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst)
    for p in [*dst.rglob("*.log.txt"), *dst.rglob("*.jsonl.txt")]:  # `*.log`, `*.jsonl` are git-ignored: kept as `.txt`
        p.rename(p.with_suffix(""))


class FakeClient:
    def __init__(self, reading: dict):
        self.reading = reading

    def call(self, method, path, directory=None, body=None, timeout=60):
        assert method == "GET"
        if path == "/session":
            return self.reading["sessions"]
        if path == "/session/status":
            return {s["id"]: {"type": "busy"} for s in self.reading["sessions"]}
        return self.reading["messages"].get(path.split("/")[2], [])


def build_world(mp: pytest.MonkeyPatch, tmp: Path, laptop: str) -> Path:
    root = (tmp / "repo").resolve()
    (root / "artifacts").mkdir(parents=True)
    # the installation names the two repo modules the monitor reads through its settings keys (#1096 3a) and the
    # owner's plan price of 1 % (#1094: no plan = no money column, so the snapshot names it)
    (root / "config").mkdir()
    (root / "config" / "orchestration.json").write_text(json.dumps({
        "monitor_dashboard": "tools.agentops.monitor_dashboard", "agent_status": "tools.agentops.agent_status",
        "limit_usd_per_pct": 16.5}),
        encoding="utf-8")
    copy_tree(FX / "bench", root / "artifacts" / "benchmark")
    copy_tree(FX / "runs", root / "artifacts" / "runs")
    copy_tree(FX / "readings", root / "artifacts" / "readings")
    cache = tmp / "cache"
    cache.mkdir()
    # the clock
    seam(mp, "datetime", FakeDT)
    seam(mp, "NOW", NOW)
    seam(mp, "time", SimpleNamespace(time=lambda: T0, sleep=lambda s: None))
    # the folders: the repo, its artifacts, every cache file
    bench = FixedPath(root / "artifacts" / "benchmark")
    for name, value in (("REPO", root), ("BENCH", bench), ("BENCH_ROOT", bench), ("REPLAY_ROOT", root / "artifacts" / "replay"),
                        ("READINGS", root / "artifacts" / "readings" / "queue.json"),
                        ("DAEMON_ERR", root / "artifacts" / "runs" / "daemon-pc.err"),
                        # the orch, opencode-launch and pipeline files are named from CACHE_DIR at each use (#182): no seam
                        ("CACHE_DIR", cache), ("HISTORY_CACHE", cache / "history.json"),
                        ("EST_CACHE", cache / "estimates.json"), ("LAPTOP_CACHE", cache / "laptop.json"),
                        ("READING_FACTS", cache / "reading_facts.json"), ("STAGE_SHARES", cache / "stage_shares.json"),
                        ("REPLAY_SEEN", cache / "replay_seen.json"),
                        ("SNAP", cache / "machine-snap.json"),
                        ("MONITOR_USAGE", cache / "monitor.jsonl")):
        seam(mp, name, value)
    # PoB-side lookups the collector makes outside its own folder
    seam(mp, "_LABELS", {"CombinedDPS": ["Combined DPS"], "Life": ["Life"], "TotalEHP": ["Total EHP"],
                         "PhysicalMaximumHitTaken": ["Phys Max Hit"]})
    seam(mp, "_catalog", lambda: None)
    seam(mp, "stage_shares", lambda: None)
    classes = {"spark": {"class": "Witch", "asc": "Occultist"}, "bleed_bow": {"class": "Ranger", "asc": "Deadeye"}}
    seam(mp, "build_class", lambda slug, _memo=None: dict(classes.get(slug, {})))
    mp.setattr("junkroan.runs.build_estimate.estimate_build", lambda slug, d, loop, bench_root: (600.0, "stub"))
    # the run store and the slot budget
    j = load("jobs.json")
    jobs = [SimpleNamespace(**{"pin": None, "submitter": "x", "resumable": False, "rc": None, "out": None, "run_dir": None,
                               "attempts": 0, "pid": None, "posted": False, "argv": None, "after": [], **row})
            for row in j["jobs"]]
    mp.setattr("junkroan.runs.store.Store", lambda path: SimpleNamespace(jobs=lambda: jobs))
    b = j["budget"]
    budget = SimpleNamespace(period=b["period"], total=b["total"], others=b["others"], limit_for=lambda role: b["queue_limit"])
    from junkroan.pob import slot_budget
    mp.setattr(slot_budget, "load_budget", lambda *a, **k: budget)
    mp.setattr(slot_budget, "slot_dir", lambda: tmp / "slots")
    mp.setattr(slot_budget, "busy_slots", lambda folder, budget=None: copy.deepcopy(j["busy_slots"]))
    mp.setattr(slot_budget, "waiting", lambda folder: list(j["waiting"]))
    mp.setattr(slot_budget, "current_host", lambda root=None: "pc")
    # the process table and the machine's counters
    m = load("machine.json")
    procs = {int(pid): {"ppid": p["ppid"], "name": p["name"], "cpu": p["cpu"], "rss": int(p["rss_gb"] * 2 ** 30), "created": p["created"]}
             for pid, p in m["procs"].items()}
    seam(mp, "_scan", lambda: copy.deepcopy(procs))
    seam(mp, "_cpu_clock", lambda: tuple(m["clock"]))
    seam(mp, "_cmdline", lambda pid: CMDLINES.get(pid, ""))  # no host process reads: pids not listed have no command line
    seam(mp, "_exe", lambda pid: "")
    (cache / "machine-snap.json").write_text(json.dumps({"t": T0 - m["prev"]["t_ago"], "busy": m["prev"]["busy"],
                                                         "total": m["prev"]["total"], "p": m["prev"]["p"]}), encoding="utf-8")
    import psutil
    mp.setattr(psutil, "cpu_count", lambda *a, **k: m["cores"])
    mp.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(total=m["ram_total_gb"] * 2 ** 30,
                                                                  available=m["ram_available_gb"] * 2 ** 30))
    # agents: the monitor's session list, the transcripts it digests, the opencode server
    from tools.agentops import monitor, monitor_agents  # the agents part is read from monitor_agents (#885 E2b)
    a = load("agents.json")
    projects = tmp / "projects"
    copy_tree(FX / "projects", projects)
    mp.setattr(monitor_agents, "live_sessions_raw", lambda: copy.deepcopy(a["raw"]))
    mp.setattr(monitor_agents, "panel_agents", lambda live, **kw: {"sessions": copy.deepcopy(a["rows"])})
    mp.setattr(monitor_agents, "load_orch_state", lambda: {})
    mp.setattr(monitor_agents, "DEFAULT_PROJECTS_DIR", projects)
    mp.setattr(monitor_agents, "ROOT", root)
    mp.setattr(monitor.token_meter, "load_prices", lambda path: {})
    reading = json.loads((HERE / "fixtures" / "opencode_reading.json").read_text(encoding="utf-8"))
    oc_root = next(s["id"] for s in reading["sessions"] if not s.get("parentID"))
    registry = {oc_root: {"directory": str(root), "model": "gpt-5.6-terra", "claude_session": a["rows"][0]["session_id"]}}
    real_opencode = owned("opencode")
    seam(mp, "opencode", lambda: real_opencode(FakeClient(reading), registry=registry, now_ms=reading["recorded_ms"],
                                                launch_cache=cache / "oc_launch.json"))
    # the merge line
    mg = load("merge.json")
    durations = mg.pop("suite_durations")
    mp.setattr("tools.agentops.merge_status._log_facts", lambda path: (list(durations), None))
    # the laptop
    lp = load("laptop.json")
    (cache / "laptop.json").write_text(json.dumps(lp["cache"]), encoding="utf-8")
    pages = (FX / "inputs" / "tickets_pages.txt").read_text(encoding="utf-8")
    closed = load("closed.json")

    def fake_run(argv, **kw):
        a_ = list(argv)
        if a_[0] == "ssh":
            if laptop == "online":
                return subprocess.CompletedProcess(a_, 0, json.dumps(lp["host"]), "")
            return subprocess.CompletedProcess(a_, 255, "", lp["ssh_error"] + "\n")
        if a_[:3] == ["gh", "api", "graphql"]:
            return subprocess.CompletedProcess(a_, 0, pages, "")
        if a_[:3] == ["gh", "issue", "list"]:
            return subprocess.CompletedProcess(a_, 0, json.dumps(closed), "")
        if a_[-2:] == ["merge-status", "--json"]:
            return subprocess.CompletedProcess(a_, 0, json.dumps(mg), "")
        raise AssertionError(f"unstubbed subprocess call: {a_}")

    class FakeSsh:
        """#984: the laptop read is a `Popen` whose stdout/stderr are files: the stub fills them like ssh would."""

        def __init__(self, argv, stdin=None, stdout=None, stderr=None, **kw):
            assert argv[0] == "ssh", argv
            self.pid = 0
            if laptop == "online":
                stdout.write(json.dumps(lp["host"]).encode("utf-8"))
                self.rc = 0
            else:
                stderr.write((lp["ssh_error"] + "\n").encode("utf-8"))
                self.rc = 255

        def wait(self, timeout=None):
            return self.rc

    mp.setattr(subprocess, "run", fake_run)
    mp.setattr(subprocess, "Popen", FakeSsh)
    cost_world(mp, tmp, cache)
    orch_world(mp, tmp)
    return root


def cost_world(mp: pytest.MonkeyPatch, tmp: Path, cache: Path) -> None:
    """`slow`: the dashboard's cost panels and the token meter's scan, from fixtures/payload/inputs/cost.json."""
    from tools.agentops import monitor_dashboard as md
    c = load("cost.json")
    tm = md.token_meter
    sessions = tmp / "cost-projects"
    sessions.mkdir()
    for stem in c["titled"]:
        (sessions / f"{stem}.jsonl").write_text('{"type":"custom-title","customTitle":"x"}\n', encoding="utf-8")
    turns = [tm.Turn(session_id=t["session"], agent_id=t["agent"], agent_type=t["atype"], message_id=f"m{i}", model=t["model"],
                     timestamp=datetime.fromisoformat(t["ts"]), input_tokens=t["input"], cache_creation_input_tokens=t["cw"],
                     cache_read_input_tokens=t["cr"], output_tokens=t["out"], issue=t["issue"], title=t["title"], turn_index=i)
             for i, t in enumerate(c["turns"])]
    mp.setattr(md, "panel_cost", lambda days=1: copy.deepcopy(c["panel"]))
    mp.setattr(tm, "scan_projects_dir", lambda d, **kw: SimpleNamespace(turns=turns))
    mp.setattr(tm, "fetch_closed_issues", lambda *a, **k: {})
    mp.setattr(tm, "load_prices", lambda path: c["prices"])
    mp.setattr(tm, "DEFAULT_PROJECTS_DIR", sessions)
    mp.setattr(tm, "discover_main_transcripts", lambda d: sorted(sessions.glob("*.jsonl")))
    (cache / "monitor.jsonl").write_text("\n".join(map(json.dumps, c["monitor"])) + "\n", encoding="utf-8")


def orch_world(mp: pytest.MonkeyPatch, tmp: Path) -> None:
    """`orch`: a fake `token_meter` (collect imports it from the repo's scripts/ at call time)."""
    o = load("orch.json")
    prices = o["prices"]
    projects = tmp / "orch-projects"
    projects.mkdir()
    (tmp / "prices.json").write_text("{}", encoding="utf-8")
    by_path: dict[str, list] = {}
    titles: dict[str, str] = {}

    def turns_of(rows, model):
        return [SimpleNamespace(timestamp=datetime.fromisoformat(ts), input_tokens=i, cache_creation_input_tokens=cw,
                                output_tokens=out, context=i + cw + cr, model=model) for ts, i, cw, out, cr in rows]

    for s in o["sessions"]:
        p = projects / f"{s['stem']}.jsonl"
        p.write_text("{}\n", encoding="utf-8")
        by_path[p.name], titles[p.name] = turns_of(s["turns"], "m1"), s["title"]
        for sub in s["subs"]:
            sd = projects / s["stem"] / "subagents"
            sd.mkdir(parents=True, exist_ok=True)
            (sd / f"{sub['name']}.jsonl").write_text("{}\n", encoding="utf-8")
            by_path[f"{sub['name']}.jsonl"] = turns_of(sub["turns"], sub["model"])
            if sub["meta"]:
                (sd / f"{sub['name']}.meta.json").write_text(json.dumps(sub["meta"]), encoding="utf-8")

    def turn_cost(t, pr):
        price = pr.get(t.model)
        if price is None:
            return None
        return (t.input_tokens * price["input"] + t.cache_creation_input_tokens * price["cache_write"]
                + (t.context - t.input_tokens - t.cache_creation_input_tokens) * price["cache_read"]
                + t.output_tokens * price["output"]) / 1_000_000

    fake = types.ModuleType("token_meter")
    fake.DEFAULT_PRICES_PATH = tmp / "prices.json"
    fake.DEFAULT_PROJECTS_DIR = projects
    fake.load_prices = lambda path: prices
    fake.discover_main_transcripts = lambda d: sorted(d.glob("*.jsonl"))
    fake.parse_main_transcript = lambda p: SimpleNamespace(title=titles[p.name], turns=by_path[p.name])
    fake.parse_subagent_transcript = lambda p, meta: by_path[p.name]
    fake.turn_cost = turn_cost
    mp.setitem(sys.modules, "token_meter", fake)
    mp.setattr(sys, "path", list(sys.path))  # `orch` puts the repo's scripts/ first: put it back afterwards


def jsonable(payload, root: Path) -> dict:
    text = json.dumps(payload, sort_keys=True, indent=1, default=str, ensure_ascii=False)
    for spelling in (json.dumps(str(root))[1:-1], json.dumps(root.as_posix())[1:-1], str(root), root.as_posix()):
        text = text.replace(spelling, "<ROOT>")
    return text


def count_keys(x) -> int:
    if isinstance(x, dict):
        return sum(1 + count_keys(v) for v in x.values())
    if isinstance(x, list):
        return sum(count_keys(v) for v in x)
    return 0


@pytest.mark.parametrize("case,mode,laptop", CASES, ids=[c[0] for c in CASES])
def test_payload_matches_recording(case, mode, laptop, monkeypatch, tmp_path):
    root = build_world(monkeypatch, tmp_path, laptop)
    text = jsonable(PAYLOADS[mode](), root)
    target = EXPECTED / f"{case}.json"
    if os.environ.get("PAYLOAD_SNAPSHOT_REGEN"):
        EXPECTED.mkdir(exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8", newline="\n")
    got = json.loads(text)
    want = json.loads(target.read_text(encoding="utf-8"))
    assert sorted(got) == sorted(want), (sorted(set(got) ^ set(want)))
    for key in sorted(want):
        assert got[key] == want[key], f"{case}: key {key!r} differs"
    assert got == want


def test_fast_holds_every_section(monkeypatch, tmp_path):
    """The recording is not trivially empty: each section the add-on and the generic part fill holds something."""
    root = build_world(monkeypatch, tmp_path, "online")
    p = json.loads(jsonable(PAYLOADS["fast"](), root))
    for key in ("runs", "laptop", "readings", "status", "agents", "merge", "machine"):
        assert p.get(key), key
    assert p["runs"]["running"] and p["runs"]["queued"] and p["runs"]["recent"] and p["runs"]["history"]
    assert p["runs"]["running"][0]["progress"]["cells"], "a running PoB run with its cells"
    assert any(r.get("rows_total") for r in p["runs"]["history"]), "a finished run with its count"
    assert p["readings"]["rows"] and p["agents"][0]["subagents"]
    assert "runs_error" not in p and "agents_error" not in p and "machine_error" not in p and "merge_error" not in p


def test_offline_laptop_is_drawn_from_the_last_reading(monkeypatch, tmp_path):
    root = build_world(monkeypatch, tmp_path, "offline")
    p = json.loads(jsonable(PAYLOADS["fast"](), root))
    assert p["laptop"]["error"] and p["laptop"]["offline"]["verdict"] and p["laptop"]["last"]["running"]
    assert any(r.get("stale") for r in p["runs"]["running"])
