"""#728: the cheap PoB-share read (`pob_cpu_pct`) equals the snapshot's number; snapshot() is unchanged."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import machine_load  # noqa: E402
from junkroan.pob import slot_budget  # noqa: E402
from junkroan.runs import load_groups  # noqa: E402

JOB = 5000
NCPU = 12


def _row(pid, ppid, name="x.exe", cmd=(), user="PC\\owner", cpu=0.0):
    return {"pid": pid, "ppid": ppid, "name": name, "cmdline": list(cmd), "username": user,
            "session": 1, "cpu_s": cpu, "rss_mb": 10.0, "cwd": None}


def _tables():
    t1 = [_row(pid, 1, cpu=float(pid % 7)) for pid in range(10, 1000)]
    t1.append(_row(JOB, 1, "python.exe", ["python", "run_job.py"], cpu=5.0))
    for i in range(12):
        t1.append(_row(5001 + i, JOB, "python.exe", ["python", "headless_runtime_worker.py"], cpu=10.0 + i))
    t1.append(_row(6000, 1, "claude.exe", ["claude"], cpu=1.0))
    for i in range(3):
        t1.append(_row(6001 + i, 6000, "pytest.exe", ["pytest", "tests/x.py"], cpu=2.0))
    t1.append(_row(6100, 1, "pytest.exe", ["python", "-m", "pytest"], cpu=3.0))
    assert len(t1) >= 1000
    t2 = [dict(r, cpu_s=r["cpu_s"] + (0.5 + 0.1 * (r["pid"] % 5))) for r in t1]
    return t1, t2


class FakeReader:
    def __init__(self, t1, t2):
        self.t1 = {r["pid"]: r for r in t1}
        self.t2 = {r["pid"]: r for r in t2}
        self.reads = {}
        self.calls = {"cmdline": 0, "memory_info": 0, "username": 0}

    def ppids(self):
        return {pid: r["ppid"] for pid, r in self.t1.items()}

    def cpu(self, pid):
        n = self.reads[pid] = self.reads.get(pid, 0) + 1
        return (self.t1 if n == 1 else self.t2)[pid]["cpu_s"]


def _clock():
    ticks = iter([0.0, 1.0])
    return lambda: next(ticks)


def test_pob_cpu_pct_equals_snapshot_and_reads_only_job_chain():
    t1, t2 = _tables()
    jobs = {JOB: "counted"}
    snap = load_groups.snapshot(
        proc_table=t2, job_pids=jobs, prev={"_cpu_s": {r["pid"]: r["cpu_s"] for r in t1}, "_wall": 0.0},
        wall=1.0, ncpu=NCPU)
    want = snap["groups"]["pob_counted"]["cpu_pct"] + snap["groups"]["pob_filler"]["cpu_pct"]
    assert want > 0
    fake = FakeReader(t1, t2)
    got = load_groups.pob_cpu_pct(jobs, ppids_reader=fake.ppids, cpu_reader=fake.cpu, ncpu=NCPU,
                                  clock=_clock(), sleep=lambda s: None)
    assert abs(got - want) < 0.01
    assert fake.calls == {"cmdline": 0, "memory_info": 0, "username": 0}
    assert set(fake.reads) == {JOB, *range(5001, 5013)}  # cpu_times only for the job chain
    assert all(n == 2 for n in fake.reads.values())


def test_pob_cpu_pct_counts_filler_and_ignores_vanished():
    t1, t2 = _tables()
    jobs = {JOB: "filler"}
    snap = load_groups.snapshot(
        proc_table=t2, job_pids=jobs, prev={"_cpu_s": {r["pid"]: r["cpu_s"] for r in t1}, "_wall": 0.0},
        wall=1.0, ncpu=NCPU)
    fake = FakeReader(t1, t2)
    inner = fake.cpu
    fake.cpu = lambda pid: None if pid == 5003 else inner(pid)
    got = load_groups.pob_cpu_pct(jobs, ppids_reader=fake.ppids, cpu_reader=fake.cpu, ncpu=NCPU,
                                  clock=_clock(), sleep=lambda s: None)
    assert snap["groups"]["pob_filler"]["cpu_pct"] > got > 0  # one worker skipped


def test_snapshot_groups_unchanged():
    t1 = [_row(1, 0, "init", user="NT AUTHORITY\\SYSTEM", cpu=0.0), _row(JOB, 1, cpu=0.0),
          _row(5001, JOB, cpu=0.0), _row(6000, 1, "claude.exe", cpu=0.0), _row(6001, 6000, cpu=0.0),
          _row(7000, 1, cpu=0.0)]
    t2 = [dict(r, cpu_s=r["cpu_s"] + 1.2) for r in t1]
    snap = load_groups.snapshot(proc_table=t2, job_pids={JOB: "counted"},
                                prev={"_cpu_s": {r["pid"]: r["cpu_s"] for r in t1}, "_wall": 0.0},
                                wall=1.0, ncpu=12)
    assert list(snap["groups"]) == list(load_groups.GROUPS)
    assert {g: v["count"] for g, v in snap["groups"].items()} == {
        "pob_counted": 2, "pob_filler": 0, "claude": 2, "owner": 1, "system": 1, "other": 0}
    assert snap["groups"]["pob_counted"]["cpu_pct"] == 20.0  # 2 procs * 1.2 s / 1 s / 12 * 100
    assert snap["groups"]["claude"]["cpu_pct"] == 20.0
    assert set(snap) >= {"ts", "free_ram_mb", "total_ram_mb", "cpu_pct", "groups", "whole_suite_pytest",
                         "merge_suite_pytest", "whole_suite_list", "pob_runtime_by_group", "_cpu_s", "_wall"}


def test_suite_workers_line_same_as_old_formula(monkeypatch):
    # the full run's launcher sets this for its whole process tree (#775): the test pins the stepped-down reading itself
    monkeypatch.delenv(machine_load.POB_NOT_STEPPED_DOWN_ENV, raising=False)
    class _Budget:
        merge_suite_reserve_gb = 2.0
        min_free_ram_gb = None  # #966: no run floor in this fake, so the count is the old formula's

        @staticmethod
        def limit_for(role):
            return 8

    budget = _Budget()
    monkeypatch.setattr(machine_load, "cpu_count", lambda: 12)
    monkeypatch.setattr(slot_budget, "available_ram_gb", lambda: 20.0)
    monkeypatch.setattr(load_groups, "pob_cpu_pct", lambda *a, **k: 30.0)
    import psutil
    monkeypatch.setattr(psutil, "cpu_percent", lambda interval=None: 80.0)
    assert machine_load.cpu_shares() == (80.0, 30.0)
    line = machine_load.suite_workers_line(budget)
    _, old = slot_budget.suite_workers_from_readings(
        12, 80.0, 20.0, budget.merge_suite_reserve_gb, slot_budget.SUITE_PER_WORKER_GB,
        budget.limit_for(slot_budget.ROLE_MERGE_SUITE), 30.0)
    assert line == old
