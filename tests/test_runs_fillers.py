"""Fillers on the daemon: the fakes the runs tests share, where a filler's exports go, the heavy rule and the
kill for any other job (issues #132, #517, #751). The old standing list is gone (#751).

Nothing real is touched: no PoB, no `git`, no `gh`, no `claude`, no live `var/` or `artifacts/runs/`.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from junkroan.pob import slot_budget  # noqa: E402
from junkroan.runs import anomalies as an  # noqa: E402
from junkroan.runs import daemon as daemon_mod  # noqa: E402
from junkroan.runs import fillers as fillers_mod  # noqa: E402
from junkroan.runs.store import CLASS_FILLER, Store  # noqa: E402

#: The PC's day budget of the spec: 7 slots, 2 for everyone else, strict reserve -> queue share 5.
BUDGET_DAY = slot_budget.Budget(period="day", hours=(0, 24), total=7, others=2,
                               min_free_ram_gb=0.0, strict_reserve=True)

#: The commit a pre-#751 filler was pinned to; the export-folder test reads its `benchmark.py` name format.
PIN = "42565a9"


def pinned_text(path_in_repo: str) -> str:
    """One file of the pinned commit, as text (nothing is imported). Skips when git cannot read it."""

    import subprocess

    try:
        result = subprocess.run(["git", "show", f"{PIN}:{path_in_repo}"], cwd=str(ROOT),
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=30)
    except Exception as exc:
        pytest.skip(f"cannot read {PIN}:{path_in_repo} ({exc!r})")
    if result.returncode != 0 or not (result.stdout or "").strip():
        pytest.skip(f"{PIN}:{path_in_repo} is not in this checkout")
    return result.stdout


def pinned_benchmark_text(tmp_path: Path | None = None) -> str:
    return pinned_text("scripts/benchmark.py")


@pytest.fixture(autouse=True)
def _isolated_daemon_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUNKROAN_DAEMON_STATUS_DIR", str(tmp_path / "daemon-status"))


# -- fakes -----------------------------------------------------------------------------------------

class FakeChild:
    def __init__(self, pid: int, launcher: "FakeLauncher") -> None:
        self.pid = pid
        self._launcher = launcher

    def poll(self) -> int | None:
        return self._launcher.exit_codes.get(self.pid)

    def close(self) -> None:
        pass


class FakeLauncher:
    def __init__(self) -> None:
        self.started: list[dict] = []
        self.exit_codes: dict[int, int] = {}
        self._next_pid = 7000

    def start(self, cmd: str, *, cwd: Path, out: Path, env: dict) -> FakeChild:
        self._next_pid += 1
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"fake run of {cmd}\n", encoding="utf-8")
        self.started.append({"cmd": cmd, "out": out, "pid": self._next_pid, "env": dict(env)})
        return FakeChild(self._next_pid, self)

    def alive(self, pid: int) -> bool:
        return True

    def finish(self, pid: int, rc: int = 0) -> None:
        self.exit_codes[pid] = rc


class FakeGh:
    def __init__(self) -> None:
        self.comments: list[tuple[int, str]] = []
        self.labels: list[tuple[int, str]] = []

    def comment(self, issue: int, body: str) -> bool:
        self.comments.append((issue, body))
        return True

    def add_label(self, issue: int, label: str) -> bool:
        self.labels.append((issue, label))
        return True

    def existing_comments(self, issue: int) -> list[str] | None:
        return []


class FakeQueueBackend:
    def __init__(self, runs_dir: Path) -> None:
        self._runs_dir = runs_dir
        self._names = 0

    def runs_dir(self) -> Path:
        return self._runs_dir

    def out_name(self, cmd: str, now: datetime, runs_dir: Path) -> str:
        self._names += 1
        return f"run{self._names}"

    def wants_snapshot(self, cmd: str) -> bool:
        return False

    def make_snapshot(self, name: str, pin: str):
        return None

    def drop_snapshot(self, snapshot: Path) -> None:
        pass

    def pid_alive(self, pid: int) -> bool:
        return True

    def find_run_dir(self, cmd: str, out: Path, started_at: float):
        return None

    def archive(self, cmd: str, run_dir, out: Path) -> int:
        return 0


class FakeSlots:
    """The rows `slot_budget.busy_slots()` would return; no test reads the real slot directory."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def __call__(self) -> list[dict]:
        return list(self.rows)

    def own(self, job_id: str, count: int) -> "FakeSlots":
        self.rows = [row for row in self.rows if row.get("job") != job_id]
        start = len(self.rows)
        self.rows += [{"slot": start + i + 1, "pid": 1000 + start + i, "role": slot_budget.ROLE_QUEUE,
                       "job": job_id, "cmd": "benchmark", "started": "", "age_seconds": 60.0}
                      for i in range(count)]
        return self


