from types import SimpleNamespace

from junkroan.runs.untracked import collect_local, untracked_trees  # noqa: F401

QUEUE = "python scripts/run_queue.py plan.json --tag new18-tpl-main3-s4-lap"
WORKER = "python headless_runtime_worker.py"


def _table(extra=None):
    t = {1: (0, 1.0, "init"), 12260: (1, 100.0, QUEUE)}
    for i in (1, 2, 3):
        t[12260 + i] = (12260, 101.0, WORKER)
    t.update(extra or {})
    return t


def _rows(pids):
    return [{"slot": n + 1, "pid": p, "role": "queue", "age_seconds": 5.0, "cmd": ""} for n, p in enumerate(pids)]


def test_untracked_queue_tree():
    trees = untracked_trees(_rows([12261, 12262, 12263]), [], _table())
    assert len(trees) == 1
    t = trees[0]
    assert (t.pid, t.slots, t.tag, t.started) == (12260, 3, "new18-tpl-main3-s4-lap", 100.0)
    assert t.cmd_head == QUEUE[:80]


def test_tracked_by_job_pid():
    job = SimpleNamespace(pid=12260, tag="x", id="j")
    assert untracked_trees(_rows([12261, 12262, 12263]), [job], _table()) == []



def test_tracked_by_job_pid_held_as_a_string():
    # the store writes pid as a string: the daemon's own filler was reported untracked (#365)
    job = SimpleNamespace(pid="12260", tag="x", id="j")
    assert untracked_trees(_rows([12261, 12262, 12263]), [job], _table()) == []


def test_mixed():
    extra = {500: (1, 50.0, "python scripts/run_queue.py --tag=other"), 501: (500, 51.0, WORKER), 502: (500, 51.0, WORKER)}
    job = SimpleNamespace(pid=500, tag="other", id="j")
    trees = untracked_trees(_rows([501, 502, 12261]), [job], _table(extra))
    assert [(t.pid, t.slots) for t in trees] == [(12260, 1)]


def test_tag_equals_form():
    t = {7: (1, 1.0, "python scripts/benchmark.py --tag=abc"), 8: (7, 2.0, WORKER)}
    assert untracked_trees(_rows([8]), [], t)[0].tag == "abc"


def test_missing_parent_is_own_root():
    trees = untracked_trees(_rows([999]), [], {999: (998, 5.0, "python x.py")})
    assert [(t.pid, t.slots, t.tag) for t in trees] == [(999, 1, None)]


def test_slot_pid_absent_from_process_table_yields_nothing():
    job = SimpleNamespace(pid="12260", tag="x", id="j")
    assert untracked_trees(_rows([777]), [job], _table()) == []


def test_deep_descendant_of_a_running_job_is_tracked():
    t = {
        1: (0, 1.0, "init"),
        100: (1, 2.0, "junkroan.exe run"),
        101: (100, 3.0, "python scripts/benchmark.py"),
        102: (101, 4.0, "python -c pool worker"),
        103: (102, 5.0, WORKER),
    }
    job = SimpleNamespace(pid="100", tag="x", id="j")
    assert untracked_trees(_rows([103]), [job], t) == []


def test_tree_without_evidence_is_not_returned():
    rows = [{"slot": 1, "pid": None, "role": "queue", "age_seconds": 1.0, "cmd": ""}]
    assert untracked_trees(rows, [], _table()) == []
    assert untracked_trees(_rows([4242]), [], {}) == []
    assert untracked_trees(_rows([4242]), [], {4242: (1, None, "")}) == []  # in the table, unreadable


def test_collect_local_reads_busy_slots_before_the_process_table(monkeypatch):
    import psutil

    from junkroan.pob import slot_budget

    calls = []

    def fake_busy():
        calls.append("busy_slots")
        return _rows([12261])

    def fake_iter(attrs):
        calls.append("process_iter")
        return iter(())

    from junkroan.runs import proc_bulk

    monkeypatch.setattr(slot_budget, "busy_slots", fake_busy)
    monkeypatch.setattr(proc_bulk, "snapshot", lambda: None)  # #988: the one-call list is tested in test_runs_tick_cost_988
    monkeypatch.setattr(psutil, "process_iter", fake_iter)
    store = SimpleNamespace(jobs=lambda state=None: calls.append("jobs") or [])
    assert collect_local(store) == []
    assert calls == ["busy_slots", "process_iter", "jobs"]
