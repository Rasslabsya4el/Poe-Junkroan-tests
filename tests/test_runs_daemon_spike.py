"""The runs daemon obeys the spike ladder (#406 unit 3). Fake snapshot reader, fake clock, fake killer."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

from junkroan.runs import daemon as daemon_mod  # noqa: E402
from junkroan.runs import fillers as fillers_mod  # noqa: E402
from junkroan.runs.store import CLASS_FILLER  # noqa: E402
from test_runs_daemon import events, make_daemon  # noqa: E402

GROUPS = ("pob_counted", "pob_filler", "claude", "owner", "system", "other")
SPIKE = {"pc": {"spike": {"ram_free_mb_hard": 2000, "cpu_pct_soft": 90, "window_s": 300}}}
STEP = 60.0


@pytest.fixture(autouse=True)
def _isolated_daemon_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUNKROAN_DAEMON_STATUS_DIR", str(tmp_path / "daemon-status"))


def snap(free: float) -> dict:
    groups = {g: {"cpu_pct": 1.0, "rss_mb": 500.0, "count": 1} for g in GROUPS}
    groups["owner"]["rss_mb"] = 6000.0
    return {"ts": "t", "free_ram_mb": free, "total_ram_mb": 32000.0, "cpu_pct": 20.0,
            "groups": groups, "whole_suite_pytest": 0, "merge_suite_pytest": 0}


class Rig:
    def __init__(self, tmp_path: Path, hosts_config: dict) -> None:
        self.free = 8000.0
        self.killed: list[int] = []
        self.readers = 0
        self.daemon, self.store, _ = make_daemon(tmp_path, hosts_config=hosts_config)
        self.t = 1_000_000.0
        self.daemon.clock = lambda: self.t
        self.daemon._spike_reader = self._reader
        self.daemon._spike_killer = lambda pid: self.killed.append(pid) or True
        # #751 unit 4b: a filler beside a counted job is killed by the preempt pass on the first tick;
        # these tests are about the spike ladder's own stop, so that pass is off here.
        self.daemon.preempt_fillers_pass = lambda: []
        self.tmp = tmp_path

    def _reader(self, job_pids, prev):
        self.readers += 1
        return snap(self.free)

    def tick(self, n: int = 1) -> None:
        for _ in range(n):
            self.t += STEP
            self.daemon.tick()

    def submit(self, tag: str, **kw):
        return self.store.submit(host="pc", priority=kw.pop("priority", "P1"), tag=tag, cmd="echo " + tag, **kw)

    def state(self, job_id: str) -> str:
        return self.store.get(job_id).state


def start_two(rig: Rig):
    counted = rig.submit("counted")
    filler = rig.submit("filler", priority=daemon_mod.FILLER_PRIORITY, job_class=CLASS_FILLER)
    rig.daemon.fill()
    assert rig.state(counted.id) == "running" and rig.state(filler.id) == "running"
    return counted, filler


def test_sustained_ram_spike_walks_the_ladder_and_spares_counted(tmp_path: Path) -> None:
    rig = Rig(tmp_path, SPIKE)
    counted, filler = start_two(rig)
    rig.free = 1000.0
    rig.tick(6)                       # a full window of low RAM: step 1
    assert rig.daemon.spike_step == 1
    assert rig.state(filler.id) == "running"
    rig.tick(5)                       # a window later: step 2, the filler is stopped
    assert rig.daemon.spike_step == 2
    job = rig.store.get(filler.id)
    assert job.state == "stopped" and "stopped by spike: owner" in (job.reason or "")
    assert rig.killed == [int(job.pid)]
    rig.tick(5)
    assert rig.daemon.spike_step == 3
    queued2 = rig.submit("queued2")
    rig.tick(2)
    assert rig.state(queued2.id) == "queued"
    assert rig.state(counted.id) == "running"
    assert int(rig.store.get(counted.id).pid) not in rig.killed
    steps = [e for e in events(tmp_path) if e["kind"] == "spike_step"]
    assert [e["step"] for e in steps] == [1, 2, 3]
    assert steps[1]["cause"] == "owner" and steps[1]["free_ram_mb"] == 1000.0 and steps[1]["reason"]


def test_spike_over_steps_down_and_work_resumes(tmp_path: Path) -> None:
    rig = Rig(tmp_path, SPIKE)
    counted, _ = start_two(rig)
    rig.free = 1000.0
    rig.tick(16)
    assert rig.daemon.spike_step == 3
    queued = rig.submit("queued")
    rig.tick(2)
    assert rig.state(queued.id) == "queued"
    rig.free = 8000.0
    rig.tick(30)
    assert rig.daemon.spike_step == 0
    assert rig.state(queued.id) == "running"
    assert rig.state(counted.id) == "running"
    assert [e["step"] for e in events(tmp_path) if e["kind"] == "spike_step"] == [1, 2, 3, 2, 1, 0]


def test_ladder_off_without_spike_config(tmp_path: Path) -> None:
    for cfg in ({}, {"pc": {}}, {"pc": {"spike": {"ram_free_mb_hard": None, "cpu_pct_soft": None,
                                                    "window_s": None}}}):
        sub = tmp_path / str(len(str(cfg)))
        sub.mkdir()
        rig = Rig(sub, cfg)
        counted, filler = start_two(rig)
        rig.free = 100.0
        rig.tick(30)
        # The ladder never acts (step 0), but the load record (#760) still reads: one reading per 30 s
        # window, and this rig's tick is STEP = 60 s, so every one of the 30 ticks opens a new window.
        assert rig.daemon.spike_step == 0
        assert rig.readers == 30
        assert rig.state(filler.id) == "running" and rig.killed == []
        queued = rig.submit("queued")
        rig.tick()
        assert rig.state(queued.id) == "running"
        assert not [e for e in events(sub) if e["kind"] == "spike_step"]
