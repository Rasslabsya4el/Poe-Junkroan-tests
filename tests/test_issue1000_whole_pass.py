"""#1000 (unit 3, whole pass): one `Daemon.tick` with the outside calls of the pass dead ends bounded.

Fakes only: `run_bounded` (gh, ssh, scp), `subprocess.run` (git) and a Popen that never ends, all on one fake clock
that a hanging call spends its whole timeout on. No real gh, ssh, git, claude or PoB; nothing sleeps.

The rule: no single outside call waits over 60 s, and a dead service costs one timeout per pass (its GUARD key).
So the whole tick is the SUM of the distinct keys' limits that hung, not 60 s. Every dead tick is compared with the
same tick with every call answering: job states, starts, holds and `_gate_status` must be the same.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from junkroan.runs import anomalies as an  # noqa: E402
from junkroan.runs import bounded  # noqa: E402
from junkroan.runs import daemon as daemon_mod  # noqa: E402
from junkroan.runs import hosts as hosts_mod  # noqa: E402
from junkroan.runs import pin_ref  # noqa: E402
from junkroan.runs import remote_store as remote_store_mod  # noqa: E402
from junkroan.runs import row_sync as row_sync_mod  # noqa: E402
from junkroan.runs.pass_guard import PassGuard  # noqa: E402
from test_runs_daemon import FakeLauncher, make_daemon  # noqa: E402

HOST = {"name": "laptop", "ssh": "laptop", "repo_path": "C:/x"}
CUT = "c" * 40
MONDAY_FOLDER = "20261017-2000-week-20261019"     # the Monday (2026-10-19) of the Saturday tick (2026-10-17)
GATE = "20261017-2000-gate-t1000"                 # a gate dir the PC holds and the laptop does not
ALL_DEAD = ("gh", "ssh", "git-fetch")             # every service down: the first ssh call hangs, the rest are skipped


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class NeverEnds:
    """The gate copy's Popen: running for ever (poll None), never killed in one tick."""

    pid = 4242

    def poll(self):
        return None

    def kill(self) -> None:
        pass


class NoKeymasters:
    """The keymaster launcher stub: records any start, starts nothing for real."""

    def __init__(self) -> None:
        self.started: list[str] = []

    def list_sessions(self) -> list[dict]:
        return []

    def start(self, anomaly):
        self.started.append(anomaly.key)
        return ("session-1", [])


def _ssh_kind(argv: list[str]) -> str:
    """The kind of one ssh call, read from its decoded `-EncodedCommand` script."""

    script = base64.b64decode(argv[-1]).decode("utf-16-le")
    if "ConvertTo-Json" in script and "rows" in script:
        return "ssh-list"          # row_sync.SshTransport.list_rows
    if ".partial" in script:
        return "ssh-prep"          # gate_sync's preparation (hosts.run_on_host)
    if "anomalies.json" in script:
        return "ssh-anomaly"       # remote_anomaly_pass's read
    if "New-Item" in script:
        return "ssh-push"          # row_sync push
    return "ssh-snapshot"          # remote_handback_pass's jobs + status read


class World:
    """The outside services of one pass. `hang` names the calls that never answer: "gh", "git-fetch", one ssh kind
    ("ssh-list", "ssh-prep", ...), or "ssh" for every ssh call (only the first ssh call of a pass is made; the
    guard skips the others)."""

    def __init__(self, clock: FakeClock, hang) -> None:
        self.clock = clock
        self.hang = set(hang)
        self.calls: list[tuple[str, float]] = []        # (kind, timeout) of every call that was made
        self.unexpected: list[list[str]] = []           # anything that is not gh, ssh, scp or git

    def _answer(self, kind: str, argv, timeout, stdout: str = ""):
        self.calls.append((kind, timeout))
        if kind in self.hang or (kind.startswith("ssh-") and "ssh" in self.hang):
            self.clock.advance(timeout)
            raise subprocess.TimeoutExpired(argv, timeout)
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    def run_bounded(self, argv, **kwargs):
        head = argv[0]
        timeout = kwargs.get("timeout")
        if head == "gh":
            return self._answer("gh", argv, timeout, stdout=json.dumps({"state": "OPEN", "comments": []}))
        if head == "ssh":
            return self._answer(_ssh_kind(argv), argv, timeout)
        if head == "scp":
            return self._answer("scp", argv, timeout)
        self.unexpected.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    def git(self, argv, *args, **kwargs):
        if not argv or argv[0] != "git":
            self.unexpected.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        sub = argv[3] if len(argv) > 3 and argv[1] == "-C" else argv[1]
        if sub == "fetch":
            return self._answer("git-fetch", argv, kwargs.get("timeout"))
        if sub == "show":                                # no override file on origin/main
            return subprocess.CompletedProcess(argv, 128, stdout="", stderr="no such path")
        return subprocess.CompletedProcess(argv, 0, stdout=CUT + "\n", stderr="")   # rev-list, rev-parse, merge-base


