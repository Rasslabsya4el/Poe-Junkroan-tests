"""#862 rules 1 and 4: a FAILED job's result comment names its held followers and a missing script."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from junkroan.runs import daemon as daemon_mod  # noqa: E402
from test_runs_daemon import FakeGh, FakeLauncher, make_daemon  # noqa: E402

MISSING_TAIL = "python.exe: can't open file 'repo/scripts/new_bench.py': [Errno 2] No such file or directory\n"


class ClockGh(FakeGh):
    def __init__(self, clock) -> None:
        super().__init__()
        self._clock = clock
        self.comment_at: list[float] = []

    def comment(self, issue: int, body: str) -> bool:
        self.comment_at.append(self._clock())
        return super().comment(issue, body)


def _failed_with_followers(tmp_path: Path, *, tail: str, seconds: float = 10.0):
    now = [1000.0]
    gh = ClockGh(lambda: now[0])
    launcher = FakeLauncher()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, gh=gh)
    daemon.clock = lambda: now[0]
    daemon._host_head = lambda: "0150ac84deadbeef"
    pred = store.submit(host="pc", priority="P2", tag="pred", cmd="python scripts/new_bench.py", issue=839)
    f1 = store.submit(host="pc", priority="P2", tag="f1", cmd="echo 1", after=[pred.id])
    f2 = store.submit(host="pc", priority="P2", tag="f2", cmd="echo 2", after=[pred.id])
    daemon.tick()
    out = Path(store.get(pred.id).out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(tail, encoding="utf-8")
    launcher.finish(launcher.started[0]["pid"], 2)
    failed_at = now[0]
    now[0] += daemon_mod.TICK_SECONDS
    daemon.tick()
    return daemon, store, gh, pred, (f1, f2), failed_at


def test_failed_job_comment_names_both_followers(tmp_path: Path) -> None:
    daemon, store, gh, pred, (f1, f2), _ = _failed_with_followers(tmp_path, tail=MISSING_TAIL)
    assert store.get(pred.id).state == "failed"
    assert len(gh.comments) == 1
    body = gh.comments[0][1]
    assert f1.id in body and f2.id in body
    assert "rc 2" in body and "predecessor" in body
    print(body)


def test_missing_script_line_after_fast_failure(tmp_path: Path) -> None:
    daemon, store, gh, pred, _, _ = _failed_with_followers(tmp_path, tail=MISSING_TAIL)
    job = store.get(pred.id)
    daemon._duration = lambda j: 10.0          # the record's start/end are the fake launcher's instant
    body = daemon.comment_body(job)
    assert "the script does not exist on this host at 0150ac84dead" in body
    assert "No such file or directory" in body        # the tail, 20 lines max, is still there


def test_no_missing_script_line_for_a_slow_or_ordinary_failure(tmp_path: Path) -> None:
    daemon, store, gh, pred, _, _ = _failed_with_followers(tmp_path, tail="Traceback: boom\n")
    job = store.get(pred.id)
    daemon._duration = lambda j: 10.0
    assert "does not exist on this host" not in daemon.comment_body(job)
    (Path(job.out)).write_text(MISSING_TAIL, encoding="utf-8")
    daemon._duration = lambda j: 300.0
    assert "does not exist on this host" not in daemon.comment_body(job)


def test_comment_within_five_minutes_of_the_failure(tmp_path: Path) -> None:
    _, _, gh, _, _, failed_at = _failed_with_followers(tmp_path, tail=MISSING_TAIL)
    assert len(gh.comment_at) == 1
    lag = gh.comment_at[0] - failed_at
    print(f"failure -> comment: {lag} s in the test clock")
    assert lag <= 300.0
