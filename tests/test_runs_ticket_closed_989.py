"""#989: a host without a `gh` executable does not run the closed-ticket pass; a host with one behaves as before.

Fakes only (no gh, no ssh, no PoB): the `gh` lookup is injected through `gh_present`.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from junkroan.runs import daemon as daemon_mod  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402
from test_runs_daemon import BUDGET_7_2, FakeLauncher, FakeQueueBackend, FakeSlots  # noqa: E402
from test_runs_ticket_closed_686 import StateGh  # noqa: E402


def _daemon(tmp_path, gh, log, gh_present):
    store = Store(tmp_path / "jobs.jsonl")
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(exist_ok=True)
    daemon = daemon_mod.Daemon(
        store, host="pc", launcher=FakeLauncher(), gh=gh, queue=FakeQueueBackend(runs_dir),
        budget_loader=lambda: BUDGET_7_2, slot_lister=FakeSlots(), events_file=tmp_path / "events.jsonl",
        runs_dir=runs_dir, archive=False, log=log, hosts_config={}, run_issue_parent=404,
        gh_present=gh_present,
    )
    now = [1000.0]
    daemon.clock = lambda: now[0]
    return daemon, store, now


def test_gh_absent_skips_the_closed_ticket_pass(tmp_path):
    gh = StateGh({621: "CLOSED"})
    logs: list[str] = []
    lookups: list[int] = []

    def gh_present():
        lookups.append(1)
        return False

    daemon, store, now = _daemon(tmp_path, gh, logs.append, gh_present)
    run = store.submit(host="pc", priority="P1", tag="a", cmd="echo hi", issue=621)
    store.start(run.id, pid=4242)
    for _ in range(3):
        assert daemon.ticket_closed_pass() == []
        now[0] += 301  # more than TICKET_CHECK_SECONDS (300 s) between passes
    assert gh.calls == []  # 0 calls of issue_state
    assert [line for line in logs if "gh could not read" in line] == []
    assert len([line for line in logs if "ticket check off" in line]) == 1  # exactly one start line
    assert len(lookups) == 1  # the gh lookup ran once, at the daemon's start
    assert store.get(run.id).state == "running"  # the job is not touched


def test_gh_present_failing_read_logs_one_line_per_pass(tmp_path):
    gh = StateGh({}, fail=True)
    logs: list[str] = []
    daemon, store, now = _daemon(tmp_path, gh, logs.append, lambda: True)
    run = store.submit(host="pc", priority="P1", tag="a", cmd="echo hi", issue=621)
    store.start(run.id, pid=4242)
    assert daemon.ticket_closed_pass() == []
    now[0] += 301
    assert daemon.ticket_closed_pass() == []
    assert gh.calls == [621, 621]
    assert len([line for line in logs if "gh could not read #621" in line]) == 2  # 1 per pass
    assert [line for line in logs if "ticket check off" in line] == []  # no start line with gh present
    assert store.get(run.id).state == "running"
