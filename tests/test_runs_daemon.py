"""The runs daemon and `runs watch` (issue #48). No PoB, no real `gh`, no real process launch.

Every collaborator that touches the world is faked: the launcher (no child process), `gh` (no
network), the clock, and `run_queue.py`'s snapshot side (no git worktree, no junction -- CLAUDE.md
"Worktrees hold junctions"). What is NOT faked is which run_queue.py functions the daemon's own
default backend calls: `test_queue_backend_calls_run_queue_by_import` pins them to the real module.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest
from conftest import pc_only

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import runs  # noqa: E402
from junkroan.pob import slot_budget  # noqa: E402
from junkroan.runs import daemon as daemon_mod  # noqa: E402
from junkroan.runs import hosts as runs_hosts  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402

# The machine budget of the spec: 7 slots, 2 for everyone else, strict reserve on -> the queue's
# share is 5 (slot_budget.Budget.limit_for("queue") == total - others).
BUDGET_7_2 = slot_budget.Budget(
    period="day", hours=(0, 24), total=7, others=2, min_free_ram_gb=0.0, strict_reserve=True,
)


@pytest.fixture(autouse=True)
def _isolated_daemon_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test in this file gets its own `daemon-<host>.json` directory (issue #73): a real
    daemon status file on the machine running the suite must never be read by a test."""

    monkeypatch.setenv("JUNKROAN_DAEMON_STATUS_DIR", str(tmp_path / "daemon-status"))


# -- fakes ---------------------------------------------------------------------------------------

class FakeChild:
    def __init__(self, pid: int, launcher: "FakeLauncher") -> None:
        self.pid = pid
        self._launcher = launcher
        self.closed = False

    def poll(self) -> int | None:
        return self._launcher.exit_codes.get(self.pid)

    def close(self) -> None:
        self.closed = True


class FakeLauncher:
    """Records every start; a child exits only when the test says so (`finish(pid, rc)`)."""

    def __init__(self) -> None:
        self.started: list[dict] = []
        self.exit_codes: dict[int, int] = {}
        self.dead_pids: set[int] = set()
        self._next_pid = 4000

    def start(self, cmd: str, *, cwd: Path, out: Path, env: dict) -> FakeChild:
        self._next_pid += 1
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"fake run of {cmd}\n", encoding="utf-8")
        self.started.append({"cmd": cmd, "cwd": cwd, "out": out, "env": dict(env), "pid": self._next_pid})
        return FakeChild(self._next_pid, self)

    def alive(self, pid: int) -> bool:
        return pid not in self.dead_pids

    def finish(self, pid: int, rc: int = 0) -> None:
        self.exit_codes[pid] = rc


class FakeGh:
    """`comment` / `add_label` / `comments`, with a configurable number of leading failures."""

    def __init__(self, fail_comments: int = 0, fail_labels: int = 0,
                 existing_comments: dict[int, list[str]] | None = None) -> None:
        self.fail_comments = fail_comments
        self.fail_labels = fail_labels
        self.comments: list[tuple[int, str]] = []
        self.labels: list[tuple[int, str]] = []
        #: `issue -> [body, ...]`, what `comments(issue)` answers before/besides `self.comments`
        #: (issue #118: the "already posted, crashed before the mark" case).
        self._existing: dict[int, list[str]] = existing_comments or {}
        #: Run issues (#164): `(title, body, labels)` per create, `(parent, child)` per attach.
        self.fail_creates = 0
        self.created: list[tuple[str, str, list[str]]] = []
        self.attached: list[tuple[int, int]] = []

    def comment(self, issue: int, body: str) -> bool:
        if self.fail_comments > 0:
            self.fail_comments -= 1
            return False
        self.comments.append((issue, body))
        return True

    def add_label(self, issue: int, label: str) -> bool:
        if self.fail_labels > 0:
            self.fail_labels -= 1
            return False
        self.labels.append((issue, label))
        return True

    def create_issue(self, title: str, body: str, labels: list[str]) -> int | None:
        if self.fail_creates > 0:
            self.fail_creates -= 1
            return None
        self.created.append((title, body, list(labels)))
        return 900 + len(self.created)

    def add_sub_issue(self, parent: int, child: int) -> bool:
        self.attached.append((parent, child))
        return True

    def existing_comments(self, issue: int) -> list[str] | None:
        posted = [body for i, body in self.comments if i == issue]
        return self._existing.get(issue, []) + posted


class FakeQueueBackend:
    """run_queue.py's seam, faked: no git worktree, no junction, no archive, no benchmark scan."""

    def __init__(self, runs_dir: Path) -> None:
        self._runs_dir = runs_dir
        self.snapshots_made: list[tuple[str, str]] = []
        self.snapshots_dropped: list[Path] = []
        self.run_dir: Path | None = None
        self._names = 0

    def runs_dir(self) -> Path:
        return self._runs_dir

    def out_name(self, cmd: str, now: datetime, runs_dir: Path) -> str:
        self._names += 1
        return f"{now:%Y%m%d-%H%M}-run{self._names}"

    def wants_snapshot(self, cmd: str) -> bool:
        return True

    def make_snapshot(self, name: str, pin: str):
        self.snapshots_made.append((name, pin))
        if pin != "HEAD":   # a pinned job gets its snapshot or does not start (#756)
            return self._runs_dir / "snap" / name, pin
        return None  # "running from the live checkout", run_queue.py's own fallback

    def drop_snapshot(self, snapshot: Path) -> None:
        self.snapshots_dropped.append(snapshot)

    def save_snapshot_diff(self, snapshot: Path, job_id: str):
        return None

    def pid_alive(self, pid: int) -> bool:
        return True

    def find_run_dir(self, cmd: str, out: Path, started_at: float):
        return self.run_dir

    def archive(self, cmd: str, run_dir, out: Path) -> int:
        return 0


class FakeSlots:
    """The host's PoB slot semaphore, faked: the rows `slot_budget.busy_slots()` would return.

    No test may read the machine's real slot directory, so every daemon built here gets one of
    these -- empty unless the test hands it foreign or own rows (issue #82).
    """

    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = list(rows or [])

    def __call__(self) -> list[dict]:
        return list(self.rows)

    def foreign(self, count: int, *, role: str = slot_budget.ROLE_QUEUE, cmd: str = "run_queue.py line",
                job: str | None = None) -> "FakeSlots":
        """`count` slots held by something the daemon did not start.

        `job` is `None` by default (no run tag at all, e.g. a hand-run line); pass one to fake
        several slots "under one owner" (#117) -- another daemon's job, or a stand-in for a
        hand-run benchmark's worker pool grouped by its parent pid in production.
        """

        start = len(self.rows)
        self.rows += [
            {"slot": start + i + 1, "pid": 900 + i, "role": role, "job": job, "cmd": cmd,
             "started": "", "age_seconds": 60.0}
            for i in range(count)
        ]
        return self

    def own(self, job_id: str, count: int) -> "FakeSlots":
        """`count` slots whose PoB workers carry this daemon's job id (`JUNKROAN_RUNS_JOB`)."""

        start = len(self.rows)
        self.rows += [
            {"slot": start + i + 1, "pid": 1000 + i, "role": slot_budget.ROLE_QUEUE, "job": job_id,
             "cmd": "benchmark", "started": "", "age_seconds": 60.0}
            for i in range(count)
        ]
        return self


def make_daemon(tmp_path: Path, *, gh: FakeGh | None = None, launcher: FakeLauncher | None = None,
                budget: slot_budget.Budget = BUDGET_7_2, host: str = "pc",
                slots: FakeSlots | None = None, handback: str = "local",
                hosts_config: dict | None = None, remote_store_reader=None, remote_mark_posted=None,
                remote_pass_seconds: float = 60.0, remote_mark_run_issue=None):
    store = Store(tmp_path / "jobs.jsonl")
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(exist_ok=True)
    queue = FakeQueueBackend(runs_dir)
    daemon = daemon_mod.Daemon(
        store, host=host,
        launcher=launcher if launcher is not None else FakeLauncher(),
        gh=gh if gh is not None else FakeGh(),
        queue=queue,
        budget_loader=lambda: budget,
        slot_lister=slots if slots is not None else FakeSlots(),
        events_file=tmp_path / "events.jsonl",
        runs_dir=runs_dir,
        archive=False,
        log=lambda message: None,
        handback=handback,
        # `{}` by default (issue #118): no test may ever reach a real `ssh`/`gh` call through the
        # remote hand-back pass just because it left these unset -- a test that wants it exercised
        # passes its own fake `hosts_config`/`remote_store_reader`/`remote_mark_posted`.
        hosts_config=hosts_config if hosts_config is not None else {},
        remote_store_reader=remote_store_reader,
        remote_mark_posted=remote_mark_posted,
        remote_pass_seconds=remote_pass_seconds,
        run_issue_parent=404,
        remote_mark_run_issue=remote_mark_run_issue,
        # #760: the load record snapshots every tick; the real reader takes 6-23 s a call
        spike_reader=lambda job_pids, prev: {"ts": "2026-01-01T00:00:00", "free_ram_mb": 9999.0, "cpu_pct": 1.0, "groups": {}},
    )
    return daemon, store, queue


def events(tmp_path: Path) -> list[dict]:
    path = tmp_path / "events.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# -- requirement 1: room arithmetic ---------------------------------------------------------------

def test_room_is_the_queue_share_minus_running_workers(tmp_path: Path) -> None:
    """Budget 7/2 with strict reserve: the queue's share is 5 workers, not 7."""

    daemon, store, _ = make_daemon(tmp_path)
    assert BUDGET_7_2.limit_for(slot_budget.ROLE_QUEUE) == 5
    assert daemon.room() == 5


