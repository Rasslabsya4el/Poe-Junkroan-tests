"""Snapshot root outside artifacts/ and junction-safe walks (#360)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import run_queue  # noqa: E402

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="directory junctions are Windows-only")


def _junction(link: Path, target: Path) -> None:
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_snapshot_outside_artifacts_is_accepted(tmp_path):
    for d in ("var", "artifacts", "vendor"):
        (tmp_path / d).mkdir()
    snap = tmp_path / "snapshots" / "x"
    snap.mkdir(parents=True)
    made = []
    try:
        for d in ("var", "artifacts", "vendor"):
            assert run_queue.junction_target_refusal(snap / d, tmp_path / d, snap) == ""
            _junction(snap / d, tmp_path / d)
            made.append(snap / d)
            assert run_queue.junction_target_refusal(snap / d, tmp_path / d, snap) == ""
    finally:
        for link in made:
            os.rmdir(link)


def test_snapshot_under_artifacts_is_refused(tmp_path):
    (tmp_path / "artifacts").mkdir()
    snap = tmp_path / "artifacts" / "runs" / "snap" / "x"
    snap.mkdir(parents=True)
    link = snap / "artifacts"
    msg = run_queue.junction_target_refusal(link, tmp_path / "artifacts", snap)
    assert msg and str(link) in msg and str(tmp_path / "artifacts") in msg
    assert "lies inside its own target" in msg


def test_old_refusals_still_refuse(tmp_path):
    wt = tmp_path / "wt"
    (wt / "inner").mkdir(parents=True)
    assert run_queue.junction_target_refusal(tmp_path / "l1", wt / "inner", wt)
    (tmp_path / "l2" / "t").mkdir(parents=True)
    assert run_queue.junction_target_refusal(tmp_path / "l2", tmp_path / "l2" / "t", wt)


def test_walk_does_not_descend_junctions(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    (a / "f.txt").write_text("x")
    loop = a / "loop"
    _junction(loop, a)
    try:
        got = list(run_queue._walk(a))
        assert got.count(loop) == 1
        assert a / "f.txt" in got
        assert len(got) == 2
    finally:
        os.rmdir(loop)


def test_make_snapshot_uses_snapshots_root(tmp_path, monkeypatch):
    monkeypatch.setattr(run_queue, "ROOT", tmp_path)
    monkeypatch.setattr(run_queue, "SNAPSHOTS", tmp_path / "snapshots")
    monkeypatch.setattr(run_queue, "RUNS", tmp_path / "runs")
    (tmp_path / "runs").mkdir()
    calls = []

    def fake_git(*args):
        calls.append(args)
        rc = 0 if args[0] == "rev-parse" else 1
        return subprocess.CompletedProcess(args, rc, stdout="abc123\n", stderr="nope")

    monkeypatch.setattr(run_queue, "_git", fake_git)
    assert run_queue.make_snapshot("x") is None
    add = next(c for c in calls if c[0] == "worktree")
    assert str(tmp_path / "snapshots" / "x") in add
    assert (tmp_path / "snapshots").is_dir()
    assert run_queue.SNAPSHOTS == tmp_path / "snapshots"