def _patch(monkeypatch, clock: FakeClock, world: World) -> None:
    """One fake clock for every pass guard, and every outside call routed to the world."""

    guard = PassGuard(clock=clock)
    for module in (daemon_mod, hosts_mod, row_sync_mod, remote_store_mod, an, pin_ref):
        if hasattr(module, "GUARD"):
            monkeypatch.setattr(module, "GUARD", guard)
    for module in (daemon_mod, hosts_mod, bounded, an, pin_ref):
        monkeypatch.setattr(module, "run_bounded", world.run_bounded)
    monkeypatch.setattr(subprocess, "run", world.git)


def _run(tmp_path: Path, monkeypatch, *, hang=(), week: bool, gate: bool) -> dict:
    """One `Daemon.tick` on the PC with a done job (its hand-back is pending) and a queued job."""

    clock = FakeClock()
    world = World(clock, hang)
    _patch(monkeypatch, clock, world)
    tmp_path.mkdir(parents=True, exist_ok=True)

    cut_repo = tmp_path / "repo"
    (cut_repo / "artifacts" / "benchmark").mkdir(parents=True, exist_ok=True)
    if week:
        folder = cut_repo / "artifacts" / "benchmark" / MONDAY_FOLDER
        (folder / "rows").mkdir(parents=True)
        (folder / "args.json").write_text(json.dumps({"commit": CUT}), encoding="utf-8")
    gate_artifacts = tmp_path / "gate_artifacts"
    if gate:
        (gate_artifacts / "benchmark" / GATE).mkdir(parents=True)

    logs: list[str] = []
    launcher = FakeLauncher()
    daemon, store, _ = make_daemon(tmp_path, gh=daemon_mod.GhCli(cwd=tmp_path), launcher=launcher,
                                   hosts_config={"laptop": HOST, "pc": {"fillers": True}},
                                   remote_pass_seconds=0.0)
    daemon.log = logs.append
    daemon.clock = clock
    daemon.timestamp = lambda: datetime(2026, 10, 17, 12, 0)    # a Saturday: the weekly cut is open
    daemon._cut_repo = cut_repo
    daemon._gate_artifacts = gate_artifacts
    daemon._gates_path = tmp_path / "gates.json"
    daemon._gate_popen = lambda argv, **kwargs: NeverEnds()
    daemon._copy_killer = lambda pid: None
    daemon._untracked_collector = lambda: []
    keymasters = NoKeymasters()
    guard = an.AnomalyGuard(path=tmp_path / "anomalies.json", launcher=keymasters, start_keymasters=True,
                            host="pc", clock=clock, log=logs.append, bench_root=tmp_path / "bench",
                            slot_lister=lambda: [], reservation_lister=lambda: [])
    daemon.anomaly_guard = guard
    guard.chain_store = store                                  # what Daemon.__init__ does for a guard
    guard.missing_script_line = daemon._missing_script_line

    out = tmp_path / "done.out"
    out.write_text("done\n", encoding="utf-8")
    done = store.submit(host="pc", priority="P1", tag="done", cmd="echo done", issue=1)
    store.start(done.id, out=str(out))
    store.end(done.id, rc=0, out=str(out))                     # done, hand-back pending (gh comment)
    queued = store.submit(host="pc", priority="P1", tag="queued", cmd="echo queued", issue=2)

    report = daemon.tick()
    # job ids carry the clock's time, so the two ticks are compared by the job's tag, never by its id
    tag_of = {done.id: "done", queued.id: "queued"}
    return {
        "elapsed": clock.now,
        "calls": list(world.calls),
        "unexpected": list(world.unexpected),
        "states": [store.get(job_id).state for job_id in (done.id, queued.id)],
        "started": [tag_of.get(job_id, job_id) for job_id in report.started],
        "holds": [(tag_of.get(job.id, job.id), verdict) for job, _, verdict in store.held_jobs()],
        "gate_status": {tag_of.get(job_id, job_id): dict(v) for job_id, v in daemon._gate_status.items()},
        "logs": logs,
    }


