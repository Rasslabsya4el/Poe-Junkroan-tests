"""Remote hand-back failures feed the `host_unreachable` anomaly (#308): failures spanning 10 min raise it, 1 h cooldown,
a success resets. No real ssh, claude.exe or PoB."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from junkroan.runs import daemon as daemon_mod  # noqa: E402
from junkroan.runs.remote_store import RemoteStoreUnreachable  # noqa: E402
from test_runs_anomalies import make_guard  # noqa: E402
from test_runs_daemon import make_daemon  # noqa: E402


def _ts(text: str) -> float:
    return datetime.strptime(f"2026-09-29 {text}", "%Y-%m-%d %H:%M:%S").timestamp()


class Rig:
    def __init__(self, tmp_path: Path) -> None:
        self.clock = {"t": 0.0}
        self.guard, self.launcher = make_guard(tmp_path, clock=lambda: self.clock["t"])
        self.raised: list[tuple[float, str]] = []
        # #674: a raise is only recorded, so the raise is read where it is recorded
        self.guard._record_host_unreachable = lambda anomaly: self.raised.append((self.clock["t"], anomaly.key))

    def step(self, t: float, ok: bool) -> None:
        self.clock["t"] = t
        self.guard.note_handback("laptop", ok)
        self.guard.check()
        self.launcher.finish_all()  # the keymaster ends at once; `handled` must not be what bars a re-raise


def test_replay_of_the_2026_09_29_log_raises_nothing(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    for stamp in ("08:50:34", "08:51:36", "08:52:37", "08:53:41", "08:54:42", "08:56:15"):
        rig.step(_ts(stamp), False)
    assert rig.raised == []                                  # 5 min 41 s of failures
    t = _ts("08:57:15")
    while t < _ts("09:50:00"):
        rig.step(t, True)
        t += 60
    assert rig.raised == []                                  # the success reset the streak


def test_nine_minutes_none_ten_minutes_one(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    for t in (0.0, 180.0, 360.0, 540.0):
        rig.step(t, False)
    assert rig.raised == []
    rig.step(600.0, False)
    assert rig.raised == [(600.0, "host_unreachable:laptop")]


def test_a_success_restarts_the_span(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    for t, ok in [(0.0, False), (300.0, True), (360.0, False), (900.0, False), (959.0, False)]:
        rig.step(t, ok)
    assert rig.raised == []
    rig.step(960.0, False)
    assert rig.raised == [(960.0, "host_unreachable:laptop")]


def test_cooldown_of_one_hour_then_raised_again(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    for t in (0.0, 300.0, 600.0):
        rig.step(t, False)
    assert rig.raised == [(600.0, "host_unreachable:laptop")]
    for t in (900.0, 1200.0, 4199.0):
        rig.step(t, False)
    assert len(rig.raised) == 1
    rig.step(4200.0, False)
    assert rig.raised == [(600.0, "host_unreachable:laptop"), (4200.0, "host_unreachable:laptop")]


def test_through_the_daemon_ten_minutes_of_failed_passes_start_no_keymaster(tmp_path: Path) -> None:
    clock = {"t": 1000.0}
    guard, launcher = make_guard(tmp_path, clock=lambda: clock["t"])

    def reader(host_cfg):
        raise RemoteStoreUnreachable("timed out")

    daemon, _, _ = make_daemon(tmp_path, host="pc", hosts_config={"laptop": {"ssh": "laptop"}},
                               remote_store_reader=reader, remote_pass_seconds=0.0)
    daemon.anomaly_guard = guard
    daemon.clock = lambda: clock["t"]
    for _ in range(11):
        clock["t"] += 60
        assert daemon.remote_handback_pass() == []
    daemon._check_anomalies(daemon_mod.TickReport())
    assert launcher.started == []  # #674: a lost laptop link is recorded only
