"""#1153 unit 2: `replay_bench` falls back to the objective built from the delivered build when a
search-output build has no benchmark fixture. PoB-free: every PoB-facing call is replaced by a fake."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import replay_bench as rb  # noqa: E402


def test_present_fixture_is_used_and_no_fallback_runs(monkeypatch) -> None:
    calls: list[tuple] = []
    sentinel = object()
    monkeypatch.setattr(rb, "fixture_path", lambda slug: Path(__file__))
    monkeypatch.setattr(rb, "_prepared_author", lambda pob, slug, stat, log: calls.append((slug, stat)) or sentinel)
    monkeypatch.setattr(rb, "objective_from_build", lambda *a, **k: pytest.fail("fallback must not run when a fixture exists"))

    assert rb.prepared_reference(None, "z327_juggernaut_boneshatter", "CombinedDPS", print) is sentinel
    assert calls == [("z327_juggernaut_boneshatter", "CombinedDPS")]


def test_missing_fixture_returns_none_so_the_caller_falls_back(monkeypatch) -> None:
    def no_fixture(slug):
        raise FileNotFoundError(f"no fixture {slug}.pob.txt")

    monkeypatch.setattr(rb, "fixture_path", no_fixture)
    monkeypatch.setattr(rb, "_prepared_author", lambda *a, **k: pytest.fail("no fixture: the author must not be prepared"))

    assert rb.prepared_reference(None, "01 witch_occultist_no_iron_will_prophecy_wand", "CombinedDPS", print) is None


def test_objective_from_build_derives_the_objective_the_way_the_probe_does(monkeypatch) -> None:
    seen: dict[str, object] = {}
    skeleton = SimpleNamespace(main_link=["Contagion"], mode="hit")
    rails = SimpleNamespace(objective=lambda: "base-objective")
    pob = SimpleNamespace(export_xml=lambda: "<xml/>")

    monkeypatch.setattr(rb, "skeleton_from_xml", lambda xml, pob, log: seen.setdefault("xml", xml) and skeleton)
    monkeypatch.setattr(rb.Rails, "load", classmethod(lambda cls, *a, **k: rails))
    monkeypatch.setattr(rb, "forced_keystones_of", lambda sk: ("Mind over Matter",))

    def fake_objective_for(rails_arg, main, base=None, *, mode=None, forced_keystones=()):
        seen.update(main=main, base=base, mode=mode, forced=tuple(forced_keystones))
        return "objective"

    monkeypatch.setattr(rb, "objective_for", fake_objective_for)

    prepared = rb.objective_from_build(pob, print)

    assert prepared.rails is rails and prepared.objective == "objective"
    assert seen == {"xml": "<xml/>", "main": "Contagion", "base": "base-objective", "mode": "hit", "forced": ("Mind over Matter",)}


def test_fallback_is_labelled_in_the_report_row() -> None:
    assert rb.NO_FIXTURE_PREPARATION == "no fixture: objective from the build"
    row = {"ok": True, "reference": "witch_occultist", "source": "a.pob.txt", "preparation": rb.NO_FIXTURE_PREPARATION,
           "recorded_value": None, "replayed_value": 100.0, "value_before": 100.0, "value_after": 110.0,
           "gain_percent": 10.0, "seconds": 1.0, "kept": 1, "not_kept": 0, "judged_and_reverted": 0,
           "violation_before": 0.0, "violation_after": 0.0, "start_infeasible": False, "audit_errors": 0,
           "replayed_over_recorded": None, "damage_kind": "spell", "start_violated": []}
    report = rb.render_report([row], stamp="s", move="utilities", passes=1, workers=1, seconds=1.0)
    assert "`a.pob.txt` (no fixture: objective from the build)" in report
