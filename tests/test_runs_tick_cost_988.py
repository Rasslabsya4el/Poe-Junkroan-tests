"""#988: what a daemon tick costs. The queue watcher read every line of `jobs.jsonl` ~25 times a tick, read the
command line of all ~400 processes every tick (`untracked.collect_local`) and again every 30 s (the load record).
The decisions must not change: the same store through the old and the new reads starts and holds the same jobs.
No PoB, no real gh, no real process launch."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from junkroan.pob import slot_budget  # noqa: E402
from junkroan.runs import load_groups, proc_bulk, untracked  # noqa: E402
from junkroan.runs.store import Store, fold  # noqa: E402
from junkroan.runs.untracked import collect_local  # noqa: E402  (conftest swaps the module's attribute, not this name)
from test_runs_daemon import FakeLauncher, make_daemon  # noqa: E402


@pytest.fixture(autouse=True)
def _status_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUNKROAN_DAEMON_STATUS_DIR", str(tmp_path / "daemon-status"))


class UncachedStore(Store):
    """The read before #988: parse and fold the whole file on every call."""

    def _fold_all(self):  # type: ignore[override]
        return fold(self._read_lines())


# -- the store read ------------------------------------------------------------------------------------

def _submit(store: Store, tag: str, **kw):
    return store.submit(host="pc", priority=kw.pop("priority", "P2"), tag=tag,
                        cmd=kw.pop("cmd", f"python scripts/benchmark.py --tag {tag}"), **kw)


def test_the_store_folds_once_while_the_file_is_unchanged_and_again_after_a_line(tmp_path: Path, monkeypatch) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    first = _submit(store, "a")
    store = Store(tmp_path / "jobs.jsonl")  # a daemon's own instance: nothing folded yet
    reads = []
    real = Store._read_lines
    monkeypatch.setattr(Store, "_read_lines", lambda self: reads.append(1) or real(self))

    for _ in range(5):
        assert [j.id for j in store.jobs()] == [first.id]
    assert len(reads) == 1, "five reads of an unchanged file must fold once"

    reads.clear()
    second = _submit(Store(tmp_path / "jobs.jsonl"), "b")  # another process appends: this instance only sees the file
    reads.clear()
    assert [j.id for j in store.jobs()] == [first.id, second.id]
    assert store.get(second.id).state == "queued"
    assert len(reads) == 1, "a new line is folded again, once"


def test_a_rewritten_or_emptied_file_is_read_again(tmp_path: Path) -> None:
    path = tmp_path / "jobs.jsonl"
    store = Store(path)
    _submit(store, "a")
    _submit(store, "b")
    assert len(store.jobs()) == 2
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    path.write_text(lines[0], encoding="utf-8")  # shorter: a compaction / a test's rewrite
    assert len(store.jobs()) == 1
    path.unlink()
    assert store.jobs() == []


def test_cached_reads_answer_exactly_as_uncached_reads(tmp_path: Path) -> None:
    cached, plain = Store(tmp_path / "jobs.jsonl"), UncachedStore(tmp_path / "jobs.jsonl")
    a = _submit(cached, "a", priority="P1", workers=2)
    b = _submit(cached, "b", priority="P0")
    c = _submit(cached, "c", after=(a.id,))
    d = _submit(cached, "d", after=(c.id,))
    for step in (lambda: cached.start(a.id, pid=111), lambda: cached.end(a.id, rc=1), lambda: cached.requeue(a.id)):
        step()
        assert cached.jobs() == plain.jobs()
        assert cached.held_jobs() == plain.held_jobs()
        assert cached.next_job("pc") == plain.next_job("pc")
        assert cached.get(d.id) == plain.get(d.id)
    assert b.id and c.id


