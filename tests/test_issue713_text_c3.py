"""#713 unit c3: every step of this unit has a complete description and is a real catalog step."""

from __future__ import annotations

from junkroan.optimizer import step_text_c3
from junkroan.optimizer.stage_catalog import STEPS

KEYS = ("clusters", "jewels", "supports re-picked", "utility links", "fill", "tree refine", "anoint re-pick", "config (final lanes)")


def test_all_keys_present():
    assert set(step_text_c3.TEXT) == set(KEYS)


def test_each_complete():
    for key in KEYS:
        assert step_text_c3.TEXT[key].is_complete(), key


def test_each_key_is_a_catalog_step():
    names = {s.name for s in STEPS}
    for key in KEYS:
        assert key in names, key
