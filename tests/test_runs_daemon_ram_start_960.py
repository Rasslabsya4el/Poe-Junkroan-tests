"""#960: a job asking for more workers than free RAM holds starts NOW at the RAM bound, with the rest yielded.

Fake launcher, fake clock, fake RAM reader; no PobSession, no laptop. Laptop numbers: 1.44 GB per worker,
1 GB floor, 3 workers in total.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from junkroan.pob import slot_budget  # noqa: E402
from junkroan.runs import daemon as daemon_mod  # noqa: E402
from junkroan.runs import yield_plan as yield_mod  # noqa: E402

from test_runs_daemon import FakeLauncher, FakeSlots, make_daemon  # noqa: E402
from test_runs_daemon import _isolated_daemon_status  # noqa: E402,F401  (autouse fixture of that file)

BUDGET = slot_budget.Budget(period="day", hours=(0, 24), total=3, others=0, min_free_ram_gb=1.0,
                            strict_reserve=False)
HOSTS = {"pc": {"ram_per_worker_gb": 1.44, "spike": {"window_s": 300}}}
BENCH3 = "python scripts/benchmark.py --tag t --workers 3"
BENCH1 = "python scripts/benchmark.py --tag u --workers 1"
REPLAY3 = "python scripts/replay_bench.py --tag t --workers 3"
UNLISTED3 = "python scripts/unlisted_pool.py --tag t --workers 3"  # a worker pool that is not a yield reader (#958)


class SeeingLauncher(FakeLauncher):
    """Records the yield file as it is on disk at the moment the child is launched."""

    def __init__(self) -> None:
        super().__init__()
        self.yield_at_launch: list[int | None] = []

    def start(self, cmd, *, cwd, out, env):
        path = Path(env[yield_mod.ENV_VAR])
        self.yield_at_launch.append(yield_mod.read_yield(path) if path.is_file() else None)
        return super().start(cmd, cwd=cwd, out=out, env=env)


class Rig:
    def __init__(self, tmp_path: Path, free: float, budget=BUDGET) -> None:
        self.free = free
        self.t = 1_000_000.0
        self.launcher = SeeingLauncher()
        self.daemon, self.store, _ = make_daemon(tmp_path, launcher=self.launcher, budget=budget,
                                                 hosts_config=HOSTS)
        self.daemon._ram_reader = lambda: self.free
        self.daemon.clock = lambda: self.t
        self.logs: list[str] = []
        self.daemon.log = self.logs.append

    def submit(self, cmd: str, workers: int, tag: str = "j"):
        return self.store.submit(host="pc", priority="P2", tag=tag, cmd=cmd, workers=workers)

    def yield_of(self, job) -> int:
        return yield_mod.read_yield(self.daemon.yield_file(job.id))

    def state(self, job) -> str:
        return self.store.get(job.id).state


def test_row1_head_starts_at_the_ram_bound_with_the_rest_yielded(tmp_path: Path) -> None:
    rig = Rig(tmp_path, 3.67)
    job = rig.submit(BENCH3, 3)
    report = rig.daemon.tick()
    assert report.started == [job.id]
    assert rig.state(job) == "running"
    assert rig.yield_of(job) == 2
    assert json.loads(rig.daemon.yield_file(job.id).read_text(encoding="utf-8"))["ram_give"] == 2
    assert rig.launcher.yield_at_launch == [2]  # on disk BEFORE the child exists: no build above the bound
    assert rig.daemon.used_workers() == 1 and rig.daemon.job_slot_counts() == {job.id: 1}
    assert any(f"gate {job.id}: started at 1 of 3 workers, RAM" in line for line in rig.logs)
    # the yield survives the next pass (owner_pass has no reservation record) and nothing else starts
    rig.t += 10
    assert rig.daemon.tick().started == [] and rig.yield_of(job) == 2


def test_row2_the_yield_falls_as_free_ram_grows_to_zero_without_a_restart(tmp_path: Path) -> None:
    rig = Rig(tmp_path, 3.67)
    job = rig.submit(BENCH3, 3)
    assert rig.daemon.tick().started == [job.id]
    rig.t += 10
    rig.free = 4.0  # (4.0 - 1.44 young - 1) / 1.44 = 1: one more worker only
    rig.daemon.tick()
    assert rig.yield_of(job) == 1 and rig.daemon.used_workers() == 2
    rig.t += 10
    rig.free = 5.4  # the 2 workers are young too: (5.4 - 2.88 - 1) / 1.44 = 1
    rig.daemon.tick()
    assert rig.yield_of(job) == 0 and not rig.daemon.yield_file(job.id).exists()
    assert rig.daemon.used_workers() == 3 and rig.daemon.job_slot_counts() == {job.id: 3}
    assert len(rig.launcher.started) == 1 and rig.state(job) == "running"  # nothing stopped or restarted
    assert rig.daemon.room() == 0


def test_row2_one_pass_to_zero_when_free_ram_holds_both_missing_workers(tmp_path: Path) -> None:
    rig = Rig(tmp_path, 3.67)
    job = rig.submit(BENCH3, 3)
    assert rig.daemon.tick().started == [job.id]
    rig.t += 10
    rig.free = 5.4  # (5.4 - 1.44 young - 1) / 1.44 = 2
    rig.daemon.tick()
    assert rig.yield_of(job) == 0 and rig.daemon.used_workers() == 3
    assert len(rig.launcher.started) == 1


def test_growth_is_held_back_by_the_slots_another_run_took(tmp_path: Path) -> None:
    slots = FakeSlots()
    rig = Rig(tmp_path, 3.67)
    rig.daemon._slot_lister = slots
    job = rig.submit(BENCH3, 3)
    assert rig.daemon.tick().started == [job.id]
    rig.t += 400  # past the young window: the reading is the job's own
    rig.free = 9.0
    slots.foreign(1)  # a run the daemon did not start holds one of the 3 slots
    rig.daemon.tick()
    assert rig.yield_of(job) == 1 and rig.daemon.used_workers() == 2  # 3 - 1 job - 1 foreign = 1 grown


def test_row3_bound_zero_holds_it_as_today(tmp_path: Path) -> None:
    rig = Rig(tmp_path, 2.0)
    job = rig.submit(BENCH3, 3)
    assert rig.daemon.tick().started == []
    assert rig.state(job) == "queued" and not rig.launcher.started
    assert rig.daemon._gate_status[job.id] == {"gate": "ram", "detail": "RAM: holds 0 workers, need 3"}
    assert not rig.daemon.yield_file(job.id).exists()


def test_row4_a_later_job_never_starts_before_the_head(tmp_path: Path) -> None:
    rig = Rig(tmp_path, 3.67)
    first = rig.submit(BENCH3, 3, tag="first")
    second = rig.submit(BENCH1, 1, tag="second")
    report = rig.daemon.tick()
    assert report.started == [first.id]  # on main: [second.id]
    assert rig.state(second) == "queued"
    assert rig.daemon._gate_status[second.id]["gate"] == "ram"  # the first took the bound; none is left


def test_row5_a_command_that_is_not_a_yield_reader_is_held_and_blocks_later_jobs(tmp_path: Path) -> None:
    rig = Rig(tmp_path, 3.67)
    head = rig.submit(UNLISTED3, 3, tag="head")
    later = rig.submit(BENCH1, 1, tag="later")
    assert rig.daemon.tick().started == []  # on main: [later.id]
    assert rig.state(head) == "queued" and rig.state(later) == "queued"
    assert rig.daemon._gate_status[head.id]["gate"] == "ram"
    status = rig.daemon._gate_status[later.id]
    assert status["gate"] == "behind" and head.id in status["detail"]
    assert not rig.daemon.yield_file(head.id).exists()


def test_the_reader_list_is_one_constant_with_the_three_yield_readers() -> None:
    # #958: replay_bench and search read the yield too (limited_completions), so all three are readers
    assert daemon_mod.YIELD_READER_COMMANDS == ("scripts/benchmark.py", "scripts/replay_bench.py", "scripts/search.py")
    assert daemon_mod.reads_yield_file("python scripts/benchmark.py --workers 3")
    assert daemon_mod.reads_yield_file(r"python scripts\benchmark.py --workers 3")
    assert daemon_mod.reads_yield_file("python scripts/replay_bench.py --workers 3")
    assert daemon_mod.reads_yield_file("python scripts/search.py --workers 3")
    assert not daemon_mod.reads_yield_file("python scripts/other_script.py --workers 3")


def test_an_owner_reservation_adds_to_the_ram_yield_and_never_deletes_it(tmp_path: Path) -> None:
    rig = Rig(tmp_path, 3.67)
    job = rig.submit(BENCH3, 3)
    assert rig.daemon.tick().started == [job.id]
    reserved = slot_budget.Budget(period="day", hours=(0, 24), total=2, others=0, min_free_ram_gb=1.0,
                                  strict_reserve=False, reserved=1, reserved_until=None)
    rig.daemon._budget_loader = lambda: reserved
    rig.daemon.owner_pass()
    # the job allows 1 worker, the host fits 2: the owner gives nothing up; the RAM yield stays
    assert rig.yield_of(job) == 2
    rig.daemon._budget_loader = lambda: BUDGET
    rig.daemon.owner_pass()
    assert rig.yield_of(job) == 2


def test_a_restarted_daemon_adopts_the_job_with_its_ram_yield(tmp_path: Path) -> None:
    rig = Rig(tmp_path, 3.67)
    job = rig.submit(BENCH3, 3)
    assert rig.daemon.tick().started == [job.id]
    rig.daemon._active.clear()  # a new daemon process: no memory of the job
    assert rig.daemon.recover() == []
    active = rig.daemon._active[job.id]
    assert (active.workers, active.ram_give, active.asked) == (1, 2, 3)
    rig.daemon.owner_pass()
    assert rig.yield_of(job) == 2