def _not_gh(run: dict) -> list:
    """The ssh and git calls of a pass (the answering gh comment reads repeat and are not the point of the test)."""
    return [call for call in run["calls"] if call[0] != "gh"]


def _same_decisions(dead: dict, alive: dict) -> None:
    for key in ("states", "started", "holds", "gate_status"):
        assert dead[key] == alive[key], (key, dead[key], alive[key], dead["logs"])
    assert dead["unexpected"] == alive["unexpected"] == [], (dead["unexpected"], alive["unexpected"])
    assert all(timeout <= 60.0 for _, timeout in dead["calls"]), dead["calls"]   # no single call over 60 s


# -- (1) every service dead, the week folder present: gh 45 s uses the pass budget (#998), nothing else starts ----------------

def test_1_all_dead_with_the_week_folder_present_ends_at_45_seconds(tmp_path, monkeypatch):
    dead = _run(tmp_path / "dead", monkeypatch, hang=ALL_DEAD, week=True, gate=True)
    alive = _run(tmp_path / "alive", monkeypatch, week=True, gate=True)

    # gh (the hand-back comment, 45 s) uses the whole 45 s pass budget (#998): no later guarded call is made
    assert dead["calls"] == [("gh", 45.0)], dead["calls"]
    assert dead["elapsed"] == 45.0, dead["elapsed"]
    _same_decisions(dead, alive)


# -- (2) ssh and git dead (gh answers), the week folder absent: the remote read 30 s, then the cut's git fetch 45 s starts
# (the pass has used 30 s < 45 s) = 75 s -----------------------

def test_2_ssh_and_fetch_dead_with_the_week_folder_absent_adds_the_cut_fetch_and_ends_at_75_seconds(tmp_path, monkeypatch):
    dead = _run(tmp_path / "dead", monkeypatch, hang=("ssh", "git-fetch"), week=False, gate=True)
    alive = _run(tmp_path / "alive", monkeypatch, week=False, gate=True)

    assert _not_gh(dead) == [("ssh-snapshot", 30.0), ("git-fetch", 45.0)], dead["calls"]
    assert dead["elapsed"] == 75.0, dead["elapsed"]
    _same_decisions(dead, alive)


# -- (3) the remote read and the anomaly read answer, row_sync's list_rows hangs: the list call 45 s = 45 s --------

def test_3_row_sync_list_rows_hang_after_the_reads_answer_ends_at_45_seconds(tmp_path, monkeypatch):
    dead = _run(tmp_path / "dead", monkeypatch, hang=("ssh-list",), week=True, gate=False)
    alive = _run(tmp_path / "alive", monkeypatch, week=True, gate=False)

    assert _not_gh(dead) == [("ssh-snapshot", 30.0), ("ssh-anomaly", 30.0), ("ssh-list", 45.0)], dead["calls"]
    assert dead["elapsed"] == 45.0, dead["elapsed"]
    _same_decisions(dead, alive)


# -- (4) the same, the gate preparation hangs: gate_sync was reached; the preparation 45 s = 45 s --------------

def test_4_gate_preparation_hang_after_the_reads_answer_ends_at_45_seconds(tmp_path, monkeypatch):
    dead = _run(tmp_path / "dead", monkeypatch, hang=("ssh-prep",), week=True, gate=True)
    alive = _run(tmp_path / "alive", monkeypatch, week=True, gate=True)

    assert _not_gh(dead) == [("ssh-snapshot", 30.0), ("ssh-anomaly", 30.0), ("ssh-prep", 45.0)], dead["calls"]
    assert dead["elapsed"] == 45.0, dead["elapsed"]
    _same_decisions(dead, alive)