def test_two_jobs_of_two_workers_start_and_a_third_of_two_waits(tmp_path: Path) -> None:
    """2 + 2 = 4 <= 5 start; the third would make 6 > 5, so it stays queued (requirement 1)."""

    launcher = FakeLauncher()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher)
    first = store.submit(host="pc", priority="P2", tag="a", cmd="python scripts/benchmark.py --workers 2", workers=2)
    second = store.submit(host="pc", priority="P2", tag="b", cmd="python scripts/benchmark.py --tag b", workers=2)
    third = store.submit(host="pc", priority="P2", tag="c", cmd="python scripts/benchmark.py --tag c", workers=2)

    started = daemon.tick().started
    assert started == [first.id, second.id]
    assert len(launcher.started) == 2
    assert store.get(third.id).state == "queued"
    assert daemon.used_workers() == 4
    assert daemon.room() == 1

    # The third only starts once a running job frees its two workers.
    launcher.finish(launcher.started[0]["pid"], 0)
    started_again = daemon.tick().started
    assert started_again == [third.id]
    assert store.get(third.id).state == "running"


def test_next_job_order_is_priority_then_age(tmp_path: Path) -> None:
    """One worker each: P0 before P1 before the older P2 (store.next_job's order, used as is)."""

    daemon, store, _ = make_daemon(tmp_path)
    old = store.submit(host="pc", priority="P2", tag="old", cmd="echo old")
    mid = store.submit(host="pc", priority="P1", tag="mid", cmd="echo mid")
    top = store.submit(host="pc", priority="P0", tag="top", cmd="echo top")
    assert daemon.fill() == [top.id, mid.id, old.id]


# -- #82 requirement 1: the room counts every busy slot on the host, not only its own jobs ---------

#: Today's PC day budget with the strict reserve still off: the queue's limit is the whole 7.
BUDGET_7_2_OPEN = slot_budget.Budget(
    period="day", hours=(0, 24), total=7, others=2, min_free_ram_gb=0.0, strict_reserve=False,
)


def test_82_a_foreign_run_holding_five_of_seven_slots_leaves_room_for_two(tmp_path: Path) -> None:
    """The spec's case: a live `run_queue.py` line holds 5 of 7 -> a 5-worker job waits, a 2 starts.

    Nothing of this is the daemon's own work, so the old `limit_for(queue) - own workers` would have
    said "room for 7" and put 12 PoB workers on a 7-slot host.
    """

    launcher = FakeLauncher()
    slots = FakeSlots().foreign(5)
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, budget=BUDGET_7_2_OPEN, slots=slots)
    assert daemon.room() == 2

    big = store.submit(host="pc", priority="P2", tag="five", cmd="python scripts/benchmark.py --workers 5", workers=5)
    small = store.submit(host="pc", priority="P2", tag="two", cmd="python scripts/benchmark.py --workers 2", workers=2)
    # `five` is the head of the queue and does not fit. #834: `two` fits the room now and 2 + 5 <= 7, so the head
    # still fits when the foreign 5 end: `two` starts behind it, `five` keeps its place.
    assert daemon.tick().started == [small.id]
    assert store.get(big.id).state == "queued"
    assert store.get(small.id).state == "running"
    assert launcher.started[-1]["env"][slot_budget.JOB_ENV] == small.id


def test_82_the_strict_reserve_keeps_the_queue_at_five_and_ignores_the_others_share(tmp_path: Path) -> None:
    """`strict_reserve: true` (day 7/2): two `others` callers do NOT eat the queue's own 5 slots."""

    slots = FakeSlots().foreign(2, role=slot_budget.ROLE_OTHER, cmd="machine_load.py --need 1")
    daemon, store, _ = make_daemon(tmp_path, budget=BUDGET_7_2, slots=slots)
    assert BUDGET_7_2.limit_for(slot_budget.ROLE_QUEUE) == 5
    assert daemon.room() == 5                       # 7 total - 2 others = the queue's whole share

    job = store.submit(host="pc", priority="P2", tag="five", cmd="python scripts/benchmark.py --workers 5", workers=5)
    assert daemon.tick().started == [job.id]
    assert daemon.room() == 0


def test_82_with_the_strict_reserve_a_foreign_queue_run_of_five_leaves_nothing(tmp_path: Path) -> None:
    """Same 5 foreign slots, but taken in the QUEUE share: room 0, even for one worker."""

    slots = FakeSlots().foreign(5)
    daemon, store, _ = make_daemon(tmp_path, budget=BUDGET_7_2, slots=slots)
    assert daemon.room() == 0
    one = store.submit(host="pc", priority="P2", tag="one", cmd="echo one", workers=1)
    assert daemon.tick().started == []
    assert store.get(one.id).state == "queued"


def test_82_an_own_job_is_counted_once_whether_its_workers_took_their_slots_or_not(tmp_path: Path) -> None:
    """max(declared, held): 3 declared and 0 taken is still 3; 3 declared and 4 taken is 4."""

    launcher = FakeLauncher()
    slots = FakeSlots()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, budget=BUDGET_7_2_OPEN, slots=slots)
    job = store.submit(host="pc", priority="P2", tag="three", cmd="python scripts/benchmark.py --workers 3", workers=3)
    daemon.tick()

    assert daemon.used_workers() == 3 and daemon.room() == 4    # no slot taken yet: the promise counts
    slots.own(job.id, 3)
    assert daemon.used_workers() == 3 and daemon.room() == 4    # the same 3, not 6
    slots.own(job.id, 1)                                        # a fourth slot the job did not declare
    assert daemon.used_workers() == 4 and daemon.room() == 3


def test_82_a_foreign_slot_also_binds_the_graceful_priority_override(tmp_path: Path) -> None:
    """A P0 may pass the queue share while a worse-priority job runs, never past the host's total."""

    slots = FakeSlots().foreign(3)
    daemon, store, _ = make_daemon(tmp_path, budget=BUDGET_7_2_OPEN, slots=slots)
    store.submit(host="pc", priority="P2", tag="p2", cmd="echo p2", workers=2)
    daemon.tick()
    assert daemon.room() == 2                                  # 7 - 3 foreign - 2 own
    urgent = store.submit(host="pc", priority="P0", tag="p0", cmd="echo p0", workers=3)
    assert daemon.tick().started == []                         # 3 + 2 + 3 = 8 > total 7
    assert store.get(urgent.id).state == "queued"


def test_82_a_broken_slot_lister_never_kills_a_tick(tmp_path: Path) -> None:
    def boom() -> list[dict]:
        raise RuntimeError("the slot directory is gone")

    daemon, store, _ = make_daemon(tmp_path, budget=BUDGET_7_2_OPEN, slots=boom)
    job = store.submit(host="pc", priority="P2", tag="a", cmd="echo a", workers=1)
    assert daemon.tick().started == [job.id]


# -- requirement 1: graceful priority -------------------------------------------------------------

def test_a_p0_starts_beyond_room_while_p2_jobs_hold_slots_and_its_env_carries_p0(tmp_path: Path) -> None:
    """Two P2 jobs of 2 workers fill 4 of 5; a P0 of 2 starts anyway (6 <= total 7), env P0."""

    launcher = FakeLauncher()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher)
    store.submit(host="pc", priority="P2", tag="p2a", cmd="python scripts/benchmark.py --tag p2a", workers=2)
    store.submit(host="pc", priority="P2", tag="p2b", cmd="python scripts/benchmark.py --tag p2b", workers=2)
    daemon.tick()
    assert daemon.used_workers() == 4 and daemon.room() == 1

    urgent = store.submit(host="pc", priority="P0", tag="urgent", cmd="python scripts/benchmark.py --tag urgent", workers=2)
    started = daemon.tick().started
    assert started == [urgent.id]                      # started although 2 > room 1
    assert store.get(urgent.id).state == "running"
    assert daemon.used_workers() == 6                  # over the queue share, never over total 7
    env = launcher.started[-1]["env"]
    assert env["JUNKROAN_POB_PRIORITY"] == "P0"
    assert env["JUNKROAN_POB_ROLE"] == "queue"

    # Nothing was killed: both P2 jobs are still running.
    assert {job.state for job in store.jobs(state="running")} == {"running"}
    assert len(store.jobs(state="running")) == 3


def test_a_p2_never_starts_beyond_room(tmp_path: Path) -> None:
    """The override is for a strictly better priority only; equal priorities respect the share."""

    daemon, store, _ = make_daemon(tmp_path)
    store.submit(host="pc", priority="P2", tag="p2a", cmd="echo a", workers=3)
    store.submit(host="pc", priority="P2", tag="p2b", cmd="echo b", workers=2)
    daemon.tick()
    assert daemon.used_workers() == 5
    waiting = store.submit(host="pc", priority="P2", tag="p2c", cmd="echo c", workers=1)
    assert daemon.tick().started == []
    assert store.get(waiting.id).state == "queued"


def test_a_p0_still_stops_at_the_budget_total(tmp_path: Path) -> None:
    """The borrowed slots are the `others` share, not slots that do not exist: 7 is the ceiling."""

    daemon, store, _ = make_daemon(tmp_path)
    store.submit(host="pc", priority="P2", tag="big", cmd="echo big", workers=5)
    daemon.tick()
    assert daemon.used_workers() == 5
    too_big = store.submit(host="pc", priority="P0", tag="huge", cmd="echo huge", workers=3)
    assert daemon.tick().started == []                 # 5 + 3 = 8 > total 7
    assert store.get(too_big.id).state == "queued"


# -- #117: the heavy-job rule (GLOSSARY.md "Heavy job") -------------------------------------------

#: The night budget of the spec: total 10, `strict_reserve` off (the owner's "no", #117).
BUDGET_NIGHT_10 = slot_budget.Budget(
    period="night", hours=(1, 8), total=10, others=5, min_free_ram_gb=0.0, strict_reserve=False,
)


