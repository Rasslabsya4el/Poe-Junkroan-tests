"""#518 unit 1: a job submitted with an explicit --host is fixed; the rebalancer never moves it."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import runs  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402
from tests.test_runs_rebalance import CMD, _fill_pc, age, rig  # noqa: E402


def _waiter(daemon, store, **kw):
    _fill_pc(daemon, store)
    job = store.submit(host="pc", priority="P2", tag="waiter", cmd=CMD, workers=1, **kw)
    age(daemon, job, 20)
    return job


def test_518_fixed_job_stays_logged_once(tmp_path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)
    job = _waiter(daemon, store, host_fixed=True)
    assert daemon._rebalancer.step() == []
    assert daemon._rebalancer.step() == []
    assert calls["submit"] == 0
    assert [m for m in logged if "host fixed" in m] == [f"rebalance: job {job.id} stays; host fixed by its submit"]


def test_518_unfixed_job_moves(tmp_path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)
    job = _waiter(daemon, store, host_fixed=False)
    assert daemon._rebalancer.step() == [job.id]


def test_518_store_line_roundtrip(tmp_path) -> None:
    path = tmp_path / "jobs.jsonl"
    store = Store(path)
    old = store.submit(host="pc", priority="P1", tag="old", cmd=CMD)
    new = store.submit(host="pc", priority="P1", tag="new", cmd=CMD, host_fixed=True)
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert all("host_fixed" not in r for r in lines if r["job"] == old.id)
    assert store.get(old.id).host_fixed is False
    assert store.get(new.id).host_fixed is True


def _submit(path: Path, monkeypatch, host_args: list[str], tag: str):
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    monkeypatch.setattr(runs, "finished_run_dir", lambda t, root: None)
    monkeypatch.setattr(runs.runs_placement, "pick_host", lambda *a, **k: "pc")
    monkeypatch.setattr(runs.runs_placement, "gather_states", lambda **k: {})
    rc = runs.main(["--store", str(path), "submit", *host_args, "--priority", "P1", "--issue", "1",
                    "--", "python", "-c", f"print('{tag}')"])
    assert rc == 0
    return Store(path).jobs()[-1]


def test_518_submit_explicit_host_is_fixed(tmp_path, monkeypatch) -> None:
    assert _submit(tmp_path / "j.jsonl", monkeypatch, ["--host", "pc"], "a").host_fixed is True


def test_518_submit_auto_and_omitted_not_fixed(tmp_path, monkeypatch) -> None:
    assert _submit(tmp_path / "j.jsonl", monkeypatch, ["--host", "auto"], "a").host_fixed is False
    assert _submit(tmp_path / "k.jsonl", monkeypatch, [], "b").host_fixed is False


def test_518_forwarded_auto_placement_not_fixed(tmp_path, monkeypatch) -> None:
    """The far side of an auto placement gets `--host X --host-auto-placed` and stores False."""

    assert _submit(tmp_path / "j.jsonl", monkeypatch, ["--host", "pc", "--host-auto-placed"], "a").host_fixed is False


# #594: the documented submit lines leave a ticket run movable; `--host pc` only with a --note reason.
_DOC_LINES = (ROOT / "docs/agents/local/orch.md", ROOT / "docs/agents/runs.md", ROOT / "scripts/runs.py")


def _submit_lines() -> list[str]:
    import re
    out = []
    for path in _DOC_LINES:
        out += re.findall(r"python scripts/runs\.py submit [^`\n]*", path.read_text(encoding="utf-8"))
    return out


def test_594_documented_orch_line_is_movable(tmp_path, monkeypatch) -> None:
    line = next(s for s in _submit_lines() if "--issue N" in s)
    assert "--host" not in line
    job = _submit(tmp_path / "j.jsonl", monkeypatch, ["--workers", "1"], "a")
    assert job.host_fixed is False and job.workers == 1


def test_594_pinned_lines_say_why() -> None:
    lines = _submit_lines()
    assert len(lines) >= 3
    pinned = [s for s in lines if "--host pc" in s or "--host laptop" in s]  # #1165: the weekly line is host laptop
    assert pinned and all("--note" in s for s in pinned), pinned
