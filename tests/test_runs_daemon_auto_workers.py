"""`--workers auto` (#570): the daemon sizes a job's PoB workers at START. PoB-free: fake launcher, slots, RAM."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from conftest import pc_only

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import runs  # noqa: E402
from junkroan.pob import slot_budget  # noqa: E402
from junkroan.runs import daemon as daemon_mod  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402

from test_runs_daemon import FakeLauncher, FakeSlots, make_daemon  # noqa: E402,F401
from test_runs_daemon import _isolated_daemon_status  # noqa: E402,F401  (autouse fixture of that file)

DAY_7 = slot_budget.Budget(period="day", hours=(8, 25), total=7, others=2, min_free_ram_gb=8.0)
NIGHT_10 = slot_budget.Budget(period="night", hours=(1, 8), total=10, others=5, min_free_ram_gb=3.0)
HOSTS = {"pc": {"ram_per_worker_gb": 1.4}}
AUTO_CMD = "python scripts/benchmark.py --tag t --workers auto"


def _daemon(tmp_path: Path, budget, free_ram: float, slots: FakeSlots | None = None, hosts=HOSTS):
    launcher = FakeLauncher()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, budget=budget, slots=slots, hosts_config=hosts)
    daemon._ram_reader = lambda: free_ram
    daemon.clock = _FakeClock()
    return daemon, store, launcher


@pytest.mark.parametrize(
    ("row", "budget", "busy", "free_ram", "expected"),
    [
        (1, DAY_7, 0, 18.4, 7),
        (2, DAY_7, 4, 18.4, 3),
        (3, DAY_7, 0, 9.5, 1),
        (4, NIGHT_10, 0, 20.0, 10),
    ],
)
def test_auto_resolves_to_the_free_room(tmp_path, row, budget, busy, free_ram, expected) -> None:
    slots = FakeSlots().foreign(busy) if busy else None
    daemon, store, launcher = _daemon(tmp_path, budget, free_ram, slots)
    job = store.submit(host="pc", priority="P2", tag="auto", cmd=AUTO_CMD, workers_auto=True)
    assert job.workers == 1 and job.workers_auto           # queued: it asks for 1 slot
    assert _tick_until_started(daemon, job.id)
    got = store.get(job.id)
    assert got.workers == expected
    assert f"--workers {expected}" in got.cmd and "auto" not in got.cmd
    assert launcher.started[0]["cmd"] == got.cmd
    assert got.workers_auto                                  # a requeue is resolved again


def test_5_a_fixed_workers_line_is_untouched(tmp_path: Path) -> None:
    daemon, store, launcher = _daemon(tmp_path, DAY_7, 18.4)
    cmd = "python scripts/benchmark.py --tag t --workers 2"
    job = store.submit(host="pc", priority="P2", tag="fixed", cmd=cmd, workers=2)
    daemon.tick()
    got = store.get(job.id)
    assert got.workers == 2 and got.cmd == cmd and launcher.started[0]["cmd"] == cmd


def test_6_the_record_the_command_and_status_show_the_resolved_count(tmp_path: Path, capsys) -> None:
    daemon, store, _ = _daemon(tmp_path, DAY_7, 18.4)
    runs.main(["--store", str(store.path), "status"])  # queued first: the column says auto
    job = store.submit(host="pc", priority="P2", tag="auto", cmd=AUTO_CMD, workers_auto=True)
    capsys.readouterr()
    runs.main(["--store", str(store.path), "status"])
    assert " auto " in capsys.readouterr().out
    daemon.tick()
    got = store.get(job.id)
    assert got.workers == 7 and "--workers 7" in got.cmd
    capsys.readouterr()
    runs.main(["--store", str(store.path), "status"])
    out = capsys.readouterr().out
    lines = out.splitlines()
    col = lines[0].split().index("workers")
    assert lines[2].split()[col] == "7"


def test_argv_job_is_rewritten_too(tmp_path: Path) -> None:
    daemon, store, launcher = _daemon(tmp_path, DAY_7, 18.4)
    argv = ["python", "scripts/benchmark.py", "--workers", "auto", "--tag", "t"]
    job = store.submit(host="pc", priority="P2", tag="auto", cmd=" ".join(argv), argv=argv, workers_auto=True)
    daemon.tick()
    got = store.get(job.id)
    assert got.argv == ("python", "scripts/benchmark.py", "--workers", "7", "--tag", "t")
    assert launcher.started[0]["cmd"] == list(got.argv)


def test_heavy_cap_another_five_worker_job_running_gives_four(tmp_path: Path) -> None:
    daemon, store, _ = _daemon(tmp_path, NIGHT_10, 40.0)
    heavy = store.submit(host="pc", priority="P2", tag="heavy", cmd="python x.py --workers 5", workers=5)
    daemon.tick()
    assert store.get(heavy.id).state == "running"
    job = store.submit(host="pc", priority="P2", tag="auto", cmd=AUTO_CMD, workers_auto=True)
    assert daemon.tick().started == [job.id]
    assert store.get(job.id).workers == 4


def test_a_host_without_ram_per_worker_resolves_by_slots_alone(tmp_path: Path) -> None:
    daemon, store, _ = _daemon(tmp_path, DAY_7, 0.1, hosts={"pc": {}})
    job = store.submit(host="pc", priority="P2", tag="auto", cmd=AUTO_CMD, workers_auto=True)
    daemon.tick()
    assert store.get(job.id).workers == 7


LAPTOP_3 = slot_budget.Budget(period="day", hours=(0, 24), total=3, others=0, min_free_ram_gb=1.0)
LAPTOP_HOSTS = {"pc": {"ram_per_worker_gb": 1.44}}


@pytest.mark.parametrize(
    ("row", "busy", "free_ram", "expected"),
    [
        (2, 0, 8.0, 3),   # #909 row 2: alone on a three-slot host with the RAM to hold it -> all three
        (3, 1, 8.0, 2),   # #909 row 3: one slot taken -> two
        (4, 0, 3.0, 1),   # the 2026-10-11 17:42 start: slots 3, ram 1 -> 1 (RAM, not slots, held it; #899 by design)
    ],
)
def test_909_a_three_slot_host_gives_all_free_slots_unless_ram_holds_them(tmp_path, row, busy, free_ram, expected) -> None:
    slots = FakeSlots().foreign(busy) if busy else None
    daemon, store, _ = _daemon(tmp_path, LAPTOP_3, free_ram, slots, hosts=LAPTOP_HOSTS)
    job = store.submit(host="pc", priority="P2", tag="auto", cmd=AUTO_CMD, workers_auto=True)
    assert _tick_until_started(daemon, job.id)
    got = store.get(job.id)
    assert got.workers == expected and f"--workers {expected}" in got.cmd


def _tick_until_started(daemon, job_id: str, *, limit_s: float = 180.0):
    """Tick every 10 s of a fake clock until the job starts; returns the seconds waited, or ``None``."""

    t0 = daemon.clock()
    while daemon.clock() - t0 <= limit_s:
        if job_id in daemon.tick().started:
            return daemon.clock() - t0 or 0.0001
        daemon.clock.advance(10.0)
    return None


@pytest.mark.parametrize(
    ("row", "busy", "free_at", "expected", "latest_s"),
    [
        (1, 0, lambda t: 3.0 if t < 5 else 8.0, 3, 60),   # #914: 3.0 GB at the start, 8.0 GB one tick later -> all three
        (2, 0, lambda t: 3.0, 1, 180),                    # 3.0 GB all ticks -> one worker, started within 3 minutes
        (3, 1, lambda t: 8.0, 2, 0),                      # one slot taken -> two, no wait (RAM holds the room)
    ],
)
def test_914_a_start_below_the_free_slots_waits_for_two_agreeing_readings(
        tmp_path, row, busy, free_at, expected, latest_s) -> None:
    slots = FakeSlots().foreign(busy) if busy else None
    daemon, store, _ = _daemon(tmp_path, LAPTOP_3, 0.0, slots, hosts=LAPTOP_HOSTS)
    daemon._ram_reader = lambda: free_at(daemon.clock() - daemon.clock.t0)
    job = store.submit(host="pc", priority="P2", tag="auto", cmd=AUTO_CMD, workers_auto=True)
    waited = _tick_until_started(daemon, job.id)
    assert waited is not None and waited <= max(latest_s, 0.0001)
    assert store.get(job.id).workers == expected


class _FakeClock:
    def __init__(self) -> None:
        self.t0 = self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pc_only
def test_submit_reads_workers_from_the_command(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(runs.runs_pin_ref, "missing_script", lambda *a, **k: None)  # #877 rule 4 is not this test's subject: b.py is a stand-in
    path = tmp_path / "jobs.jsonl"
    base = ["--store", str(path), "submit", "--issue", "1", "--host", "pc", "--priority", "P2"]
    assert runs.main([*base, "--", "python", "b.py", "--workers", "auto"]) == 0
    a = Store(path).get(capsys.readouterr().out.strip())
    assert a.workers_auto and a.workers == 1
    assert runs.main([*base, "--", "python b.py --workers 3"]) == 0
    b = Store(path).get(capsys.readouterr().out.strip())
    assert not b.workers_auto and b.workers == 3
    assert runs.main([*base, "--", "python", "b.py"]) == 0
    c = Store(path).get(capsys.readouterr().out.strip())
    assert not c.workers_auto and c.workers == 1
    assert runs.main([*base, "--workers", "auto", "--", "python", "b.py"]) == 0
    d = Store(path).get(capsys.readouterr().out.strip())
    assert d.workers_auto
    assert runs.main([*base, "--workers", "0", "--", "python", "b.py"]) == 2


def test_import_queue_reads_auto(tmp_path: Path, capsys) -> None:
    path = tmp_path / "jobs.jsonl"
    queue = tmp_path / "queue.txt"
    queue.write_text("python scripts/benchmark.py --tag a --workers auto\n", encoding="utf-8")
    assert runs.main(["--store", str(path), "import-queue", "--queue", str(queue)]) == 0
    capsys.readouterr()
    (job,) = Store(path).jobs()
    assert job.workers_auto and job.workers == 1


def test_declared_workers() -> None:
    d = daemon_mod.declared_workers
    assert d("x --workers auto") == "auto" and d("x --workers=4") == 4 and d("x") is None
    assert d(None, ["x", "--workers=auto"]) == "auto" and d(None, ["x", "--workers", "2"]) == 2
