"""#713 unit c1: the descriptions of the opening construction steps exist, are complete, and name real steps."""

from junkroan.optimizer import stage_catalog, step_text_c1

KEYS = (
    "skeleton applied", "config (conservative lane)", "rig gear", "rig tree", "gear pass 1 (rig tree)",
    "gear pass 1 (empty tree)", "config re-derived (after gear pass 1)", "flat-reservation aura levels",
    "supports re-picked (no number)",
)


def test_all_keys_present():
    assert set(step_text_c1.TEXT) == set(KEYS)


def test_each_description_is_complete():
    for key in KEYS:
        assert step_text_c1.TEXT[key].is_complete(), key


def test_each_key_is_a_real_step():
    names = {s.name for s in stage_catalog.STEPS}
    for key in step_text_c1.TEXT:
        assert key in names, key
