"""#756 rule 2 / row 3: a pin that origin lacks travels to the host that runs the job (PoB-free)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import run_queue  # noqa: E402
from junkroan.runs import pin_ref  # noqa: E402
from test_runs_daemon import FakeLauncher, make_daemon  # noqa: E402
from timing_bound import bound  # noqa: E402


def g(repo: Path, *args: str) -> str:
    res = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=str(repo),
                         capture_output=True, text=True, check=True)
    return res.stdout.strip()


def pins_on_origin(origin: Path) -> str:
    return g(origin, "for-each-ref", "refs/junkroan-pins/")


def world(tmp_path: Path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)
    pc = tmp_path / "pc"
    subprocess.run(["git", "clone", str(origin), str(pc)], check=True, capture_output=True)
    (pc / "a.txt").write_text("1")
    g(pc, "add", "."); g(pc, "commit", "-m", "one"); g(pc, "branch", "-M", "main"); g(pc, "push", "origin", "main")
    laptop = tmp_path / "laptop"
    subprocess.run(["git", "clone", str(origin), str(laptop)], check=True, capture_output=True)
    g(pc, "checkout", "-b", "wt-orch")
    (pc / "a.txt").write_text("2")
    g(pc, "commit", "-am", "branch only")
    return origin, pc, laptop, g(pc, "rev-parse", "HEAD")


def point_queue_at(monkeypatch, laptop: Path, tmp_path: Path) -> None:
    monkeypatch.setattr(run_queue, "ROOT", laptop)
    monkeypatch.setattr(run_queue, "SNAPSHOTS", tmp_path / "snaps")
    monkeypatch.setattr(run_queue, "SHARED_DIRS", ())


def test_row3_pin_travels_and_ref_is_gone_after_end(tmp_path, monkeypatch):
    # #844: pin_ref._git ends a git call at TIMEOUT (60 s) and returns a failed result, so on a busy PC a
    # slow `ls-remote` made fetch_pin False and make_snapshot None; the limit scales with the machine here.
    monkeypatch.setattr(pin_ref, "TIMEOUT", bound(pin_ref.TIMEOUT, 1500.0))
    origin, pc, laptop, pin = world(tmp_path)
    assert g(pc, "branch", "-r", "--contains", pin) == ""
    ok, _ = pin_ref.push_pin(pc, pin[:7])
    assert ok and pin in pins_on_origin(origin)
    point_queue_at(monkeypatch, laptop, tmp_path)
    made = run_queue.make_snapshot("job-a", pin[:7])      # a short pin, as the queue gets it
    assert made is not None
    snap, _ = made
    assert g(snap, "rev-parse", "HEAD") == pin

    launcher = FakeLauncher()
    (tmp_path / "d").mkdir()
    daemon, store, queue = make_daemon(tmp_path / "d", launcher=launcher)
    job = store.submit(host="pc", priority="P1", tag="t", cmd="python scripts/benchmark.py --tag t", pin=pin)
    store.start(job.id, out=str(tmp_path / "o.out"), pid=None)
    queue.drop_pin_ref = lambda p: pin_ref.drop_pin(laptop, p)
    daemon._end(job.id, rc=0, out=tmp_path / "o.out")
    assert pins_on_origin(origin) == ""
    assert g(laptop, "for-each-ref", "refs/junkroan-pins/") == ""


def test_pin_ref_stays_while_another_unfinished_job_holds_it(tmp_path):
    origin, pc, laptop, pin = world(tmp_path)
    pin_ref.push_pin(pc, pin)
    (tmp_path / "d").mkdir()
    daemon, store, queue = make_daemon(tmp_path / "d")
    a = store.submit(host="pc", priority="P1", tag="a", cmd="python scripts/benchmark.py --tag a", pin=pin)
    store.submit(host="pc", priority="P1", tag="b", cmd="python scripts/benchmark.py --tag b", pin=pin)
    store.start(a.id, out=str(tmp_path / "o.out"), pid=None)
    queue.drop_pin_ref = lambda p: pin_ref.drop_pin(pc, p)
    daemon._end(a.id, rc=0, out=tmp_path / "o.out")
    assert pin in pins_on_origin(origin)


def test_pin_already_on_origin_pushes_nothing(tmp_path):
    origin, pc, laptop, pin = world(tmp_path)
    main_sha = g(pc, "rev-parse", "main")
    ok, msg = pin_ref.push_pin(pc, main_sha)
    assert ok and "nothing pushed" in msg
    assert pins_on_origin(origin) == ""


def test_pin_unreachable_anywhere_fetch_fails_and_reason_is_rule1(tmp_path, monkeypatch):
    origin, pc, laptop, pin = world(tmp_path)      # nothing pushed
    point_queue_at(monkeypatch, laptop, tmp_path)
    assert run_queue.make_snapshot("job-b", pin[:7]) is None
    assert "not on this host" in run_queue.LAST_SNAPSHOT_FAILURE
    assert pin[:7] in run_queue.LAST_SNAPSHOT_FAILURE