def test_117_a_two_heavy_jobs_queued_the_second_waits_for_the_first_to_end(tmp_path: Path) -> None:
    """Night budget 10 has room for two 5-worker jobs at once (5+5=10) -- the bug in #117.

    The rule holds the second until the first ends, though the room arithmetic alone would let it
    start beside it.
    """

    launcher = FakeLauncher()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, budget=BUDGET_NIGHT_10)
    first = store.submit(host="pc", priority="P2", tag="h1", cmd="python scripts/benchmark.py --workers 5", workers=5)
    second = store.submit(host="pc", priority="P2", tag="h2", cmd="python scripts/benchmark.py --workers 5", workers=5)

    assert daemon.tick().started == [first.id]
    assert store.get(second.id).state == "queued"
    assert daemon.tick().started == []                  # still held, room (5) would otherwise fit it
    assert store.get(second.id).state == "queued"

    launcher.finish(launcher.started[0]["pid"], 0)
    assert daemon.tick().started == [second.id]
    assert store.get(second.id).state == "running"


def test_117_b_a_heavy_job_live_a_two_worker_job_still_starts(tmp_path: Path) -> None:
    """The rule only ever holds a QUEUED heavy job; a light job behind it is unaffected."""

    launcher = FakeLauncher()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, budget=BUDGET_NIGHT_10)
    heavy = store.submit(host="pc", priority="P2", tag="heavy", cmd="python scripts/benchmark.py --workers 5", workers=5)
    daemon.tick()
    assert store.get(heavy.id).state == "running"

    light = store.submit(host="pc", priority="P2", tag="light", cmd="python scripts/benchmark.py --workers 2", workers=2)
    assert daemon.tick().started == [light.id]
    assert store.get(light.id).state == "running"


def test_117_c_a_foreign_owner_holding_five_slots_holds_a_heavy_job_three_does_not(tmp_path: Path) -> None:
    """"Under one owner": the foreign slots' shared `job` id is the owner (#117 pointer)."""

    (tmp_path / "five").mkdir()
    (tmp_path / "three").mkdir()
    five = FakeSlots().foreign(5, job="foreign-run-1")
    daemon, store, _ = make_daemon(tmp_path / "five", budget=BUDGET_NIGHT_10, slots=five)
    heavy = store.submit(host="pc", priority="P2", tag="heavy", cmd="python scripts/benchmark.py --workers 5", workers=5)
    assert daemon.tick().started == []
    assert store.get(heavy.id).state == "queued"

    three = FakeSlots().foreign(3, job="foreign-run-2")
    daemon2, store2, _ = make_daemon(tmp_path / "three", budget=BUDGET_NIGHT_10, slots=three)
    fits = store2.submit(host="pc", priority="P2", tag="heavy2", cmd="python scripts/benchmark.py --workers 5", workers=5)
    assert daemon2.tick().started == [fits.id]
    assert store2.get(fits.id).state == "running"


def test_117_d_a_higher_priority_heavy_job_does_not_borrow_past_the_rule(tmp_path: Path) -> None:
    """The heavy check comes before `_may_exceed_room`: a P0 heavy job still waits on a P2 one."""

    launcher = FakeLauncher()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, budget=BUDGET_NIGHT_10)
    first = store.submit(host="pc", priority="P2", tag="h1", cmd="python scripts/benchmark.py --workers 5", workers=5)
    daemon.tick()
    assert store.get(first.id).state == "running"

    urgent = store.submit(host="pc", priority="P0", tag="urgent", cmd="python scripts/benchmark.py --workers 5", workers=5)
    assert daemon.tick().started == []
    assert store.get(urgent.id).state == "queued"


def test_117_the_hold_log_line_fires_once_per_held_job_not_once_per_tick(tmp_path: Path) -> None:
    """Requirement 2: `held: heavy job <id> live on <host>` once when the hold starts."""

    logged: list[str] = []
    launcher = FakeLauncher()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, budget=BUDGET_NIGHT_10)
    daemon.log = logged.append

    first = store.submit(host="pc", priority="P2", tag="h1", cmd="python scripts/benchmark.py --workers 5", workers=5)
    daemon.tick()
    second = store.submit(host="pc", priority="P2", tag="h2", cmd="python scripts/benchmark.py --workers 5", workers=5)
    daemon.tick()
    daemon.tick()
    daemon.tick()

    held_lines = [line for line in logged if line.startswith("held: heavy job")]
    assert held_lines == [f"held: heavy job {first.id} live on {daemon.host}"]


def test_117_a_held_heavy_job_does_not_block_a_lighter_job_behind_it(tmp_path: Path) -> None:
    """Requirement 1: the held job keeps its place; a light job behind it starts if it fits.

    Live heavy job, then queued in order H2 (P1, heavy) and L (P2, 2 workers, room for it): after
    one tick L is running and H2 is still queued. When the live heavy job ends, H2 starts next --
    before any later-submitted job of the same priority -- because it kept its place in the queue.
    """

    launcher = FakeLauncher()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, budget=BUDGET_NIGHT_10)
    live = store.submit(host="pc", priority="P2", tag="live", cmd="python scripts/benchmark.py --workers 5", workers=5)
    daemon.tick()
    assert store.get(live.id).state == "running"

    h2 = store.submit(host="pc", priority="P1", tag="h2", cmd="python scripts/benchmark.py --workers 5", workers=5)
    light = store.submit(host="pc", priority="P2", tag="light", cmd="python scripts/benchmark.py --workers 2", workers=2)
    assert daemon.tick().started == [light.id]
    assert store.get(h2.id).state == "queued"
    assert store.get(light.id).state == "running"

    later = store.submit(host="pc", priority="P1", tag="later", cmd="python scripts/benchmark.py --workers 1", workers=1)
    launcher.finish(launcher.started[0]["pid"], 0)  # `live` ends
    assert daemon.tick().started == [h2.id, later.id]
    assert store.get(h2.id).state == "running"


# -- requirement 2: the environment, the out file, the snapshot, the pid --------------------------

def test_start_uses_run_queue_environment_out_file_snapshot_and_records_the_pid(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    daemon, store, queue = make_daemon(tmp_path, launcher=launcher)
    job = store.submit(host="pc", priority="P1", tag="bench", cmd="python scripts/benchmark.py --tag bench",
                       pin="abc1234", issue=48)
    daemon.tick()

    record = launcher.started[0]
    assert record["env"]["JUNKROAN_POB_ROLE"] == "queue"
    assert record["env"]["JUNKROAN_POB_PRIORITY"] == "P1"
    assert record["out"].parent == queue.runs_dir()
    assert record["out"].suffix == ".out"
    assert queue.snapshots_made and queue.snapshots_made[0][1] == "abc1234"   # the job's pinned commit

    stored = store.get(job.id)
    assert stored.state == "running"
    assert stored.pid == record["pid"]
    assert stored.out == str(record["out"])


# -- requirement 3: the hand-back -----------------------------------------------------------------

def test_end_writes_the_event_posts_one_comment_and_readds_the_label(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    gh = FakeGh()
    daemon, store, queue = make_daemon(tmp_path, launcher=launcher, gh=gh)
    run_dir = tmp_path / "bench-run"
    run_dir.mkdir()
    (run_dir / "report.md").write_text("| build | dps |\n", encoding="utf-8")
    queue.run_dir = run_dir

    job = store.submit(host="pc", priority="P1", tag="new18", cmd="python scripts/benchmark.py --tag new18", issue=48)
    daemon.tick()
    pid = launcher.started[0]["pid"]
    Path(launcher.started[0]["out"]).write_text("\n".join(f"line {i}" for i in range(40)) + "\n", encoding="utf-8")
    launcher.finish(pid, 0)
    report = daemon.tick()

    assert report.ended == [job.id]
    finished = store.get(job.id)
    assert finished.state == "done" and finished.rc == 0 and finished.posted is True

    assert len(gh.comments) == 1
    issue, body = gh.comments[0]
    assert issue == 48
    assert body.startswith(daemon_mod.RUNS_DAEMON_MARKER)  # issue #50: a dispatcher's marker
    assert job.id in body and "new18" in body and "rc 0" in body
    assert str(run_dir) in body and "report.md" in body
    assert "line 39" in body and "line 20" in body and "line 19" not in body  # the last 20 lines
    assert gh.labels == [(48, "ready-for-agent")]

    rows = events(tmp_path)
    assert rows[-1]["kind"] == "end" and rows[-1]["job"] == job.id
    assert rows[-1]["issue"] == 48 and rows[-1]["rc"] == 0


def test_the_comment_writes_the_duration_in_human_units(tmp_path: Path) -> None:
    """Principle 7: the comment says "47 min", never a big number of seconds."""

    from datetime import timedelta, timezone

    launcher = FakeLauncher()
    gh = FakeGh()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, gh=gh)
    job = store.submit(host="pc", priority="P1", tag="long", cmd="echo long", issue=7)
    # A `start` line written 47 minutes ago: the run the daemon adopts and then sees end.
    started = datetime.now(timezone.utc) - timedelta(minutes=47)
    store._write_line({"ts": started.isoformat(timespec="microseconds"), "job": job.id, "op": "start",
                       "out": str(tmp_path / "runs" / "long.out"), "run_dir": None, "pid": 5555})
    daemon.recover()
    launcher.dead_pids.add(5555)
    daemon.tick()

    assert gh.comments, "the comment must have been posted"
    body = gh.comments[0][1]
    assert "47 min" in body
    assert "2820" not in body   # never a big number of seconds (principle 7)


def test_a_failing_gh_comment_is_retried_next_tick_and_never_duplicated(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    gh = FakeGh(fail_comments=1)
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, gh=gh)
    job = store.submit(host="pc", priority="P1", tag="flaky", cmd="echo flaky", issue=12)
    daemon.tick()
    launcher.finish(launcher.started[0]["pid"], 1)

    daemon.tick()                                        # the end: gh refuses the comment
    assert gh.comments == [] and gh.labels == []
    assert store.get(job.id).state == "failed"
    assert store.get(job.id).posted is False             # nothing recorded, so nothing is lost

    handed = daemon.tick().handed_back                    # the retry
    assert handed == [job.id]
    assert len(gh.comments) == 1 and gh.labels == [(12, "ready-for-agent")]
    assert store.get(job.id).posted is True

    daemon.tick()                                        # and a third tick posts nothing more
    assert len(gh.comments) == 1
    assert len(gh.labels) == 1


def test_a_failing_label_retries_only_the_label(tmp_path: Path) -> None:
    """The comment is recorded the moment it is out, so the label's retry cannot duplicate it."""

    launcher = FakeLauncher()
    gh = FakeGh(fail_labels=1)
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, gh=gh)
    store.submit(host="pc", priority="P1", tag="labelless", cmd="echo x", issue=13)
    daemon.tick()
    launcher.finish(launcher.started[0]["pid"], 0)

    daemon.tick()
    assert len(gh.comments) == 1 and gh.labels == []
    daemon.tick()
    assert len(gh.comments) == 1                          # not posted twice
    assert gh.labels == [(13, "ready-for-agent")]


