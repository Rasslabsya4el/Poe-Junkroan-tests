import importlib.util
import json
import re
from pathlib import Path

from junkroan.optimizer import stage_catalog
from junkroan.optimizer.step_description import MOVE_PREFIX, Description

spec = importlib.util.spec_from_file_location(
    "build_steps_doc", Path(__file__).resolve().parents[1] / "scripts" / "build_steps_doc.py")
bsd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bsd)

D = Description("Changes a. B.", "Tries c.", "Judged d.", "Keeps e.", "Never skipped.", "x.py:f")


def _run(tmp_path, monkeypatch, missing=()):
    texts = {s.name: D for s in stage_catalog.STEPS}
    texts.update({MOVE_PREFIX + m: D for m in stage_catalog.LOOP_MOVES})
    for k in missing:
        texts.pop(k)
    monkeypatch.setattr(stage_catalog, "descriptions", lambda: texts)
    rows = tmp_path / "run" / "rows"
    rows.mkdir(parents=True)
    stages = [{"name": "skeleton applied", "seconds": 3.1 * 60, "notes": "n1"},
              {"name": "loop pass 1", "seconds": 5000}]
    # #720: --check wants a time or a condition for every step, so the run times the rest
    stages += [{"name": s.name.replace("<N>", "1"), "seconds": 1.0} for s in stage_catalog.STEPS
               if s.name not in ("skeleton applied", "loop pass <N>") and stage_catalog.condition_of(s.name) is None
               and "<" not in s.name]
    (rows / "b-s1.json").write_text(json.dumps({"stages": stages, "move_rows": [
        {"move": "gear Boots", "seconds": 100}, {"move": "gear Belt", "seconds": 86},
        {"move": "kick joint", "seconds": 7}]}))
    return tmp_path / "run"


def test_all_steps_and_moves_present(tmp_path, monkeypatch):
    page = bsd.generate(bsd.load_run(_run(tmp_path, monkeypatch)))
    for s in stage_catalog.STEPS:
        assert f"### {s.label}" in page
    for m in stage_catalog.LOOP_MOVES:
        assert f"#### {m}" in page
    assert "NO DESCRIPTION YET" not in page


def test_missing_description(tmp_path, monkeypatch):
    page = bsd.generate(bsd.load_run(_run(tmp_path, monkeypatch, missing=["tree greedy", MOVE_PREFIX + "refine"])))
    assert page.count("NO DESCRIPTION YET") == 2


def test_deterministic_and_check(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch)
    out = tmp_path / "page.md"
    args = ["--run", str(run), "--out", str(out)]
    assert bsd.main(args) == 0
    first = out.read_text(encoding="utf-8")
    assert bsd.main(args) == 0 and out.read_text(encoding="utf-8") == first
    assert bsd.main(args + ["--check"]) == 0
    out.write_text(first.replace("How a build", "How a bUild", 1), encoding="utf-8")
    assert bsd.main(args + ["--check"]) == 1


def test_no_bare_big_seconds_and_time_format(tmp_path, monkeypatch):
    page = bsd.generate(bsd.load_run(_run(tmp_path, monkeypatch)))
    assert not re.search(r"\b\d{3,}\s*s\b", page)
    assert "3.1 min" in page  # skeleton applied median
    assert "Median time per build: 3.1 min." in page  # gear: 100 + 86 s summed
