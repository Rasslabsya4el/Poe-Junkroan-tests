"""#713 rows 1, 3: every step and loop move the pipeline can record has a complete description, none extra,
and docs/BUILD_STEPS.md carries every step and every description text (times move with the weekly run, so they
are not compared here; `python scripts/build_steps_doc.py --check` is the full no-diff check)."""

import importlib.util
from pathlib import Path

from junkroan.optimizer import stage_catalog
from junkroan.optimizer.step_description import MOVE_PREFIX

ROOT = Path(__file__).resolve().parents[1]


def _expected_keys():
    return [s.name for s in stage_catalog.STEPS] + [MOVE_PREFIX + m for m in stage_catalog.LOOP_MOVES]


def test_every_step_and_move_has_a_complete_description():
    texts = stage_catalog.descriptions()
    missing = [k for k in _expected_keys() if k not in texts]
    assert not missing, f"no description for: {missing}"
    incomplete = [k for k in _expected_keys() if not texts[k].is_complete()]
    assert not incomplete, f"incomplete (5 fields, where, >= 3 sentences): {incomplete}"


def test_no_description_for_a_step_that_does_not_exist():
    extra = sorted(set(stage_catalog.descriptions()) - set(_expected_keys()))
    assert not extra, f"description without a step: {extra}"


def test_page_carries_every_step_and_description():
    page = (ROOT / "docs" / "BUILD_STEPS.md").read_text(encoding="utf-8")
    texts = stage_catalog.descriptions()
    for s in stage_catalog.STEPS:
        assert f"### {s.label}" in page, f"page lacks step {s.name!r}"
        assert texts[s.name].what_it_changes in page, f"page text of {s.name!r} is out of date"
    for m in stage_catalog.LOOP_MOVES:
        assert f"#### {m}" in page, f"page lacks move {m!r}"
        assert texts[MOVE_PREFIX + m].what_it_changes in page, f"page text of move {m!r} is out of date"
    assert "NO DESCRIPTION YET" not in page