class FakeKeymasterCli:
    def __init__(self) -> None:
        self.started: list[an.Anomaly] = []

    def list_sessions(self) -> list[dict]:
        return []

    def start(self, anomaly: an.Anomaly) -> tuple[str, list[str]]:
        self.started.append(anomaly)
        return "km-1", []


# -- helpers ---------------------------------------------------------------------------------------


class Clock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_daemon(tmp_path: Path, *, host: str = "pc", budget=BUDGET_DAY, slots: FakeSlots | None = None,
                source=None, launcher: FakeLauncher | None = None,
                clock: Clock | None = None, guard=None,
                pob_builds: Path | None = None, hosts_config: dict | None = None,
                remote_store_reader=None, remote_status_reader=None,
                remote_pass_seconds: float = 0.0):
    store = Store(tmp_path / "jobs.jsonl")
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    daemon = daemon_mod.Daemon(
        store, host=host,
        launcher=launcher if launcher is not None else FakeLauncher(),
        gh=FakeGh(),
        queue=FakeQueueBackend(runs_dir),
        budget_loader=lambda: budget,
        slot_lister=slots if slots is not None else FakeSlots(),
        events_file=tmp_path / "events.jsonl",
        runs_dir=runs_dir,
        archive=False,
        snapshots=False,
        log=lambda message: None,
        clock=clock if clock is not None else Clock(),
        hosts_config=hosts_config if hosts_config is not None else {},
        remote_store_reader=remote_store_reader,
        remote_status_reader=remote_status_reader,
        remote_pass_seconds=remote_pass_seconds,
        anomaly_guard=guard,
        fillers=source,
        # the stand-in for the owner's PoB Builds folder
        pob_builds_dir=pob_builds if pob_builds is not None else tmp_path / "pob-builds",
    )
    return daemon, store



def running_filler(store: Store, launcher: FakeLauncher, daemon, tag: str = "filler-live",
                   workers: int = 5) -> str:
    """A filler job already running on this host, started the way the daemon starts one."""

    # #751 unit 4b: these old yield tests keep a filler beside another job; the preempt pass is off for them
    daemon.preempt_fillers_pass = lambda: []
    job = store.submit(host=daemon.host, priority="P2", tag=tag, workers=workers,
                       cmd=f"junkroan.exe scripts/benchmark.py --tag {tag}", job_class=CLASS_FILLER)
    daemon.fill()
    assert store.get(job.id).state == "running"
    return job.id


def fillers_in(store: Store) -> list[str]:
    return [job.tag for job in store.jobs() if job.is_filler]


# -- (c) the heavy rule does not count a filler as a holder -----------------------------------------

def test_c_a_heavy_job_is_not_held_by_a_live_heavy_filler(tmp_path: Path) -> None:
    slots = FakeSlots()
    launcher = FakeLauncher()
    daemon, store = make_daemon(tmp_path, slots=slots, launcher=launcher)
    filler = running_filler(store, launcher, daemon, workers=5)

    heavy = store.submit(host="pc", priority="P1", tag="heavy-real", workers=5, issue=61,
                         cmd="junkroan.exe scripts/benchmark.py --tag heavy-real")
    assert daemon.heavy_holder() is None          # the filler is no holder (#132 requirement 3)
    assert daemon._hold_for_heavy(store.get(heavy.id)) is None

    assert store.get(filler).state == "running"   # the tick that kills it is `preempt_fillers_pass` (below)


# -- (g) where a filler's builds go -----------------------------------------------------------------

