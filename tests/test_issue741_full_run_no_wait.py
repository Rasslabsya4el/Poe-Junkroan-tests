"""#741: run_full never waits for the merge line; with its lock taken it starts the suite at once."""
import json
import os

from tests.test_issue690_full_run import env, STUB  # noqa: F401  (the fixture)
from tools.agentops import full_run as fr
from tools.agentops import merge_status
from tools.agentops.test_select import map_dir, read_meta


def _run(env, commit):
    return fr.run_full(commit, root=env.repo, suite_cmd=env.cmd, suite_env=env.suite_env,
                       gh=lambda a: None, resolve_head=lambda: env.c3)


def _busy_line(monkeypatch):
    """A merge running and one waiting in the queue; run_full must not look at it."""
    monkeypatch.setattr(merge_status, "collect", lambda root=None: {"running": [{"branch": "orch-9"}],
                                                                    "waiting": [{"branch": "orch-10"}]})
    # stands in for the 40 min wait on code that still has one: "stayed busy" at once, never real time
    monkeypatch.setattr(fr, "wait_for_free_line", lambda *a, **k: False, raising=False)


def test_busy_merge_line_does_not_hold_the_suite_back(env, monkeypatch):
    _busy_line(monkeypatch)
    env.behave(total=4)
    assert _run(env, env.c1) == 0
    assert len(env.runs()) == 1
    assert read_meta(map_dir(env.repo))["map_commit"] == env.c1
    assert not fr.pending_path(env.repo).exists() and not fr.lock_path(env.repo).exists()


def test_second_call_while_locked_writes_pending_and_returns_0(env, monkeypatch):
    _busy_line(monkeypatch)
    fr.lock_path(env.repo).parent.mkdir(parents=True, exist_ok=True)
    fr.lock_path(env.repo).write_text(json.dumps({"pid": os.getppid(), "started": "now"}), encoding="utf-8")
    assert _run(env, env.c1) == 0
    assert fr.pending_path(env.repo).read_text() == env.c1
    assert env.runs() == [] and fr.lock_path(env.repo).exists()