PAUSE_COMMENT = "**PAUSED on the owner's word, 2026-10-09 13:4x**\n\nThe brain took ready-for-agent off."


@pytest.mark.parametrize("paused", [True, False])
def test_654_a_paused_issue_gets_the_comment_but_no_label(tmp_path: Path, paused: bool) -> None:
    """#654 row 1: newest comment `**PAUSED...` -> result posted, label left off; without it -> labelled."""

    launcher = FakeLauncher()
    gh = FakeGh(existing_comments={609: ["**Parked (ORCH): the job is queued.**"]
                                   + ([PAUSE_COMMENT] if paused else [])})
    logs: list[str] = []
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, gh=gh)
    daemon.log = logs.append
    job = store.submit(host="pc", priority="P1", tag="pob609", cmd="echo x", issue=609)
    daemon.tick()
    launcher.finish(launcher.started[0]["pid"], 0)
    daemon.tick()
    daemon.tick()                                         # a retry tick adds nothing either way

    assert len(gh.comments) == 1 and gh.comments[0][0] == 609
    assert store.get(job.id).posted is True
    if paused:
        assert gh.labels == []
        assert f"handback {job.id}: #609 paused, label left off" in logs
    else:
        assert gh.labels == [(609, "ready-for-agent")]


def test_654_a_pause_older_than_a_human_comment_does_not_hold(tmp_path: Path) -> None:
    """Only the NEWEST non-hand-back comment counts; an earlier hand-back of another job is skipped."""

    other_handback = daemon_mod.RUNS_DAEMON_MARKER + "\njob `j-old` ended rc 0"
    launcher = FakeLauncher()
    gh = FakeGh(existing_comments={7: [PAUSE_COMMENT, other_handback]})
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, gh=gh)
    store.submit(host="pc", priority="P1", tag="a", cmd="echo x", issue=7)
    daemon.tick()
    launcher.finish(launcher.started[0]["pid"], 0)
    daemon.tick()
    assert gh.labels == []                                 # the pause is still the newest human word

    gh2 = FakeGh(existing_comments={8: [PAUSE_COMMENT, "Brain: resumed, go on."]})
    launcher2 = FakeLauncher()
    (tmp_path / "b").mkdir()
    daemon2, store2, _ = make_daemon(tmp_path / "b", launcher=launcher2, gh=gh2)
    store2.submit(host="pc", priority="P1", tag="b", cmd="echo x", issue=8)
    daemon2.tick()
    launcher2.finish(launcher2.started[0]["pid"], 0)
    daemon2.tick()
    assert gh2.labels == [(8, "ready-for-agent")]


def test_654_unreadable_comments_hold_the_label_for_the_retry(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    gh = FakeGh()
    answers = [None]
    real = gh.existing_comments
    gh.existing_comments = lambda issue: answers.pop(0) if answers else real(issue)
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, gh=gh)
    store.submit(host="pc", priority="P1", tag="c", cmd="echo x", issue=9)
    daemon.tick()
    launcher.finish(launcher.started[0]["pid"], 0)
    daemon.tick()
    assert len(gh.comments) == 1 and gh.labels == []      # gh could not answer: no label yet
    daemon.tick()
    assert len(gh.comments) == 1 and gh.labels == [(9, "ready-for-agent")]


def test_654_remote_handback_leaves_a_paused_issue_unlabelled(tmp_path: Path) -> None:
    remote = FakeRemoteHost(tmp_path, "laptop")
    job_id = _ended_job_with_handback(remote)
    gh = FakeGh(existing_comments={118: [PAUSE_COMMENT]})
    daemon, _, _ = make_daemon(
        tmp_path, gh=gh, host="pc", hosts_config={"laptop": {"ssh": "laptop"}},
        remote_store_reader=lambda host_cfg: remote.read(host_cfg),
        remote_mark_posted=remote.mark_posted, remote_pass_seconds=60.0,
    )

    assert daemon.remote_handback_pass() == [job_id]
    assert len(gh.comments) == 1 and gh.labels == []
    assert remote.marked == [job_id]


def test_a_job_without_an_issue_is_ended_without_any_gh_call(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    gh = FakeGh()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, gh=gh)
    job = store.submit(host="pc", priority="P2", tag="queue-line", cmd="echo x")
    daemon.tick()
    launcher.finish(launcher.started[0]["pid"], 0)
    daemon.tick()

    assert store.get(job.id).state == "done"
    assert gh.comments == [] and gh.labels == []
    assert events(tmp_path)[-1]["issue"] is None


# -- issue #118: `--handback remote` (the laptop has no `gh`) -------------------------------------

def test_118e_handback_remote_stores_the_body_and_calls_no_gh(tmp_path: Path) -> None:
    """Requirement 1 / numbers (e): `--handback remote` makes no `gh` call at all."""

    launcher = FakeLauncher()
    gh = FakeGh()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, gh=gh, host="laptop", handback="remote")
    job = store.submit(host="laptop", priority="P1", tag="lap", cmd="echo x", issue=118)
    daemon.tick()
    launcher.finish(launcher.started[0]["pid"], 0)
    report = daemon.tick()

    assert report.ended == [job.id]
    finished = store.get(job.id)
    assert finished.state == "done"
    assert finished.posted is False              # only the PC ever sets `posted`
    assert finished.handback_body is not None
    assert finished.handback_body.startswith(daemon_mod.RUNS_DAEMON_MARKER)
    assert job.id in finished.handback_body
    assert gh.comments == [] and gh.labels == []  # no `gh` call, ever


def test_501_rc_is_reading_headline(tmp_path: Path) -> None:
    daemon, store, _ = make_daemon(tmp_path, launcher=FakeLauncher(), gh=FakeGh(), host="pc")
    heads = {}
    for tag, flag in (("pin", True), ("plain", False)):
        job = store.submit(host="pc", priority="P1", tag=tag, cmd="echo x", rc_is_reading=flag)
        store.start(job.id)
        heads[tag] = daemon.comment_body(store.end(job.id, rc=1))
    assert "rc 1 (reading)" in heads["pin"]
    assert "rc 1 (failed)" in heads["plain"]


def test_118_handback_remote_never_retries_or_rewrites_the_stored_body(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    gh = FakeGh()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, gh=gh, host="laptop", handback="remote")
    store.submit(host="laptop", priority="P1", tag="lap2", cmd="echo x", issue=118)
    daemon.tick()
    launcher.finish(launcher.started[0]["pid"], 0)
    daemon.tick()
    job_id = store.jobs()[0].id
    first_body = store.get(job_id).handback_body

    daemon.tick()   # retry_handbacks runs again; must not touch the body or call gh
    assert store.get(job_id).handback_body == first_body
    assert gh.comments == [] and gh.labels == []


# -- issue #118 requirement 2: the PC's remote hand-back pass -------------------------------------

class FakeRemoteHost:
    """One other host's own job store + a fake `mark-posted` (no real ssh, ever)."""

    def __init__(self, tmp_path: Path, host: str) -> None:
        self.store = Store(tmp_path / f"{host}-jobs.jsonl")
        self.unreachable = False
        self.marked: list[str] = []
        self.mark_fails = 0

    def read(self, host_cfg) -> list:
        if self.unreachable:
            from junkroan.runs.remote_store import RemoteStoreUnreachable
            raise RemoteStoreUnreachable("laptop unreachable")
        return self.store.jobs()

    def mark_posted(self, host_cfg, host: str, job_id: str) -> bool:
        if self.mark_fails > 0:
            self.mark_fails -= 1
            return False
        self.store.mark_posted(job_id)
        self.marked.append(job_id)
        return True


def _ended_job_with_handback(remote: FakeRemoteHost, *, issue: int = 118) -> str:
    job = remote.store.submit(host="laptop", priority="P1", tag="lap", cmd="echo x", issue=issue)
    remote.store.start(job.id)
    remote.store.end(job.id, rc=0)
    remote.store.record_handback(job.id, f"{daemon_mod.RUNS_DAEMON_MARKER}\nrun for job `{job.id}`\n")
    return job.id


def test_118a_a_laptop_ended_job_is_posted_once_labelled_and_marked_posted(tmp_path: Path) -> None:
    gh = FakeGh()
    remote = FakeRemoteHost(tmp_path, "laptop")
    daemon, _, _ = make_daemon(
        tmp_path, gh=gh, host="pc", hosts_config={"laptop": {"ssh": "laptop"}},
        remote_store_reader=lambda host_cfg: remote.read(host_cfg),
        remote_mark_posted=remote.mark_posted, remote_pass_seconds=60.0,
    )
    job_id = _ended_job_with_handback(remote)

    done = daemon.remote_handback_pass()

    assert done == [job_id]
    assert len(gh.comments) == 1 and gh.comments[0][0] == 118
    assert gh.comments[0][1].startswith(daemon_mod.RUNS_DAEMON_MARKER) and job_id in gh.comments[0][1]
    assert gh.labels == [(118, "ready-for-agent")]
    assert remote.marked == [job_id]
    assert remote.store.get(job_id).posted is True


