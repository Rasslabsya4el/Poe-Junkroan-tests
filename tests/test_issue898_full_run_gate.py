"""#898 row 10: `full-run` is held back while the PC is busy; the merge's own suite run is not."""
import inspect

from tests.test_issue690_full_run import env, STUB  # noqa: F401  (the fixture)
from tools.agentops import full_run as fr
from tools.agentops import merge as merge_mod
from junkroan.pob import slot_budget as sb

NOW = 1_000_000.0


def _gate(mean, mode="normal"):
    samples = [(NOW - 60 * i, mean) for i in range(10)]
    return lambda: sb.admission_now(now=NOW, samples=samples, mode=mode, cores=12)


def _run(env, admission, capsys=None):
    return fr.run_full(env.c1, root=env.repo, suite_cmd=env.cmd, suite_env=env.suite_env,
                       gh=lambda a: None, resolve_head=lambda: env.c3, admission=admission)


def test_busy_pc_does_not_start(env, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(fr, "_one_run", lambda *a, **k: calls.append(1) or 0)
    adm = _gate(9.2)
    line = adm().line()
    assert "9.2" in line and "9.0" in line, line
    assert _run(env, adm) == 0
    assert calls == []
    out = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
    assert len(out) == 1 and "9.2" in out[0] and "9.0" in out[0]
    assert not fr.lock_path(env.repo).exists()


def test_free_pc_starts(env, monkeypatch):
    calls = []
    monkeypatch.setattr(fr, "_one_run", lambda *a, **k: calls.append(1) or 0)
    adm = _gate(7.9)
    assert adm().go
    assert _run(env, adm) == 0
    assert calls == [1]


def test_error_in_check_means_go(env, monkeypatch):
    calls = []
    monkeypatch.setattr(fr, "_one_run", lambda *a, **k: calls.append(1) or 0)

    def boom():
        raise RuntimeError("no samples")
    assert _run(env, boom) == 0
    assert calls == [1]


def test_merge_suite_path_never_asks_admission(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the merge's suite run asked the admission gate")
    monkeypatch.setattr(sb, "admission_now", boom)
    seen = []
    monkeypatch.setattr(merge_mod, "_run_suite", lambda *a, **k: seen.append(1) or (True, ""))
    assert fr.run_suite_by_merge_state("cmd", None, {}, None, None) == (True, "")
    assert seen == [1]
    assert "admission" not in inspect.getsource(merge_mod._run_suite) + inspect.getsource(merge_mod._run_suite_unreserved)
