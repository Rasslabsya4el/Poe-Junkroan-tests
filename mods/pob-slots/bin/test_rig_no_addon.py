"""#796 unit 2 (row 3): the generic collector on a project that has no add-on.

A rig project = a temp git repo INSIDE this worktree (`.scratch796-rig-<pid>-<n>/`, removed by the test) with a
`config/orchestration.json` holding `repo` (a tracker stub), the `monitor_dashboard` key naming the stub package's cost
module (the cost section is read through that key), and NO `monitor.addon`. `collect.py` is copied into the
rig and run there as a program (`python driver.py <mode>`, cwd = the rig, no `MONITOR_ROOT`), so the project root
comes from the cwd. The driver stubs every outside source: `gh` and `ssh` calls (no network; each is logged) and the
project's `tools.agentops` package (the rig has none). Each mode must end rc 0; the union of the sections across
modes must be exactly agents, tickets, merge, cost, machine, plus `pipeline` (collect.py's core section, #1176) and `version`
(collect.py's own key, #157); none of the add-on's keys or words may appear.
The same run with `monitor.addon` set to this repo's add-on must show the add-on keys (the test sees a silent load).

    python -m pytest -q -s bin/test_rig_no_addon.py
"""
import itertools
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKTREE = HERE.parents[2]
ADDON = HERE.parent / "addon" / "addon.py"
MODES = ("fast", "tickets", "slow")
GENERIC = {"agents", "tickets", "merge", "cost", "machine"}
ADDON_KEYS = {"readings", "runs", "runs_error", "laptop", "status"}
ADDON_WORDS = re.compile(r"pob|build|laptop|junkroan|poe|readings|runs|queue", re.I)
_N = itertools.count()

DRIVER = '''
import json, os, runpy, subprocess, sys, types
from pathlib import Path

RIG = Path(__file__).resolve().parent
CP = subprocess.CompletedProcess
real_run = subprocess.run
NODE = {"state": "OPEN", "stateReason": None, "updatedAt": "2026-10-11T00:00:00Z", "createdAt": "2026-10-10T00:00:00Z",
        "author": {"login": "a"}, "blockedBy": {"nodes": []}}
PAGES = json.dumps({"data": {"repository": {"issues": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [
    {**NODE, "number": 1, "title": "goal", "labels": {"nodes": []}, "parent": None},
    {**NODE, "number": 2, "title": "kid", "labels": {"nodes": [{"name": "ready-for-agent"}]}, "parent": {"number": 1}}]}}}})


def fake_run(argv, *a, **kw):
    argv = [str(x) for x in argv]
    if argv[0] in ("gh", "ssh"):
        with open(RIG / "outside_calls.log", "a", encoding="utf-8") as f:
            f.write(" ".join(argv[:3]) + "\\n")
        if argv[:3] == ["gh", "api", "graphql"]:
            return CP(argv, 0, PAGES, "")
        if argv[:3] == ["gh", "issue", "list"]:
            return CP(argv, 0, "[]", "")
        return CP(argv, 255, "", "stub: no network")
    if argv[-2:] == ["merge-status", "--json"]:
        return CP(argv, 0, json.dumps({"at": "2026-10-11T12:00:00", "running": None, "waiting": [], "landed": []}), "")
    return real_run(argv, *a, **kw)


subprocess.run = fake_run


def mod(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


tm = mod("tools.agentops.token_meter", load_prices=lambda p: {}, DEFAULT_PRICES_PATH=RIG / "prices.json",
         DEFAULT_PROJECTS_DIR=RIG / "projects", discover_main_transcripts=lambda d: [],
         fetch_closed_issues=lambda *a, **k: {}, scan_projects_dir=lambda d, **kw: types.SimpleNamespace(turns=[]))
monitor = mod("tools.agentops.monitor", live_sessions_raw=lambda: [], DEFAULT_PRICES_PATH=RIG / "prices.json",
              DEFAULT_PROJECTS_DIR=RIG / "projects", ROOT=RIG, load_orch_state=lambda: {}, token_meter=tm,
              panel_agents=lambda live, **kw: {"sessions": []})
ma = mod("tools.agentops.monitor_agents", live_sessions_raw=lambda: [], DEFAULT_PRICES_PATH=RIG / "prices.json",
         DEFAULT_PROJECTS_DIR=RIG / "projects", ROOT=RIG, load_orch_state=lambda: {},
         panel_agents=lambda live, **kw: {"sessions": []}, _token_meter=lambda: tm)
dash = mod("tools.agentops.monitor_dashboard", token_meter=tm, panel_cost=lambda days=1: {"days": days, "total_usd": 0})
mod("tools.agentops.merge_status", FALLBACK_SUITE_S=300.0, _log_facts=lambda p: ([], None))
pkg = mod("tools.agentops", monitor=monitor, monitor_agents=ma, monitor_dashboard=dash)
pkg.__path__ = []
mod("tools", agentops=pkg).__path__ = []
# #1176: collect.py imports the core's pipeline section (core 21b4b257: monitor_pipeline, and gh_call with its util and
# core_format) from `tools.agentops`; the stub package has no path, so the core's own copies are loaded from the repo
# root (CORE) under their dotted names, dependencies first. The stub package and every other stub stay as they are.
import importlib.util as _iu
def _core(name):
    spec = _iu.spec_from_file_location("tools.agentops." + name, CORE / "tools" / "agentops" / (name + ".py"))
    mod_ = _iu.module_from_spec(spec)
    sys.modules["tools.agentops." + name] = mod_
    spec.loader.exec_module(mod_)
    setattr(pkg, name, mod_)
for _name in ("core_format", "util", "gh_call", "monitor_pipeline", "ticket_groups"):
    _core(_name)

sys.argv = [str(RIG / "bin" / "collect.py")] + sys.argv[1:]
runpy.run_path(str(RIG / "bin" / "collect.py"), run_name="__main__")
'''


