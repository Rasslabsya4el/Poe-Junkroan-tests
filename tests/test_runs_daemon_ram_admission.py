"""#899: a PoB job starts only when free RAM holds its workers. Fake RAM reader, fake clock, no PoB."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from junkroan.pob import slot_budget  # noqa: E402

from test_runs_daemon import FakeLauncher, make_daemon  # noqa: E402
from test_runs_daemon import _isolated_daemon_status  # noqa: E402,F401  (autouse fixture of that file)

BUDGET = slot_budget.Budget(period="day", hours=(0, 24), total=10, others=0, min_free_ram_gb=8.0,
                            strict_reserve=False)
HOSTS = {"pc": {"ram_per_worker_gb": 1.4, "spike": {"window_s": 300}}}
AUTO = "python scripts/benchmark.py --tag t --workers auto"


class Rig:
    def __init__(self, tmp_path: Path, free: float, hosts=HOSTS) -> None:
        self.free = free
        self.t = 1_000_000.0
        self.launcher = FakeLauncher()
        self.daemon, self.store, _ = make_daemon(tmp_path, launcher=self.launcher, budget=BUDGET,
                                                 hosts_config=hosts)
        self.daemon._ram_reader = lambda: self.free
        self.daemon.clock = lambda: self.t
        self.logs: list[str] = []
        self.daemon.log = self.logs.append

    def auto(self, tag: str = "auto"):
        return self.store.submit(host="pc", priority="P2", tag=tag, cmd=AUTO, workers_auto=True)

    def fixed(self, n: int, tag: str = "fixed"):
        return self.store.submit(host="pc", priority="P2", tag=tag,
                                 cmd=f"python scripts/benchmark.py --tag t --workers {n}", workers=n)

    def state(self, job) -> str:
        return self.store.get(job.id).state


def settled_tick(rig):
    """#914: a RAM-bound auto start waits for a second agreeing reading one tick (10 s) later."""

    assert rig.daemon.tick().started == []
    rig.t += 10
    return rig.daemon.tick().started


def test_1_auto_job_with_9_gb_free_stays_queued(tmp_path: Path) -> None:
    rig = Rig(tmp_path, 9.0)
    job = rig.auto()
    assert rig.daemon.tick().started == []
    assert rig.state(job) == "queued" and not rig.launcher.started
    assert "RAM" in rig.daemon._gate_status[job.id]["detail"]
    assert rig.daemon.waits()[job.id]["kind"] == "ram"
    assert any(f"gate {job.id}: ram" in line and "RAM" in line for line in rig.logs)


def test_2_auto_job_with_12_2_gb_free_starts_with_3(tmp_path: Path) -> None:
    rig = Rig(tmp_path, 12.2)
    job = rig.auto()
    assert settled_tick(rig) == [job.id]
    assert rig.store.get(job.id).workers == 3


def test_3_second_auto_job_within_5_minutes_waits_for_the_first_to_grow(tmp_path: Path) -> None:
    rig = Rig(tmp_path, 12.2)
    a = rig.auto("a")
    assert settled_tick(rig) == [a.id]
    rig.t += 30
    b = rig.auto("b")
    assert rig.daemon.tick().started == []
    assert rig.state(b) == "queued"


def test_4_second_auto_job_after_5_minutes_starts(tmp_path: Path) -> None:
    rig = Rig(tmp_path, 12.2)
    a = rig.auto("a")
    settled_tick(rig)
    rig.t += 301
    b = rig.auto("b")
    assert settled_tick(rig) == [b.id]
    assert rig.store.get(b.id).workers == 3


def test_5_fixed_4_workers_with_12_2_gb_free_stays_queued(tmp_path: Path) -> None:
    # #960: a `scripts/benchmark.py` job (a yield reader) now starts at the RAM bound (tests/test_runs_daemon_
    # ram_start_960.py); a command that does not read the yield file is still held whole, as here.
    rig = Rig(tmp_path, 12.2)
    job = rig.store.submit(host="pc", priority="P2", tag="fixed", workers=4,
                           cmd="python scripts/unlisted_pool.py --tag t --workers 4")
    assert rig.daemon.tick().started == []
    assert rig.state(job) == "queued" and not rig.launcher.started
    assert rig.store.get(job.id).workers == 4  # never shrunk


def test_6_fixed_4_workers_with_13_7_gb_free_starts(tmp_path: Path) -> None:
    rig = Rig(tmp_path, 13.7)
    job = rig.fixed(4)
    assert rig.daemon.tick().started == [job.id]
    assert rig.store.get(job.id).workers == 4


def test_7_a_running_job_is_not_touched_when_free_ram_falls(tmp_path: Path) -> None:
    rig = Rig(tmp_path, 40.0)
    job = rig.fixed(10)
    assert rig.daemon.tick().started == [job.id]
    rig.free = 2.9
    rig.t += 600
    rig.daemon.tick()
    got = rig.store.get(job.id)
    assert got.state == "running" and got.workers == 10


def test_8_host_without_ram_per_worker_sizes_by_slots(tmp_path: Path) -> None:
    rig = Rig(tmp_path, 2.0, hosts={"pc": {}})
    job = rig.auto()
    assert rig.daemon.tick().started == [job.id]
    assert rig.store.get(job.id).workers == 10
    assert sum("no ram_per_worker_gb" in line for line in rig.logs) == 1