def test_118b_a_second_pass_posts_nothing(tmp_path: Path) -> None:
    gh = FakeGh()
    remote = FakeRemoteHost(tmp_path, "laptop")
    clock = {"t": 1_000_000.0}
    daemon, _, _ = make_daemon(
        tmp_path, gh=gh, host="pc", hosts_config={"laptop": {"ssh": "laptop"}},
        remote_store_reader=lambda host_cfg: remote.read(host_cfg),
        remote_mark_posted=remote.mark_posted, remote_pass_seconds=60.0,
    )
    daemon.clock = lambda: clock["t"]
    job_id = _ended_job_with_handback(remote)

    first = daemon.remote_handback_pass()
    assert first == [job_id]

    clock["t"] += 61.0   # past the 60 s gate: a real second pass, not a no-op from the gate itself
    second = daemon.remote_handback_pass()

    assert second == []
    assert len(gh.comments) == 1        # no duplicate comment
    assert len(gh.labels) == 1


def test_118c_an_existing_marker_comment_is_marked_posted_with_no_new_comment(tmp_path: Path) -> None:
    """A crash between an earlier post and its mark: the comment is already there."""

    remote = FakeRemoteHost(tmp_path, "laptop")
    job_id = _ended_job_with_handback(remote)
    existing_body = remote.store.get(job_id).handback_body
    gh = FakeGh(existing_comments={118: [existing_body]})
    daemon, _, _ = make_daemon(
        tmp_path, gh=gh, host="pc", hosts_config={"laptop": {"ssh": "laptop"}},
        remote_store_reader=lambda host_cfg: remote.read(host_cfg),
        remote_mark_posted=remote.mark_posted,
    )

    done = daemon.remote_handback_pass()

    assert done == [job_id]
    assert gh.comments == []            # no NEW comment
    assert remote.marked == [job_id]
    assert remote.store.get(job_id).posted is True


def test_118d_an_unreachable_host_is_skipped_then_posts_once_reachable(tmp_path: Path) -> None:
    gh = FakeGh()
    remote = FakeRemoteHost(tmp_path, "laptop")
    remote.unreachable = True
    clock = {"t": 1_000_000.0}
    daemon, _, _ = make_daemon(
        tmp_path, gh=gh, host="pc", hosts_config={"laptop": {"ssh": "laptop"}},
        remote_store_reader=lambda host_cfg: remote.read(host_cfg),
        remote_mark_posted=remote.mark_posted, remote_pass_seconds=60.0,
    )
    daemon.clock = lambda: clock["t"]
    job_id = _ended_job_with_handback(remote)

    first = daemon.remote_handback_pass()
    assert first == []
    assert gh.comments == [] and gh.labels == []   # no post, no anomaly raised

    remote.unreachable = False
    clock["t"] += 61.0
    second = daemon.remote_handback_pass()

    assert second == [job_id]
    assert len(gh.comments) == 1
    assert remote.store.get(job_id).posted is True


def test_118_the_remote_pass_is_gated_to_at_most_once_a_minute(tmp_path: Path) -> None:
    gh = FakeGh()
    remote = FakeRemoteHost(tmp_path, "laptop")
    clock = {"t": 1_000_000.0}
    calls = {"n": 0}

    def counting_read(host_cfg):
        calls["n"] += 1
        return remote.read(host_cfg)

    daemon, _, _ = make_daemon(
        tmp_path, gh=gh, host="pc", hosts_config={"laptop": {"ssh": "laptop"}},
        remote_store_reader=counting_read, remote_mark_posted=remote.mark_posted,
        remote_pass_seconds=60.0,
    )
    daemon.clock = lambda: clock["t"]

    daemon.remote_handback_pass()
    assert calls["n"] == 1
    clock["t"] += 5.0                      # still inside the 60 s gate
    daemon.remote_handback_pass()
    assert calls["n"] == 1                 # no second read at all
    clock["t"] += 56.0                     # now past it
    daemon.remote_handback_pass()
    assert calls["n"] == 2


# -- requirement 4: a daemon that died ------------------------------------------------------------

def test_a_running_job_whose_pid_is_gone_becomes_failed_with_a_comment(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    gh = FakeGh()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, gh=gh)
    job = store.submit(host="pc", priority="P1", tag="orphan", cmd="echo orphan", issue=48)
    store.start(job.id, out=str(tmp_path / "runs" / "orphan.out"), pid=9999)
    launcher.dead_pids.add(9999)

    lost = daemon.recover()

    assert lost == [job.id]
    finished = store.get(job.id)
    assert finished.state == "failed" and finished.rc is None
    assert finished.reason == "lost pid 9999"
    assert len(gh.comments) == 1 and "lost pid 9999" in gh.comments[0][1]
    assert gh.labels == [(48, "ready-for-agent")]
    row = events(tmp_path)[-1]
    assert row["kind"] == "end" and row["job"] == job.id and row["rc"] is None and row["issue"] == 48


def test_a_running_job_whose_pid_is_alive_is_adopted_not_failed(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    gh = FakeGh()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, gh=gh)
    job = store.submit(host="pc", priority="P1", tag="alive", cmd="echo alive", issue=48, workers=3)
    store.start(job.id, out=str(tmp_path / "runs" / "alive.out"), pid=8888)

    assert daemon.recover() == []
    assert store.get(job.id).state == "running"
    assert gh.comments == []
    assert daemon.used_workers() == 3                     # it still counts against the share

    launcher.dead_pids.add(8888)                          # it ends while adopted
    assert daemon.tick().ended == [job.id]
    assert store.get(job.id).state == "failed"


# -- requirement 5: runs watch --------------------------------------------------------------------

def test_watch_returns_on_the_first_new_event(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(json.dumps({"kind": "mode", "host": "pc"}) + "\n", encoding="utf-8")

    def append() -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"kind": "end", "job": "j-1", "rc": 0}) + "\n")

    # watch_next_event takes its start snapshot (daemon.py:3198) before its first sleep (daemon.py:3206); a wall-clock
    # Timer could fire before that snapshot on a loaded PC and the event would be "past" (#844). Append from the
    # first sleep call instead: the snapshot is certainly taken.
    appended = []

    def sleep_hook(_seconds: float) -> None:
        if not appended:
            appended.append(True)
            append()

    line = daemon_mod.watch_next_event(path, timeout=10.0, poll=0.01, sleep=sleep_hook)

    assert line is not None
    assert json.loads(line) == {"kind": "end", "job": "j-1", "rc": 0}   # the new line, not the old


def test_watch_gives_up_at_its_timeout(tmp_path: Path) -> None:
    assert daemon_mod.watch_next_event(tmp_path / "events.jsonl", timeout=0.05, poll=0.01) is None


def test_runs_watch_cli_prints_the_line_and_exits(tmp_path: Path, capsys) -> None:
    path = tmp_path / "events.jsonl"

    def append() -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"kind": "end", "job": "j-2", "rc": 1}) + "\n")

    timer = threading.Timer(0.05, append)
    timer.start()
    try:
        rc = runs.main(["--store", str(tmp_path / "jobs.jsonl"), "watch", "--events", str(path),
                        "--timeout", "10", "--poll", "0.01"])
    finally:
        timer.cancel()
    assert rc == 0
    assert json.loads(capsys.readouterr().out.strip()) == {"kind": "end", "job": "j-2", "rc": 1}


def test_runs_watch_cli_exits_3_on_timeout(tmp_path: Path, capsys) -> None:
    rc = runs.main(["--store", str(tmp_path / "jobs.jsonl"), "watch", "--events",
                    str(tmp_path / "events.jsonl"), "--timeout", "0.05", "--poll", "0.01"])
    assert rc == 3
    assert capsys.readouterr().out.strip() == ""


# -- requirement 1 / 6: the `workers` field and run_queue.py's own functions ----------------------

@pc_only
def test_submit_and_import_queue_read_the_worker_count(tmp_path: Path, capsys) -> None:
    store_path = tmp_path / "jobs.jsonl"
    rc = runs.main(["--store", str(store_path), "submit", "--issue", "1", "--host", "pc", "--priority", "P1",
                    "--workers", "5", "--", "python", "scripts/benchmark.py"])
    assert rc == 0
    job_id = capsys.readouterr().out.strip()
    assert Store(store_path).get(job_id).workers == 5

    queue = tmp_path / "queue.txt"
    queue.write_text(
        "python scripts/benchmark.py --tag a --workers 2\n"
        "python scripts/benchmark.py --tag b --workers=4\n"
        "python scripts/benchmark.py --tag c\n",
        encoding="utf-8",
    )
    assert runs.main(["--store", str(store_path), "import-queue", "--queue", str(queue)]) == 0
    capsys.readouterr()
    imported = {job.tag: job.workers for job in Store(store_path).jobs() if job.submitter == "import-queue"}
    assert sorted(imported.values()) == [1, 2, 4]


@pytest.mark.parametrize(
    ("cmd", "expected"),
    [
        ("python scripts/benchmark.py --workers 5", 5),
        ("python scripts/benchmark.py --workers=3", 3),
        ("python scripts/benchmark.py --seeds 3", 1),
        ("python scripts/benchmark.py --workers 0", 1),
    ],
)
def test_parse_workers(cmd: str, expected: int) -> None:
    assert daemon_mod.parse_workers(cmd) == expected


# -- issue #57 follow-up: `runs.py daemon` actually builds the anomaly guard ---------------------

