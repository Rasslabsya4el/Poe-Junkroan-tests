"""#745: the lock's `started` (and the status `elapsed_s`) is that of the run going now, not of the first of a row."""
from __future__ import annotations

from tools.agentops import full_run, merge_status as ms

T0 = 1_800_000_000.0


def _status(root, now):
    f = ms.collect(root, clock=now)["full_run"]
    text = ms.render_text({"running": None, "full_run": f, "waiting": [], "landed": []})
    return f, text


def _clocked(monkeypatch, clock):
    real = full_run._iso
    monkeypatch.setattr(full_run, "_iso", lambda t=None: real(clock[0] if t is None else t))


def test_row1_second_run_of_a_row_counts_from_its_own_start(tmp_path, monkeypatch):
    clock = [T0]
    _clocked(monkeypatch, clock)
    seen = []

    def fake_one_run(commit, root, cmd, env, gh, shared):
        if not seen:
            clock[0] += 1800  # the first run: 30 min
            full_run.write_pending(root, "x")
        else:
            clock[0] += 120  # the second run: read 2 min in
            seen.append(_status(root, clock[0]))
        seen.append(commit) if len(seen) == 0 else None
        return 0

    monkeypatch.setattr(full_run, "_one_run", fake_one_run)
    monkeypatch.setattr(full_run._merge, "resolve_suite_cmd", lambda *_: "x")
    monkeypatch.setattr(full_run._merge, "resolve_suite_env", lambda: {})
    monkeypatch.setattr(full_run._merge, "resolve_suite_shared", lambda: None)
    heads = iter(["c1", "c2"])
    full_run.run_full(None, root=tmp_path, gh=object(), resolve_head=lambda: next(heads))
    f, text = seen[-1]
    assert abs(f["elapsed_s"] - 120) <= 2
    assert "running 2 min" in text


def test_row2_one_run_alone_read_9_min_in(tmp_path, monkeypatch):
    clock = [T0]
    _clocked(monkeypatch, clock)
    got = []

    def fake_one_run(commit, root, cmd, env, gh, shared):
        clock[0] += 540
        got.append(_status(root, clock[0]))
        return 0

    monkeypatch.setattr(full_run, "_one_run", fake_one_run)
    monkeypatch.setattr(full_run._merge, "resolve_suite_cmd", lambda *_: "x")
    monkeypatch.setattr(full_run._merge, "resolve_suite_env", lambda: {})
    monkeypatch.setattr(full_run._merge, "resolve_suite_shared", lambda: None)
    full_run.run_full("c1", root=tmp_path, gh=object(), resolve_head=lambda: "c1")
    f, text = got[0]
    assert abs(f["elapsed_s"] - 540) <= 2 and "running 9 min" in text