def test_g_a_fillers_builds_are_moved_under_junkroan_fillers_and_no_other_run_is_touched(
    tmp_path: Path,
) -> None:
    """The folder the PINNED benchmark.py writes is moved from outside the run (it has no switch).

    The name is the one 42565a9's own `_pob_build_dir` builds, computed here by that very function
    loaded from the pinned commit -- so this test fails the day the name changes.
    """

    builds = tmp_path / "pob-builds"
    filler_run = builds / "benchmark 2026-09-27 1200-filler-new18-tpl-s7"
    other_run = builds / "benchmark 2026-09-27 1200-real-work"
    for folder in (filler_run, other_run):
        folder.mkdir(parents=True)
        (folder / "t329_slug s7.xml").write_text("<PathOfBuilding/>", encoding="utf-8")
    slots = FakeSlots()
    launcher = FakeLauncher()
    daemon, store = make_daemon(tmp_path, slots=slots, launcher=launcher, pob_builds=builds)
    filler = running_filler(store, launcher, daemon, tag="filler-new18-tpl-s7", workers=5)

    moved = daemon.sweep_filler_exports()

    target = builds / "fillers" / filler_run.name
    assert moved == [target]
    assert (target / "t329_slug s7.xml").read_text(encoding="utf-8") == "<PathOfBuilding/>"
    assert not filler_run.exists()
    assert f"Junkroan{os.sep}fillers{os.sep}" in str(
        Path("Junkroan") / fillers_mod.EXPORT_DIR_NAME / filler_run.name)
    # every other run is untouched, in place, with its file
    assert (other_run / "t329_slug s7.xml").is_file()
    assert not (builds / "fillers" / other_run.name).exists()

    # a build written after the move lands in the source folder again and is swept on the next tick
    filler_run.mkdir(parents=True)
    (filler_run / "t329_slug s8.xml").write_text("<PathOfBuilding2/>", encoding="utf-8")
    daemon.tick()
    assert (target / "t329_slug s8.xml").is_file()
    assert not filler_run.exists()

    # and once more when the job ends, even if no tick swept while it ran
    filler_run.mkdir(parents=True)
    (filler_run / "t329_slug s9.xml").write_text("<PathOfBuilding3/>", encoding="utf-8")
    launcher.finish(store.get(filler).pid, 0)
    daemon.tick()
    assert store.get(filler).state == "done"
    assert (target / "t329_slug s9.xml").is_file()
    assert not filler_run.exists()


def test_g_the_export_folder_name_is_the_one_the_pinned_benchmark_writes(tmp_path: Path) -> None:
    """`fillers.export_run_glob` must match 42565a9's own `_pob_build_dir` output, character for
    character: the sweep finds the folder by that name and nothing else."""

    import fnmatch
    import re

    text = pinned_benchmark_text(tmp_path)
    line = next(line for line in text.splitlines() if "Documents" in line and "Builds" in line)
    assert 'f"benchmark {stamp[:4]}-{stamp[4:6]}-{stamp[6:8]} {stamp[9:]}"' in line
    stamp = "20260927-1200-filler-core14-tpl-s7"
    name = f"benchmark {stamp[:4]}-{stamp[4:6]}-{stamp[6:8]} {stamp[9:]}"
    assert fnmatch.fnmatch(name, fillers_mod.export_run_glob("filler-core14-tpl-s7"))
    assert not fnmatch.fnmatch(name, fillers_mod.export_run_glob("filler-core14-loot-s7"))
    assert re.match(r"^benchmark \d{4}-\d{2}-\d{2} \d{4}-", name)


def test_the_monitor_marks_a_filler_row_and_shows_what_is_left(tmp_path: Path) -> None:
    from tools.agentops import monitor

    store = Store(tmp_path / "jobs.jsonl")
    filler = store.submit(host="pc", priority="P2", tag="filler-new18-tpl-s7", cmd="bench",
                          workers=5, job_class=CLASS_FILLER)
    real = store.submit(host="pc", priority="P1", tag="real-work", cmd="bench", issue=61)
    now = datetime.now(timezone.utc)

    rows = {row["tag"]: row for row in (monitor._job_row(job, now=now) for job in store.jobs())}
    assert rows["filler-new18-tpl-s7"]["filler"] is True
    assert rows["real-work"]["filler"] is False
    assert filler.id and real.id

    row = monitor._daemon_row("pc", {"pid": 4, "last_tick": now.isoformat(timespec="seconds"),
                                     "tick_seconds": 10.0, "running": [], "queued": 0,
                                     "fillers_left": 3, "fillers_hours_left": 28.0,
                                     "fillers_ran_out": True}, now=now, pid_alive=lambda pid: True)
    assert row["fillers"] == "3 / 28 h 00 min (ran out)"   # human_duration, never "100800 s"
    assert row["fillers_ran_out"] is True