class _RecordingDaemon:
    """Stands in for `runs_daemon.Daemon`: records the kwargs it was built with, runs zero ticks."""

    instances: list[dict] = []

    def __init__(self, store, host, **kwargs) -> None:
        self.store, self.host, self.kwargs = store, host, kwargs
        _RecordingDaemon.instances.append(kwargs)

    def budget(self):
        return BUDGET_7_2

    def run(self, *, ticks=None, interval=10.0, load_thread=False):
        return 0


def test_runs_daemon_cli_builds_a_guard_with_a_budget_checker_and_a_laptop_prober(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(daemon_mod, "Daemon", _RecordingDaemon)
    _RecordingDaemon.instances = []
    rc = runs.main(["--store", str(tmp_path / "jobs.jsonl"), "daemon", "--host", "pc", "--ticks", "0"])
    assert rc == 0
    kwargs = _RecordingDaemon.instances[-1]
    guard = kwargs["anomaly_guard"]
    assert guard is not None
    assert guard.budget_checker is not None
    assert guard.host_prober is not None                  # pc has an ssh route to the laptop
    assert guard.slot_lister is not None                   # issue #76: lease_overrun detection
    assert guard.reservation_lister is not None
    assert guard.host == "pc"                               # issue #120: job_wrong_host detection


def test_runs_daemon_cli_no_keymaster_builds_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daemon_mod, "Daemon", _RecordingDaemon)
    _RecordingDaemon.instances = []
    rc = runs.main(["--store", str(tmp_path / "jobs.jsonl"), "daemon", "--host", "pc",
                    "--ticks", "0", "--no-keymaster"])
    assert rc == 0
    assert _RecordingDaemon.instances[-1]["anomaly_guard"] is None


def test_runs_daemon_cli_on_the_laptop_builds_a_guard_with_no_prober(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The laptop has no `ssh` route to itself: the budget check still runs, the probe does not."""

    monkeypatch.setattr(daemon_mod, "Daemon", _RecordingDaemon)
    _RecordingDaemon.instances = []
    rc = runs.main(["--store", str(tmp_path / "jobs.jsonl"), "daemon", "--host", "laptop", "--ticks", "0"])
    assert rc == 0
    guard = _RecordingDaemon.instances[-1]["anomaly_guard"]
    assert guard is not None
    assert guard.budget_checker is not None
    assert guard.host_prober is None


def test_runs_daemon_cli_handback_defaults_to_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daemon_mod, "Daemon", _RecordingDaemon)
    _RecordingDaemon.instances = []
    rc = runs.main(["--store", str(tmp_path / "jobs.jsonl"), "daemon", "--host", "pc", "--ticks", "0"])
    assert rc == 0
    assert _RecordingDaemon.instances[-1]["handback"] == "local"


def test_runs_daemon_cli_handback_remote_reaches_the_daemon(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """issue #118 requirement 1: `--handback remote` (the laptop's own launch)."""

    monkeypatch.setattr(daemon_mod, "Daemon", _RecordingDaemon)
    _RecordingDaemon.instances = []
    rc = runs.main(["--store", str(tmp_path / "jobs.jsonl"), "daemon", "--host", "laptop",
                    "--ticks", "0", "--handback", "remote"])
    assert rc == 0
    assert _RecordingDaemon.instances[-1]["handback"] == "remote"


def test_the_real_host_prober_probes_at_most_once_per_60s_of_fake_clock(tmp_path: Path) -> None:
    """The daemon's own `AnomalyGuard` (built by `_build_anomaly_guard`), driven by a fake clock."""

    from junkroan.runs import anomalies as an

    calls = {"n": 0}

    def fake_run_on_host(host_cfg, script):
        calls["n"] += 1
        import subprocess

        return subprocess.CompletedProcess(args=[], returncode=0)

    prober = an.make_host_prober({"ssh": "laptop"}, run_on_host=fake_run_on_host)
    clock = {"t": 0.0}
    class NoSessions:                                       # no real Claude program (#759)
        def list_sessions(self):
            return []

    guard = an.AnomalyGuard(path=tmp_path / "anomalies.json", host_prober=prober, launcher=NoSessions(),
                            clock=lambda: clock["t"], log=lambda message: None)
    assert guard.probe_interval == an.PROBE_INTERVAL_SECONDS

    for _ in range(12):                                     # 12 ticks of 10 s = 120 s
        guard.check()
        clock["t"] += 10.0

    assert calls["n"] == 2


def test_queue_backend_calls_run_queue_by_import() -> None:
    """Requirement 2 and 6: snapshot / junction / naming / archival handling is run_queue.py's own.

    The module is imported and its functions are the ones the backend calls -- nothing is
    reimplemented here, and `scripts/run_queue.py` itself is untouched.
    """

    module = daemon_mod.run_queue()
    for name in ("make_snapshot", "drop_snapshot", "wants_snapshot", "out_name", "pid_alive",
                 "benchmark_run_dir", "archive_benchmark_run", "is_benchmark_command", "RUNS"):
        assert hasattr(module, name), name

    backend = daemon_mod.QueueBackend()
    assert backend.runs_dir() == module.RUNS
    assert backend.wants_snapshot("python scripts/benchmark.py --tag x") is True
    assert backend.wants_snapshot("python scripts/compare_runs.py") is False   # LIVE_SCRIPTS
    assert backend.find_run_dir("python scripts/search.py Fireball", Path("nope.out"), 0.0) is None
    assert backend.archive("python scripts/search.py Fireball", None, Path("nope.out")) == 0


# -- issue #54: the runs daemon reverts expired timed modes every tick ---------------------------

def test_54_tick_calls_revert_modes_once_and_survives_its_failure(tmp_path: Path) -> None:
    daemon, _store, _queue = make_daemon(tmp_path)
    assert daemon.revert_modes is None  # tests never touch the real var/modes.json
    calls: list[int] = []
    daemon.revert_modes = lambda: calls.append(1)
    daemon.tick()
    assert calls == [1]

    def boom() -> None:
        raise RuntimeError("locked")

    daemon.revert_modes = boom
    daemon.tick()  # a failing revert must not end the tick


def test_54_runs_daemon_cli_passes_revert_expired_modes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from junkroan.runs import hosts as runs_hosts

    monkeypatch.setattr(daemon_mod, "Daemon", _RecordingDaemon)
    _RecordingDaemon.instances = []
    assert runs.main(["--store", str(tmp_path / "jobs.jsonl"), "daemon", "--host", "pc", "--ticks", "0"]) == 0
    assert _RecordingDaemon.instances[-1]["revert_modes"] is runs_hosts.revert_expired_modes


# -- issues #59 / #25: two jobs started in the same minute never share one `.out` ----------------

def _same_minute_daemon(tmp_path: Path, launcher: FakeLauncher):
    """A daemon with the REAL `QueueBackend` (so `run_queue.out_name` is the code under test) and a
    clock frozen inside one minute, which is what made two lines collide (#59)."""

    store = Store(tmp_path / "jobs.jsonl")
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(exist_ok=True)
    frozen = datetime(2026, 9, 26, 17, 59)
    daemon = daemon_mod.Daemon(
        store, host="pc",
        launcher=launcher,
        gh=FakeGh(),
        queue=daemon_mod.QueueBackend(),          # not the fake: the real naming path
        budget_loader=lambda: BUDGET_7_2,
        slot_lister=FakeSlots(),
        events_file=tmp_path / "events.jsonl",
        runs_dir=runs_dir,
        archive=False,
        snapshots=False,                          # no git worktree, no junction
        hosts_config={},                          # #864: not the host's real config/hosts.json (its RAM gate reads real free RAM)
        spike_reader=lambda job_pids, prev: {"ts": "2026-01-01T00:00:00", "free_ram_mb": 9999.0, "cpu_pct": 1.0, "groups": {}},
        timestamp=lambda: frozen,
        log=lambda message: None,
    )
    return daemon, store, runs_dir


def test_59_three_untagged_jobs_of_the_same_minute_get_three_out_files(tmp_path: Path) -> None:
    """The 2026-09-26 17:59 collision, under the daemon: two `compare_runs` lines and a census line
    started in one minute must land in three different `.out` files, none overwritten.
    """

    launcher = FakeLauncher()
    daemon, store, runs_dir = _same_minute_daemon(tmp_path, launcher)
    first = store.submit(host="pc", priority="P2", tag="cmp-a", workers=1,
                         cmd="python scripts/compare_runs.py main3-tpl-smoke-s4-lap tpl-byvalue-smoke-s4")
    second = store.submit(host="pc", priority="P2", tag="cmp-b", workers=1,
                          cmd="python scripts/compare_runs.py ziz-main3-s4 ziz-tpl-main3-s4")
    third = store.submit(host="pc", priority="P2", tag="census", workers=1,
                         cmd="python scripts/template_line_census.py main3-tpl-smoke-s4-lap tpl-byvalue-smoke-s4")

    assert daemon.fill() == [first.id, second.id, third.id]

    outs = [Path(store.get(job.id).out) for job in (first, second, third)]
    assert [path.name for path in outs] == [
        "20260926-1759-compare_runs.out",
        "20260926-1759-compare_runs-2.out",
        "20260926-1759-template_line_census.out",
    ]
    assert len({path for path in outs}) == 3
    assert all(path.is_file() for path in outs)
    # Nothing was overwritten: each file still holds its own job's command.
    assert "main3-tpl-smoke-s4-lap tpl-byvalue" in outs[0].read_text(encoding="utf-8")
    assert "ziz-main3-s4 ziz-tpl-main3-s4" in outs[1].read_text(encoding="utf-8")
    assert "template_line_census" in outs[2].read_text(encoding="utf-8")
    assert len(list(runs_dir.glob("*.out"))) == 3


def test_25_a_job_only_ever_writes_to_its_own_out_file(tmp_path: Path) -> None:
    """#25 (the slot semaphore's lines landing in another run's `.out`) is the same collision: with
    one `.out` per job, every child's handle is its own file, and the paths the store records are
    the paths the launcher was given."""

    launcher = FakeLauncher()
    daemon, store, _runs_dir = _same_minute_daemon(tmp_path, launcher)
    for index in range(4):
        store.submit(host="pc", priority="P2", tag=f"bench-{index}", workers=1,
                     cmd=f"python scripts/benchmark.py --set smoke --tag same-minute-{index}")
    started = daemon.fill()
    assert len(started) == 4

    launched = [record["out"] for record in launcher.started]
    recorded = [Path(store.get(job_id).out) for job_id in started]
    assert launched == recorded
    assert len(set(launched)) == 4
    assert sorted(path.name for path in launched) == [
        f"20260926-1759-same-minute-{index}.out" for index in range(4)
    ]


# -- #82 requirement 2: `--after` chains, through the daemon --------------------------------------

def test_82_an_after_chain_of_two_starts_in_order(tmp_path: Path) -> None:
    """B `--after A` only starts on the tick after A ended rc 0, though there is room for both."""

    launcher = FakeLauncher()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher)
    first = store.submit(host="pc", priority="P2", tag="a", cmd="python scripts/benchmark.py --tag a", workers=1)
    second = store.submit(host="pc", priority="P2", tag="b", cmd="python scripts/benchmark.py --tag b",
                          workers=1, after=[first.id])

    assert daemon.tick().started == [first.id]     # room 5: B is held by the chain, not by the room
    assert daemon.room() == 4
    assert daemon.tick().started == []
    assert store.get(second.id).state == "queued"

    launcher.finish(launcher.started[0]["pid"], 0)
    report = daemon.tick()
    assert report.ended == [first.id] and report.started == [second.id]
    assert store.get(second.id).state == "running"
    assert [job["cmd"] for job in launcher.started] == [
        "python scripts/benchmark.py --tag a", "python scripts/benchmark.py --tag b",
    ]


