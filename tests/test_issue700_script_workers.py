"""#700: a PoB script with a --workers option and none on the submit line is queued as `--workers auto`. PoB-free."""

from __future__ import annotations
from conftest import pc_only

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import runs  # noqa: E402
from junkroan.pob import slot_budget  # noqa: E402
from junkroan.runs import daemon as daemon_mod  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402

from test_runs_daemon_auto_workers import DAY_7, _daemon  # noqa: E402,F401
from test_runs_daemon import FakeLauncher, FakeSlots, make_daemon  # noqa: E402,F401
from test_runs_daemon import _isolated_daemon_status  # noqa: E402,F401  (autouse fixture of that file)

REPLAY = ["python", "scripts/replay_bench.py", "--builds", "X", "--move", "loop", "--seed", "1", "--tag", "t"]


def _submit(tmp_path: Path, capsys, *cmd: str):
    (tmp_path / "s").mkdir(exist_ok=True)
    path = tmp_path / "s" / "jobs.jsonl"
    base = ["--store", str(path), "submit", "--issue", "1", "--host", "pc", "--priority", "P2", "--"]
    assert runs.main([*base, *cmd]) == 0
    return Store(path).get(capsys.readouterr().out.strip())


@pc_only
def test_1_replay_without_workers_is_auto_and_starts_with_the_free_room(tmp_path: Path, capsys) -> None:
    job = _submit(tmp_path, capsys, *REPLAY)
    assert job.workers_auto and job.workers == 1 and "--workers auto" in (" ".join(job.argv or ()) or job.cmd)
    daemon, store, launcher = _daemon(tmp_path, DAY_7, 18.4)
    queued = store.submit(host="pc", priority="P2", tag="r", cmd=job.cmd, argv=list(job.argv) if job.argv else None,
                          workers=job.workers, workers_auto=job.workers_auto)
    assert daemon.tick().started == [queued.id]
    got = store.get(queued.id)
    assert got.workers == 7
    started = launcher.started[0]["cmd"]
    started = " ".join(started) if isinstance(started, list) else started
    assert "--workers 7" in started and "auto" not in started


@pc_only
def test_2_an_explicit_workers_is_kept(tmp_path: Path, capsys) -> None:
    job = _submit(tmp_path, capsys, *REPLAY, "--workers", "3")
    assert not job.workers_auto and job.workers == 3
    assert "auto" not in (" ".join(job.argv or ()) or job.cmd)
    one_line = _submit(tmp_path, capsys, "python scripts/replay_bench.py --builds Y --move loop --seed 2 --tag u --workers 2")
    assert not one_line.workers_auto and one_line.workers == 2


@pc_only
def test_3_a_script_without_a_workers_option_stays_one(tmp_path: Path, capsys) -> None:
    tool = ROOT / "scripts" / "token_meter.py"
    assert "add_argument(\"--workers\"" not in tool.read_text(encoding="utf-8")
    job = _submit(tmp_path, capsys, "python", "scripts/token_meter.py", "--orch-threshold")
    assert not job.workers_auto and job.workers == 1


def test_4_the_option_is_read_from_the_parsers() -> None:
    has = daemon_mod.script_has_workers_option
    for name in ("replay_bench", "benchmark", "search"):
        assert has(f"python scripts/{name}.py --tag t")
        assert has(None, ["python", "scripts" + chr(92) + f"{name}.py"])
    assert not has("python scripts/token_meter.py") and not has("python b.py") and not has("pytest tests -q")
    assert not has("python scripts/does_not_exist.py")