# -- #413: the `pause` budget (queue 0, others 2) starts nothing ------------------------------------

def test_413_pause_starts_no_job_and_no_filler(tmp_path: Path) -> None:
    pause = slot_budget.Budget(period="day", hours=(0, 24), total=2, others=2, min_free_ram_gb=0.0,
                               strict_reserve=True, queue_slots=0)
    assert pause.limit_for(slot_budget.ROLE_QUEUE) == 0 and pause.limit_for(slot_budget.ROLE_OTHER) == 2
    launcher = FakeLauncher()
    daemon, store = make_daemon(tmp_path, budget=pause, source=fillers_mod.FillerSwitch(lambda: True), launcher=launcher)
    for workers, priority in ((1, "P0"), (2, "P1"), (5, "P2")):
        store.submit(host="pc", priority=priority, tag=f"j{workers}", cmd=f"echo {workers}", workers=workers)
    for _ in range(8):
        report = daemon.tick()
        assert report.started == [] and report.fillers == []
    assert launcher.started == []
    assert fillers_in(store) == []
    assert [job.state for job in store.jobs()] == ["queued"] * 3


def test_413_pause_does_not_borrow_past_the_share_for_a_p0_while_a_p2_runs(tmp_path: Path) -> None:
    open_budget = slot_budget.Budget(period="day", hours=(0, 24), total=7, others=2, min_free_ram_gb=0.0,
                                     strict_reserve=True)
    pause = slot_budget.Budget(period="day", hours=(0, 24), total=2, others=2, min_free_ram_gb=0.0,
                               strict_reserve=True, queue_slots=0)
    current = [open_budget]
    launcher = FakeLauncher()
    daemon, store = make_daemon(tmp_path, budget=open_budget, launcher=launcher)
    daemon.budget = lambda: current[0]
    store.submit(host="pc", priority="P2", tag="old", cmd="echo old", workers=1)
    assert len(daemon.tick().started) == 1
    current[0] = pause
    store.submit(host="pc", priority="P0", tag="urgent", cmd="echo urgent", workers=1)
    assert daemon.tick().started == []


# -- #517 unit 3: a P0/P1 job never waits behind a filler ---------------------------------------------

def _preempt_setup(tmp_path: Path, *, filler_workers: int, kill_ok: bool = True):
    launcher = FakeLauncher()
    daemon, store = make_daemon(tmp_path, launcher=launcher)
    daemon._spike_killer = lambda pid: kill_ok
    filler_id = running_filler(store, launcher, daemon, workers=filler_workers)
    del daemon.preempt_fillers_pass  # back to the real pass (#751 rule 5)
    return daemon, store, filler_id


@pytest.mark.parametrize("priority", ["P1", "P2"])
@pytest.mark.parametrize("filler_workers,job_workers", [(5, 5), (3, 5)])
def test_any_job_stops_the_filler_then_starts_next_tick(
        tmp_path: Path, filler_workers: int, job_workers: int, priority: str) -> None:
    daemon, store, filler_id = _preempt_setup(tmp_path, filler_workers=filler_workers)
    job = store.submit(host="pc", priority=priority, tag="j", cmd="echo j", workers=job_workers)
    assert daemon.preempt_fillers_pass() == [filler_id]
    assert store.get(filler_id).state == "stopped"
    assert "not a filler" in (store.get(filler_id).reason or "")
    assert store.get(job.id).state == "queued"
    assert daemon.fill() == [job.id]
    assert store.get(job.id).state == "running"


def test_filler_whose_kill_fails_stays_and_the_job_waits(tmp_path: Path) -> None:
    daemon, store, filler_id = _preempt_setup(tmp_path, filler_workers=5, kill_ok=False)
    job = store.submit(host="pc", priority="P1", tag="p1", cmd="echo p1", workers=5)
    assert daemon.preempt_fillers_pass() == []
    assert daemon.fill() == []
    assert store.get(filler_id).state == "running"
    assert store.get(job.id).state == "queued"