def test_82_a_failed_predecessor_leaves_the_follower_queued_and_names_the_pair(tmp_path: Path) -> None:
    """A ends rc 1: B never starts, and `blocked_jobs` names the pair for the anomaly guard."""

    launcher = FakeLauncher()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher)
    first = store.submit(host="pc", priority="P2", tag="a", cmd="echo a", workers=1)
    second = store.submit(host="pc", priority="P2", tag="b", cmd="echo b", workers=1, after=[first.id])
    daemon.tick()
    launcher.finish(launcher.started[0]["pid"], 1)
    daemon.tick()

    assert store.get(first.id).state == "failed"
    assert daemon.tick().started == []
    assert store.get(second.id).state == "queued"
    assert [(job.id, dep.id) for job, dep in daemon.blocked_jobs()] == [(second.id, first.id)]


@pc_only
def test_82_submit_after_on_the_cli_is_repeatable_and_rejects_an_unknown_id(tmp_path: Path, capsys) -> None:
    store_path = tmp_path / "jobs.jsonl"
    base = ["--store", str(store_path), "submit", "--issue", "1", "--host", "pc", "--priority", "P2"]
    assert runs.main([*base, "--", "echo", "a"]) == 0
    first_id = capsys.readouterr().out.strip()
    assert runs.main([*base, "--", "echo", "b"]) == 0
    second_id = capsys.readouterr().out.strip()

    assert runs.main([*base, "--after", first_id, "--after", second_id, "--", "echo", "c"]) == 0
    third_id = capsys.readouterr().out.strip()
    store = Store(store_path)
    assert store.get(third_id).after == (first_id, second_id)

    assert runs.main([*base, "--after", "j-20260101-0000-dead", "--", "echo", "d"]) == 1
    captured = capsys.readouterr()
    assert "no such job" in captured.err
    assert len(store.jobs()) == 3   # `d` was never written


def test_82_status_prints_the_hold_under_the_table(tmp_path: Path, capsys) -> None:
    store_path = tmp_path / "jobs.jsonl"
    store = Store(store_path)
    first = store.submit(host="pc", priority="P2", tag="a", cmd="echo a")
    second = store.submit(host="pc", priority="P2", tag="b", cmd="echo b", after=[first.id])
    store.start(first.id)
    store.end(first.id, rc=2)

    assert runs.main(["--store", str(store_path), "status"]) == 0
    out = capsys.readouterr().out
    assert f"{second.id} held: predecessor {first.id} failed" in out


# -- issue #73: the daemon status file + single-instance guard ----------------------------------

def test_write_daemon_status_is_atomic_and_readable(tmp_path: Path) -> None:
    path = tmp_path / "daemon-pc.json"
    daemon_mod.write_daemon_status(path, {"host": "pc", "pid": 123, "started": "2026-09-27T00:00:00+00:00",
                                          "last_tick": "2026-09-27T00:00:10+00:00", "tick_seconds": 10.0,
                                          "running": ["j-1"], "queued": 2})
    assert not list(tmp_path.glob("*.tmp"))  # the temp file is gone: os.replace landed it
    status = daemon_mod.read_daemon_status(path)
    assert status == {"host": "pc", "pid": 123, "started": "2026-09-27T00:00:00+00:00",
                      "last_tick": "2026-09-27T00:00:10+00:00", "tick_seconds": 10.0,
                      "running": ["j-1"], "queued": 2}


def test_read_daemon_status_is_none_for_a_missing_or_broken_file(tmp_path: Path) -> None:
    assert daemon_mod.read_daemon_status(tmp_path / "nope.json") is None
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert daemon_mod.read_daemon_status(broken) is None


def test_status_liveness_true_when_pid_alive_and_tick_fresh() -> None:
    now = datetime(2026, 9, 27, 12, 0, 5, tzinfo=timezone.utc)
    status = {"pid": 111, "last_tick": "2026-09-27T12:00:00+00:00", "tick_seconds": 10.0}
    live, age = daemon_mod.status_liveness(status, now=now, pid_alive=lambda pid: True)
    assert live is True
    assert age == pytest.approx(5.0)


def test_status_liveness_false_when_pid_is_dead() -> None:
    now = datetime(2026, 9, 27, 12, 0, 5, tzinfo=timezone.utc)
    status = {"pid": 111, "last_tick": "2026-09-27T12:00:00+00:00", "tick_seconds": 10.0}
    live, age = daemon_mod.status_liveness(status, now=now, pid_alive=lambda pid: False)
    assert live is False
    assert age is None


def test_status_liveness_false_when_tick_is_stale() -> None:
    """Tick every 10 s: stale_after == max(30, 180) == 180 s; 200 s old is stale even if pid lives."""

    now = datetime(2026, 9, 27, 12, 5, 0, tzinfo=timezone.utc)
    status = {"pid": 111, "last_tick": "2026-09-27T12:01:40+00:00", "tick_seconds": 10.0}
    live, age = daemon_mod.status_liveness(status, now=now, pid_alive=lambda pid: True)
    assert live is False
    assert age == pytest.approx(200.0)


def test_status_liveness_none_status_is_never_live() -> None:
    live, age = daemon_mod.status_liveness(None, now=datetime.now(timezone.utc), pid_alive=lambda pid: True)
    assert live is False and age is None


def test_run_writes_the_status_file_at_start_and_rewrites_it_each_tick_with_running_ids(
    tmp_path: Path,
) -> None:
    one_slot = slot_budget.Budget(
        period="day", hours=(0, 24), total=1, others=0, min_free_ram_gb=0.0, strict_reserve=False,
    )
    launcher = FakeLauncher()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, budget=one_slot)
    job = store.submit(host="pc", priority="P2", tag="a", cmd="python scripts/benchmark.py --tag a")
    store.submit(host="pc", priority="P2", tag="b", cmd="echo b")  # only one slot: stays queued

    daemon.run(ticks=1, interval=5.0, sleep=lambda s: None)

    status = daemon_mod.read_daemon_status(daemon.status_path)
    assert status is not None
    assert status["host"] == "pc"
    assert status["pid"] == os.getpid()
    assert status["tick_seconds"] == 5.0
    assert status["running"] == [job.id]
    assert status["queued"] == 1
    datetime.fromisoformat(status["started"])  # ISO, parseable
    datetime.fromisoformat(status["last_tick"])


def test_cmd_daemon_guard_exits_when_a_live_daemon_owns_the_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
) -> None:
    status_path = runs_hosts.daemon_status_path("pc")
    daemon_mod.write_daemon_status(status_path, {
        "host": "pc", "pid": os.getpid(), "started": "2026-09-27T00:00:00+00:00",
        "last_tick": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tick_seconds": 10.0, "running": [], "queued": 0,
    })
    monkeypatch.setattr(daemon_mod, "Daemon", _RecordingDaemon)
    _RecordingDaemon.instances = []
    rc = runs.main(["--store", str(tmp_path / "jobs.jsonl"), "daemon", "--host", "pc", "--ticks", "0"])
    assert rc == 0
    assert _RecordingDaemon.instances == []  # never constructed: the guard exited first
    out = capsys.readouterr().out
    assert "already live" in out
    assert "pid" in out