# #1176: the repo root holds the core files the driver loads (tools/agentops/); a path, not a copy
DRIVER = DRIVER.replace("RIG = Path(__file__).resolve().parent\n",
                        "RIG = Path(__file__).resolve().parent\nCORE = Path(%r)\n" % str(WORKTREE))


def _rmtree(path: Path) -> None:
    def force(fn, p, exc):
        os.chmod(p, stat.S_IWRITE)
        fn(p)
    # #984: the add-on leaves a slow laptop ssh running on its own, writing into bin/.cache; stop it first
    try:
        pid = (json.loads((path / "bin" / ".cache" / "laptop.json").read_text(encoding="utf-8")).get("pending") or {}).get("pid")
    except (OSError, ValueError, AttributeError):
        pid = None
    if pid:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    shutil.rmtree(path, onerror=force)


def make_rig(config: dict) -> Path:
    rig = WORKTREE / f".scratch796-rig-{os.getpid()}-{next(_N)}"
    (rig / "config").mkdir(parents=True)
    (rig / "bin").mkdir()
    subprocess.run(["git", "init", "-q", str(rig)], check=True)
    (rig / "config" / "orchestration.json").write_text(json.dumps(config), encoding="utf-8", newline="\n")
    shutil.copy(HERE / "collect.py", rig / "bin" / "collect.py")
    (rig / "driver.py").write_text(DRIVER, encoding="utf-8", newline="\n")
    return rig


def run_modes(config: dict) -> dict:
    """{mode: (rc, stdout JSON, stderr tail), "outside": [gh/ssh calls]} of the collector run in a rig; the rig is removed."""
    rig = make_rig(config)
    try:
        env = {k: v for k, v in os.environ.items() if k != "MONITOR_ROOT"}
        env["PYTHONPATH"] = str(WORKTREE / "src")  # the add-on variant imports the project's `junkroan`
        out: dict = {}
        for mode in MODES:
            r = subprocess.run([sys.executable, str(rig / "driver.py"), mode], cwd=rig, env=env, capture_output=True,
                               text=True, encoding="utf-8", timeout=120)
            out[mode] = (r.returncode, json.loads(r.stdout) if r.stdout.strip() else None, r.stderr[-600:])
        log = rig / "outside_calls.log"
        out["outside"] = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        return out
    finally:
        _rmtree(rig)


def section_of(mode: str, key: str) -> str | None:
    """The generic section a top-level key of `mode`'s payload belongs to (`at` is a time stamp, not a section)."""
    if key == "at":
        return None
    if mode == "tickets":
        return "tickets"  # goals / loose / issues = the one tickets tree
    if mode == "slow":
        return "cost" if key.startswith("cost_") else key
    return key


def all_keys(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield str(k)
            yield from all_keys(v)
    elif isinstance(x, list):
        for v in x:
            yield from all_keys(v)


def test_rig_without_addon_gives_exactly_the_five_generic_sections():
    res = run_modes({"repo": "stub-owner/stub-repo", "monitor_dashboard": "tools.agentops.monitor_dashboard"})
    supplied: dict[str, set[str]] = {}
    for mode in MODES:
        rc, payload, err = res[mode]
        assert rc == 0, (mode, err)
        assert payload is not None, (mode, err)
        for key in payload:
            sec = section_of(mode, key)
            if sec:
                supplied.setdefault(sec, set()).add(mode)
        assert not [k for k in payload if k.endswith("_error")], (mode, payload)
        words = sorted({k for k in all_keys(payload) if ADDON_WORDS.search(k)})
        assert not words, (mode, "add-on words in keys", words)
    print()
    for sec in sorted(supplied):
        print(f"section {sec:8s} <- mode {', '.join(sorted(supplied[sec]))}")
    print(f"{len(supplied)} sections: {sorted(supplied)}; outside calls: {sorted(set(res['outside']))}")
    # the five generic sections, `pipeline` (collect.py's fast() puts it in every add-on-less payload, core 21b4b257)
    # and `version` (collect.py:981, #157: the orchestration version the collector itself writes, None in a rig)
    expected = GENERIC | {"pipeline", "version"}
    assert set(supplied) == expected, sorted(set(supplied) ^ expected)
    assert not (set(supplied) & ADDON_KEYS)
    assert not any(c.startswith("ssh") for c in res["outside"]), "no laptop call without an add-on"


def test_same_rig_with_the_repos_addon_gives_its_keys():
    res = run_modes({"repo": "stub-owner/stub-repo", "monitor": {"addon": str(ADDON)}})
    rc, payload, err = res["fast"]
    assert rc == 0, err
    got = ADDON_KEYS & set(payload)
    print(f"\nwith monitor.addon: add-on keys in fast = {sorted(got)}")
    assert {"readings", "laptop"} <= got, sorted(payload)
    assert "runs" in payload or "runs_error" in payload