def test_a_caller_cannot_corrupt_the_cached_fold(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    job = _submit(store, "a")
    store._fold_all().clear()
    assert [j.id for j in store.jobs()] == [job.id]


# -- the tick's decisions: one recorded store through the old and the new read -------------------------

def _record(path: Path) -> None:
    """A store as the daemon finds it: one running job, a P0, a P1 behind a running dependency, a queue that
    does not all fit the 5 workers of the queue share, and a filler-sized P2 tail."""

    rec = Store(path)
    run = _submit(rec, "running", priority="P1", workers=2, cmd="python scripts/benchmark.py --workers 2")
    rec.start(run.id, pid=4001, out=str(path.parent / "running.out"))
    top = _submit(rec, "top", priority="P0", workers=2, cmd="python scripts/benchmark.py --workers 2")
    _submit(rec, "after-top", priority="P1", workers=1, after=(top.id,))
    _submit(rec, "big", priority="P2", workers=4, cmd="python scripts/benchmark.py --workers 4")
    _submit(rec, "small-a", priority="P2", workers=1)
    _submit(rec, "small-b", priority="P2", workers=1)
    _submit(rec, "late-p0", priority="P0", workers=1)


def _replay(tmp_path: Path, name: str, store_cls: type[Store], recorded: Path) -> dict:
    root = tmp_path / name
    root.mkdir()
    shutil.copy(recorded, root / "jobs.jsonl")
    launcher = FakeLauncher()
    daemon, _, _ = make_daemon(root, launcher=launcher)
    daemon.store = store_cls(root / "jobs.jsonl")
    seen = []
    for tick in range(4):
        report = daemon.tick()
        seen.append({
            "started": list(report.started), "ended": list(report.ended), "room": report.room,
            "gates": json.dumps(daemon._gate_status, sort_keys=True, default=str),
            "queued": sorted(j.id for j in daemon.store.jobs(state="queued")),
        })
        if tick == 0 and launcher.started:
            launcher.finish(launcher.started[0]["pid"], 0)  # a job ends: the next tick reaps it and starts more
    final = [(j.id, j.state, j.rc) for j in daemon.store.jobs()]
    return {"ticks": seen, "started_cmds": [s["cmd"] for s in launcher.started], "final": final}


def test_988_one_recorded_store_starts_and_holds_the_same_through_the_old_and_the_new_read(tmp_path: Path) -> None:
    recorded = tmp_path / "recorded.jsonl"
    _record(recorded)
    old = _replay(tmp_path, "old", UncachedStore, recorded)
    new = _replay(tmp_path, "new", Store, recorded)
    assert old["started_cmds"], "the replay must start something, or it proves nothing"
    assert any(t["queued"] for t in old["ticks"]), "and hold something"
    assert new == old


# -- the process table --------------------------------------------------------------------------------

class _FakeProc:
    """A psutil.Process stand-in that counts what it is asked."""

    asked: list[tuple[int, str]] = []

    def __init__(self, pid: int, ppid: int, ctime: float, cmd: list[str], *, name: str = "python.exe",
                 user: str | None = "me", denied: bool = False) -> None:
        self.pid, self._cmd, self._denied = pid, cmd, denied
        self.info = {"pid": pid, "ppid": ppid, "name": name, "create_time": ctime, "username": user,
                     "memory_info": SimpleNamespace(rss=2 << 20), "cpu_times": SimpleNamespace(user=1.0, system=0.5)}

    def cmdline(self) -> list[str]:
        _FakeProc.asked.append((self.pid, "cmdline"))
        if self._denied:
            import psutil
            raise psutil.AccessDenied(self.pid)
        return list(self._cmd)

    def cwd(self) -> str:
        return "C:/x"


def _fake_table(monkeypatch, procs: list[_FakeProc]) -> None:
    import psutil

    _FakeProc.asked = []
    monkeypatch.setattr(proc_bulk, "snapshot", lambda: None)
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None, ad_value=None: iter(procs))
    monkeypatch.setattr(load_groups, "_CMDLINES", {})


def test_988_a_command_line_is_read_once_per_process_not_once_per_reading(monkeypatch) -> None:
    old = _FakeProc(10, 1, 100.0, ["python", "a.py"])
    denied = _FakeProc(11, 1, 101.0, [], user=None, denied=True)
    _fake_table(monkeypatch, [old, denied])
    monkeypatch.setattr(load_groups, "_session_of", lambda pid: 0)
    first = load_groups.read_proc_table()
    assert [r["cmdline"] for r in first] == [["python", "a.py"], []]
    assert sorted(_FakeProc.asked) == [(10, "cmdline"), (11, "cmdline")]

    _FakeProc.asked = []
    second = load_groups.read_proc_table()
    assert second == first
    assert _FakeProc.asked == [], "a known (pid, start) is not asked again, a refused one included"

    young = _FakeProc(12, 10, 1e12, [])  # empty and not yet old enough to be believed
    _fake_table(monkeypatch, [old, young])
    load_groups.read_proc_table()
    _FakeProc.asked = []
    load_groups.read_proc_table()
    assert _FakeProc.asked == [(12, "cmdline")], "only the young empty one is asked again"


def test_988_a_pid_reused_by_a_new_process_is_read_again(monkeypatch) -> None:
    _fake_table(monkeypatch, [_FakeProc(10, 1, 100.0, ["old.exe"])])
    assert load_groups.read_proc_table()[0]["cmdline"] == ["old.exe"]
    import psutil
    reused = _FakeProc(10, 1, 200.0, ["new.exe"])
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None, ad_value=None: iter([reused]))
    assert load_groups.read_proc_table()[0]["cmdline"] == ["new.exe"]


def _slot_rows(pids: list[int]) -> list[dict]:
    return [{"slot": n + 1, "pid": p, "role": "queue", "age_seconds": 5.0, "cmd": ""} for n, p in enumerate(pids)]