def test_cmd_daemon_takes_over_when_the_recorded_pid_is_dead(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    status_path = runs_hosts.daemon_status_path("pc")
    daemon_mod.write_daemon_status(status_path, {
        "host": "pc", "pid": 999999, "started": "2026-09-27T00:00:00+00:00",
        "last_tick": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tick_seconds": 10.0, "running": [], "queued": 0,
    })
    monkeypatch.setattr(daemon_mod.QueueBackend, "pid_alive", lambda self, pid: False)
    monkeypatch.setattr(daemon_mod, "Daemon", _RecordingDaemon)
    _RecordingDaemon.instances = []
    rc = runs.main(["--store", str(tmp_path / "jobs.jsonl"), "daemon", "--host", "pc", "--ticks", "0"])
    assert rc == 0
    assert len(_RecordingDaemon.instances) == 1  # the dead pid did not block a takeover


def test_cmd_daemon_takes_over_when_the_tick_is_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    status_path = runs_hosts.daemon_status_path("pc")
    # 3 x 10 s == 30 s, floored to 180 s: a tick recorded years ago is stale either way.
    old = "2020-01-01T00:00:00+00:00"
    daemon_mod.write_daemon_status(status_path, {
        "host": "pc", "pid": os.getpid(), "started": old, "last_tick": old,
        "tick_seconds": 10.0, "running": [], "queued": 0,
    })
    monkeypatch.setattr(daemon_mod.QueueBackend, "pid_alive", lambda self, pid: True)
    monkeypatch.setattr(daemon_mod, "Daemon", _RecordingDaemon)
    _RecordingDaemon.instances = []
    rc = runs.main(["--store", str(tmp_path / "jobs.jsonl"), "daemon", "--host", "pc", "--ticks", "0"])
    assert rc == 0
    assert len(_RecordingDaemon.instances) == 1


# -- issue #365: an untracked process tree holding PoB slots raises one `untracked_slots` anomaly ----

def _untracked_daemon(tmp_path: Path, collector):
    from junkroan.runs import anomalies as an

    class Cli:
        def __init__(self) -> None:
            self.started: list = []

        def list_sessions(self) -> list:
            return []

        def start(self, anomaly):
            self.started.append(anomaly)
            return f"km-{len(self.started)}", ["claude"]

    cli = Cli()
    guard = an.AnomalyGuard(path=tmp_path / "anomalies.json", launcher=cli, host="pc",
                            log=lambda message: None)
    daemon, _store, _queue = make_daemon(tmp_path)
    daemon.anomaly_guard = guard
    daemon._untracked_collector = collector
    return daemon, cli


def test_365_one_untracked_tree_raises_one_anomaly_once(tmp_path: Path) -> None:
    from junkroan.runs.untracked import UntrackedTree

    tree = UntrackedTree(pid=12260, started=1_790_000_000.0, cmd_head="python scripts/run_queue.py",
                         tag="new18-tpl-main3-s4-lap", slots=3)
    daemon, cli = _untracked_daemon(tmp_path, lambda: [tree])
    daemon.tick()
    assert len(cli.started) == 1
    anomaly = cli.started[0]
    assert anomaly.kind == "untracked_slots" and anomaly.pid == 12260
    assert "pid 12260" in anomaly.detail and "3 PoB slot" in anomaly.detail
    assert "new18-tpl-main3-s4-lap" in anomaly.detail and "Nothing is stopped" in anomaly.detail
    print(anomaly.detail)
    daemon.tick()
    assert len(cli.started) == 1  # same pid + start: handled, no second anomaly
    # a reused pid (other start time) is a new anomaly
    daemon._untracked_collector = lambda: [UntrackedTree(12260, 1_790_009_999.0, "x", None, 1)]
    daemon.tick()
    assert len(cli.started) == 2


def test_365_a_failing_collector_does_not_kill_the_tick(tmp_path: Path) -> None:
    def boom():
        raise RuntimeError("psutil gone")

    daemon, cli = _untracked_daemon(tmp_path, boom)
    daemon.tick()
    assert cli.started == []


# -- issue #418: an agent's short 1-slot PoB test (<= 5 min) raises no `untracked_slots` -------------

def _clocked_untracked_daemon(tmp_path: Path, tree):
    daemon, cli = _untracked_daemon(tmp_path, lambda: [tree])
    clock = {"now": tree.started}
    daemon.anomaly_guard.clock = lambda: clock["now"]
    return daemon, cli, clock


def test_418_row1_one_slot_29_min_59_s_old_raises_nothing(tmp_path: Path) -> None:
    from junkroan.runs.untracked import UntrackedTree

    tree = UntrackedTree(pid=9916, started=1_790_000_000.0, cmd_head="python -u scratch398/diag_keys.py",
                         tag=None, slots=1)
    daemon, cli, clock = _clocked_untracked_daemon(tmp_path, tree)
    clock["now"] = tree.started + 29 * 60 + 59
    daemon.tick()
    assert cli.started == []


def test_418_row2_the_same_tree_at_30_min_1_s_raises_one_with_the_key_unchanged(tmp_path: Path) -> None:
    from junkroan.runs import anomalies as an
    from junkroan.runs.untracked import UntrackedTree

    tree = UntrackedTree(pid=9916, started=1_790_000_000.0, cmd_head="python -u scratch398/diag_keys.py",
                         tag=None, slots=1)
    daemon, cli, clock = _clocked_untracked_daemon(tmp_path, tree)
    clock["now"] = tree.started + 30
    daemon.tick()
    clock["now"] = tree.started + 30 * 60 + 1
    daemon.tick()
    daemon.tick()
    assert len(cli.started) == 1
    assert cli.started[0].key == an.detect_untracked_slots(tree, "pc").key == "untracked_slots:pc:9916:1790000000"


def test_418_row3_two_slots_30_s_old_raise_one(tmp_path: Path) -> None:
    from junkroan.runs.untracked import UntrackedTree

    tree = UntrackedTree(pid=2744, started=1_790_000_000.0, cmd_head="python scripts/benchmark.py",
                         tag=None, slots=2)
    daemon, cli, clock = _clocked_untracked_daemon(tmp_path, tree)
    clock["now"] = tree.started + 30
    daemon.tick()
    assert len(cli.started) == 1 and cli.started[0].kind == "untracked_slots"


# -- issue #164: the Run issue of a whole-set benchmark job -----------------------------------------

RUN_FIXTURE = Path(__file__).parent / "fixtures" / "run_issue" / "20261001-0100-filler-smoke-loot-s7"
BENCH_CMD = "py -3.12 scripts/benchmark.py --set {s} --seed 7 --seeds 3 --gear loot --tag x"


def _run_to_end(daemon, store, queue, launcher, cmd: str, rc: int, *, host: str = "pc"):
    queue.run_dir = RUN_FIXTURE
    job = store.submit(host=host, priority="P1", tag="filler-smoke-loot-s7", cmd=cmd)
    daemon.tick()
    launcher.finish(launcher.started[-1]["pid"], rc)
    daemon.tick()
    return job


def test_164a_a_whole_set_job_ending_rc0_opens_one_run_issue(tmp_path: Path) -> None:
    gh, launcher = FakeGh(), FakeLauncher()
    daemon, store, queue = make_daemon(tmp_path, launcher=launcher, gh=gh)
    job = _run_to_end(daemon, store, queue, launcher, BENCH_CMD.format(s="smoke"), 0)

    assert len(gh.created) == 1
    title, body, labels = gh.created[0]
    assert title == "Run 20261001-0100-filler-smoke-loot-s7 (smoke, pc)"
    assert labels == ["needs-triage", "area:builds"]
    rows = [l for l in body.splitlines() if l.startswith("| ") and not l.startswith("| reference")]
    assert len(rows) == 6
    assert gh.attached == [(404, 901)]
    assert store.get(job.id).run_issue == 901
    daemon.tick()
    daemon.tick()
    assert len(gh.created) == 1


def test_164b_slug_lists_and_failed_runs_open_no_run_issue(tmp_path: Path) -> None:
    gh, launcher = FakeGh(), FakeLauncher()
    daemon, store, queue = make_daemon(tmp_path, launcher=launcher, gh=gh)
    _run_to_end(daemon, store, queue, launcher, "py -3.12 scripts/benchmark.py --slugs a b --gear loot", 0)
    _run_to_end(daemon, store, queue, launcher, BENCH_CMD.format(s="smoke"), 1)
    assert gh.created == [] and gh.attached == []


def test_164_a_failed_create_retries_next_tick_and_creates_once(tmp_path: Path) -> None:
    gh, launcher = FakeGh(), FakeLauncher()
    gh.fail_creates = 1
    daemon, store, queue = make_daemon(tmp_path, launcher=launcher, gh=gh)
    job = _run_to_end(daemon, store, queue, launcher, BENCH_CMD.format(s="smoke"), 0)
    assert gh.created == [] and store.get(job.id).run_issue is None
    daemon.tick()
    assert len(gh.created) == 1 and store.get(job.id).run_issue == 901


def test_164c_a_laptop_job_is_created_by_the_pc_remote_pass_once(tmp_path: Path) -> None:
    lap_gh, launcher = FakeGh(), FakeLauncher()
    (tmp_path / "lap").mkdir()
    lap, lap_store, lap_queue = make_daemon(tmp_path / "lap", launcher=launcher, gh=lap_gh,
                                            host="laptop", handback="remote")
    job = _run_to_end(lap, lap_store, lap_queue, launcher, BENCH_CMD.format(s="new18"), 0, host="laptop")
    assert lap_gh.created == [] and lap_gh.attached == [] and lap_gh.comments == []
    kept = lap_store.get(job.id)
    assert kept.run_issue_body and kept.run_issue is None

    marks: list[tuple[str, int]] = []

    def mark(host_cfg, host, job_id, number):
        marks.append((job_id, number))
        lap_store.record_run_issue(job_id, number)
        return True

    pc_gh = FakeGh()
    (tmp_path / "pc").mkdir()
    pc, _, _ = make_daemon(tmp_path / "pc", gh=pc_gh, host="pc", hosts_config={"laptop": {"ssh": "laptop"}},
                           remote_store_reader=lambda cfg: lap_store.jobs(), remote_mark_run_issue=mark,
                           remote_pass_seconds=0.0)
    pc.remote_handback_pass()
    assert len(pc_gh.created) == 1
    assert pc_gh.created[0][0] == "Run 20261001-0100-filler-smoke-loot-s7 (new18, laptop)"
    assert pc_gh.attached == [(404, 901)]
    assert marks == [(job.id, 901)]
    pc.remote_handback_pass()
    assert len(pc_gh.created) == 1
