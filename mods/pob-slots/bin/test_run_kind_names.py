"""Plain-python check of the run kinds' plain Russian names (#985 b): python test_run_kind_names.py

Every kind the code can produce (`run_kind`) gets a Russian name in `kind_name`, and no run row that `runs()` hands
the pane goes without one (`kind_name` on every row of running, queued, recent and history).
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect  # noqa: E402,F401  (the generic collector loads the add-on)

addon = collect.addon()  # the project's add-on: the subject of this file


T = "2026-10-14T10:00:00+00:00"

# One command per kind `run_kind` can return, plus the tags `runs.py submit` derives (P<prio>-<#N|core>[-<n>]).
CASES = [
    # (cmd, argv, tag, issue, name the kind must get)
    ("py -3.12 scripts/benchmark.py --set core14 --tag P2-core", [], "P2-core", None, "недельный прогон"),
    ("py -3.12 scripts/benchmark.py --set core14 --tag P2-core-3", [], "P2-core-3", None, "недельный прогон"),
    ("py -3.12 scripts/benchmark.py --set smoke --seed 7 --tag P1-#600", [], "P1-#600", 600, "прогон тикета"),
    ("py -3.12 scripts/benchmark.py --tag P2-untracked", [], "P2-untracked", None, "benchmark"),
    ("C:/Python312/junkroan.exe scripts/replay_bench.py --builds x --against y", [], "P1-#601", 601, "replay"),
    ("python -m pytest -q -rfE", [], "P1-#602", 602, "тесты"),
    ('junkroan build --skill "Raise Spectre"', [], "P2-untracked", None, "билд по запросу"),
    ("python scripts/build_from_skeleton.py --from-fixture bleed_bow", [], "P2-#603", 603, ""),
    ("python scripts/probe_ramp_audit.py --build bleed_bow-s4", [], "P2-#604", 604, ""),
]


def job_of(cmd, argv, tag, issue, **kw):
    base = dict(id=f"j-{tag}", tag=tag, issue=issue, priority="P2", host="pc", workers=1, state="done", cmd=cmd,
                argv=list(argv), submit_ts=T, start_ts=T, end_ts=T, after=[], run_dir=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_every_kind_has_a_russian_name():
    kinds = set()
    for cmd, argv, tag, issue, want in CASES:
        j = job_of(cmd, argv, tag, issue)
        what = addon.run_kind(j)
        kinds.add(what)
        name = addon.kind_name(what, j)
        assert name == want, (cmd, what, name)
    # every kind run_kind can return is covered, the empty one (an unknown command) included
    assert kinds == {"benchmark", "replay", "tests", "request", ""}, kinds
    # an unknown kind (a future one) gets an empty name, as before #985
    for what in ("", None, "something-new"):
        assert addon.kind_name(what, job_of("x", [], "P2-#1", 1)) == ""


def test_runs_rows_all_carry_a_russian_name(monkeypatch, tmp_path):
    from junkroan.pob import slot_budget
    from junkroan.runs import store

    jobs = []
    for i, (cmd, argv, tag, issue, _) in enumerate(CASES):
        state = ("running", "queued", "done")[i % 3]
        jobs.append(job_of(cmd, argv, tag, issue, id=f"j-{i}", state=state,
                           start_ts=None if state == "queued" else T,
                           end_ts=T if state == "done" else None))
    monkeypatch.setattr(store, "Store", lambda _log: SimpleNamespace(jobs=lambda: jobs))
    budget = SimpleNamespace(period="day", total=10, others=0, limit_for=lambda role: 5)
    monkeypatch.setattr(slot_budget, "load_budget", lambda *a, **k: budget)
    monkeypatch.setattr(slot_budget, "slot_dir", lambda: tmp_path)
    monkeypatch.setattr(slot_budget, "busy_slots", lambda *a, **k: [])
    monkeypatch.setattr(slot_budget, "waiting", lambda *a, **k: [])
    monkeypatch.setattr(slot_budget, "current_host", lambda *a, **k: "pc")
    monkeypatch.setattr(addon, "run_cells", lambda j: None)
    monkeypatch.setattr(addon, "estimate", lambda *a, **k: (600.0, "test"))
    monkeypatch.setattr(addon, "daemon_waits", lambda host: {})
    monkeypatch.setattr(addon, "daemon_slots", lambda: None)
    monkeypatch.setattr(addon, "_history_counts", lambda js: {})
    out = addon.runs(history=True)
    rows = [r for key in ("running", "queued", "recent", "history") for r in out[key]]
    assert rows, out.keys()
    unnamed = [r["tag"] for r in rows if bool(r.get("kind_name")) != bool(r["what"] or r["bench"])]
    assert unnamed == [], unnamed
    names = {r["kind_name"] for r in rows}
    assert names >= {"недельный прогон", "прогон тикета", "replay", "тесты", "билд по запросу"}, names
    assert names <= {"недельный прогон", "прогон тикета", "benchmark", "replay", "тесты", "билд по запросу", ""}, names
    # the raw kind stays as its own field
    assert {r["what"] for r in rows} >= {"benchmark", "replay", "tests", "request", ""}


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