def _old_collect_local(slots, jobs, procs: list[_FakeProc]):
    """`untracked.collect_local` before #988, on the same fakes: every command line of the table."""

    table = {p.pid: (p.info["ppid"], p.info["create_time"], " ".join(p.cmdline() or ())) for p in procs}
    return untracked.untracked_trees(slots, jobs, table)


def test_988_collect_local_gives_the_trees_the_old_full_table_gave_and_reads_only_the_chains(monkeypatch) -> None:
    import psutil

    queue = "python scripts/run_queue.py plan.json --tag lap"
    worker = "python headless_runtime_worker.py"
    procs = [
        _FakeProc(1, 0, 1.0, ["init"]),
        _FakeProc(100, 1, 10.0, queue.split()),
        _FakeProc(101, 100, 11.0, worker.split()),
        _FakeProc(102, 100, 11.0, worker.split()),
        _FakeProc(200, 1, 12.0, ["python", "scripts/benchmark.py", "--tag", "own"]),
        _FakeProc(201, 200, 13.0, worker.split()),
        _FakeProc(300, 1, 14.0, ["notepad.exe"]),
        _FakeProc(301, 1, 14.0, ["explorer.exe"]),
    ]
    slots = _slot_rows([101, 102, 201])
    jobs = [SimpleNamespace(pid="200", tag="own", id="j")]
    want = _old_collect_local(slots, jobs, procs)
    assert [(t.pid, t.slots, t.tag) for t in want] == [(100, 2, "lap")]

    by_pid = {p.pid: p for p in procs}
    _FakeProc.asked = []
    monkeypatch.setattr(slot_budget, "busy_slots", lambda: slots)
    monkeypatch.setattr(untracked, "_CMDLINES", {})
    store = SimpleNamespace(jobs=lambda state=None: jobs)
    # the psutil route (no bulk reader) ...
    monkeypatch.setattr(proc_bulk, "snapshot", lambda: None)
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: iter(procs))
    got = collect_local(store)
    assert got == want
    assert {pid for pid, _ in _FakeProc.asked} == {100, 101, 102, 200, 201, 1}, "chain members only"
    # ... and the bulk route, which has no Process objects at all until a command line is needed
    _FakeProc.asked = []
    monkeypatch.setattr(untracked, "_CMDLINES", {})
    bulk = {p.pid: proc_bulk.ProcInfo(p.pid, p.info["ppid"], "x", p.info["create_time"], 0.0, 0, 0) for p in procs}
    monkeypatch.setattr(proc_bulk, "snapshot", lambda: bulk)
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: pytest.fail("the bulk list is enough"))
    monkeypatch.setattr(psutil, "Process", lambda pid: by_pid[pid])
    assert collect_local(store) == want
    _FakeProc.asked = []
    assert collect_local(store) == want
    assert _FakeProc.asked == [], "the second pass finds every chain member's command line known"


def test_988_collect_local_without_a_slot_holder_reads_no_process_table(monkeypatch) -> None:
    import psutil

    monkeypatch.setattr(slot_budget, "busy_slots", lambda: [] )
    monkeypatch.setattr(proc_bulk, "snapshot", lambda: pytest.fail("no slot, no table"))
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: pytest.fail("no slot, no table"))
    assert collect_local(SimpleNamespace(jobs=lambda state=None: [])) == []
    monkeypatch.setattr(slot_budget, "busy_slots", lambda: [{"slot": 1, "pid": None, "role": "queue"}])
    assert collect_local(SimpleNamespace(jobs=lambda state=None: [])) == []


@pytest.mark.skipif(sys.platform != "win32", reason="the one-call process list is a Windows reader")
def test_988_the_one_call_process_list_agrees_with_psutil() -> None:
    import psutil

    bulk = proc_bulk.snapshot()
    assert bulk is not None and len(bulk) > 20
    checked = same_ppid = same_name = close_rss = 0
    for p in psutil.process_iter(["pid", "ppid", "name", "memory_info"], ad_value=None):
        got = bulk.get(p.pid)
        if got is None or p.pid in (0, 4):
            continue
        checked += 1
        same_ppid += got.ppid == p.info["ppid"]
        same_name += got.name == (p.info["name"] or "")
        mem = p.info["memory_info"]
        close_rss += mem is None or abs(mem.rss - got.rss) <= max(0.25 * mem.rss, 4 << 20)
    assert checked > 20
    assert same_ppid >= 0.97 * checked, (same_ppid, checked)
    assert same_name >= 0.95 * checked, (same_name, checked)
    assert close_rss >= 0.9 * checked, (close_rss, checked)
    me = bulk[__import__("os").getpid()]
    assert abs(me.create_time - psutil.Process().create_time()) < 0.05
