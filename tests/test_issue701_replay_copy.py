"""#701 rows 2 and 3: a replay job is copied-then-moved to the laptop (fake laptop, no PoB, no ssh)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from junkroan.runs import gates
from junkroan.runs.rebalance import Rebalancer, cmd_option_values, replay_dirs
from junkroan.runs.store import Job
from tests.test_runs_rebalance import _fill_pc, age, rig

BASE = "20261010-0046-b632-loop-base-13842c0"
BUILDS = "20261005-1220-gate-20261005"
CMD = ("python scripts/replay_bench.py --builds artifacts/benchmark/%s/x.pob.txt --move loop "
       "--against b632-loop-base-13842c0 --workers 1" % BUILDS)


def _artifacts(tmp_path: Path) -> Path:
    art = tmp_path / "pc_artifacts"
    (art / "replay" / BASE).mkdir(parents=True)
    (art / "replay" / BASE / "results.json").write_text("[]", encoding="utf-8")
    (art / "replay" / "20260101-0000-b632-loop-base-13842c0").mkdir()
    (art / "benchmark" / BUILDS).mkdir(parents=True)
    return art


def _setup(tmp_path, monkeypatch, *, copy_ok=True, present=()):
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)
    daemon._gate_artifacts = _artifacts(tmp_path)
    held = {"laptop": set(present)}
    copies: list[str] = []

    def copy_dir(host, cfg, rel):
        copies.append(rel)
        if copy_ok:
            held[host].add(gates.dir_key(rel))
        return copy_ok

    daemon._rebalancer = Rebalancer(
        daemon, has_pin=lambda cfg, host, pin: True, submit_moved=daemon._rebalancer._submit_moved,
        gates_present=lambda host: held[host], newest_gate=lambda root: None, copy_dir=copy_dir)
    _fill_pc(daemon, store)
    job = store.submit(host="pc", priority="P2", tag="replay", cmd=CMD, workers=1)
    age(daemon, job, 20)
    return daemon, store, laptop, logged, calls, held, copies, job


def test_row2_copy_then_move(tmp_path, monkeypatch):
    daemon, store, laptop, logged, calls, held, copies, job = _setup(tmp_path, monkeypatch)
    daemon.tick()
    assert sorted(copies) == sorted([f"replay/{BASE}", f"benchmark/{BUILDS}"])
    assert held["laptop"] == {f"replay/{BASE}", BUILDS}
    assert store.get(job.id).state == "cancelled" and calls["submit"] == 1
    assert any(f"job {job.id} waited" in line and "moved to laptop" in line for line in logged)


def test_row2_present_dirs_are_not_copied(tmp_path, monkeypatch):
    daemon, store, laptop, logged, calls, held, copies, job = _setup(
        tmp_path, monkeypatch, present={f"replay/{BASE}", BUILDS})
    daemon.tick()
    assert copies == [] and calls["submit"] == 1


def test_row3_copy_failure_keeps_job_one_line_no_second_try(tmp_path, monkeypatch):
    daemon, store, laptop, logged, calls, held, copies, job = _setup(tmp_path, monkeypatch, copy_ok=False)
    second = store.submit(host="pc", priority="P2", tag="replay2", cmd=CMD, workers=1)
    age(daemon, job, 20)
    daemon.tick()
    assert store.get(job.id).state == "queued" and store.get(second.id).state == "queued"
    assert calls["submit"] == 0
    assert len(copies) == 1                                    # the second job does not retry the same dir
    assert len([l for l in logged if "failed" in l and "copy of" in l]) == 1  # one line per step


def test_row3_one_job_one_line(tmp_path, monkeypatch):
    daemon, store, laptop, logged, calls, held, copies, job = _setup(tmp_path, monkeypatch, copy_ok=False)
    daemon.tick()
    assert store.get(job.id).state == "queued"
    assert len(copies) == 1
    assert [l for l in logged if "copy of" in l] == [f"rebalance: job {job.id} stays; copy of {copies[0]} to laptop failed"]


def _job(cmd=None, argv=None):
    return SimpleNamespace(cmd=cmd, argv=argv)


def test_parser_forms():
    s = _job(cmd=CMD)
    assert cmd_option_values(s, "--against") == ["b632-loop-base-13842c0"]
    assert cmd_option_values(s, "--builds") == [f"artifacts/benchmark/{BUILDS}/x.pob.txt"]
    a = _job(cmd="x", argv=["python", "r.py", "--against=tag1", "--builds", "artifacts/benchmark/D/*.pob.txt"])
    assert cmd_option_values(a, "--against") == ["tag1"]
    assert cmd_option_values(a, "--builds") == ["artifacts/benchmark/D/*.pob.txt"]
    lst = _job(cmd=["python", "r.py", "--builds=artifacts/benchmark/D/x"])
    assert cmd_option_values(lst, "--builds") == ["artifacts/benchmark/D/x"]
    assert cmd_option_values(_job(cmd="python a.py"), "--against") == []


def test_replay_dirs_resolve_newest_and_direct_path(tmp_path):
    art = _artifacts(tmp_path)
    assert replay_dirs(_job(cmd=CMD), art) == [f"replay/{BASE}", f"benchmark/{BUILDS}"]
    direct = _job(cmd=f"python r.py --against {art / 'replay' / BASE}")
    assert replay_dirs(direct, art) == [f"replay/{BASE}"]
    assert replay_dirs(_job(cmd="python r.py --against nosuchtag"), art) is None
    assert replay_dirs(_job(cmd="python r.py"), art) == []


def test_daemon_copy_dir_transport(tmp_path, monkeypatch):
    daemon, store, laptop, logged, calls, held, copies, job = _setup(tmp_path, monkeypatch)
    scripts, argvs = [], []
    daemon._gate_run_on_host = lambda cfg, script: scripts.append(script) or SimpleNamespace(returncode=0)
    daemon._dir_copy_run = lambda argv, **kw: argvs.append(argv) or SimpleNamespace(returncode=0)
    daemon._gates_path = tmp_path / "gates.json"
    cfg = {"ssh": "laptop", "daemon_repo_path": r"C:\Coding\d"}
    assert daemon.copy_dir_to_host("laptop", cfg, f"replay/{BASE}")
    assert argvs[0][-1].endswith(f"artifacts/replay/{BASE}.partial")
    partial = chr(92).join(["C:", "Coding", "d", "artifacts", "replay", BASE + ".partial"])
    assert f"Rename-Item -LiteralPath '{partial}' -NewName '{BASE}'" in scripts[-1]
    assert gates.gates_present("laptop", daemon._gates_path) == {f"replay/{BASE}"}
    daemon._dir_copy_run = lambda argv, **kw: SimpleNamespace(returncode=1)
    assert not daemon.copy_dir_to_host("laptop", cfg, f"benchmark/{BUILDS}")
    assert gates.gates_present("laptop", daemon._gates_path) == {f"replay/{BASE}"}
