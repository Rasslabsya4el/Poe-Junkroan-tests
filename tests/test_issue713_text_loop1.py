"""#713: the loop1 descriptions are complete and keyed by real step names / loop moves."""

from junkroan.optimizer import stage_catalog, step_text_loop1
from junkroan.optimizer.step_description import MOVE_PREFIX

STEP_KEYS = ("loop opening", "loop pass <N>", "fixed point check", "repair pass <N>")
MOVES = ("refine", "swaps", "regions", "corridors", "aura levels", "lanes")


def test_all_keys_present():
    expected = set(STEP_KEYS) | {MOVE_PREFIX + m for m in MOVES}
    assert set(step_text_loop1.TEXT) == expected
    assert len(step_text_loop1.TEXT) == 10


def test_each_complete():
    for key, d in step_text_loop1.TEXT.items():
        assert d.is_complete(), key
        assert ".py:" in d.where, key


def test_keys_are_real():
    names = {s.name for s in stage_catalog.STEPS}
    for key in step_text_loop1.TEXT:
        if key.startswith(MOVE_PREFIX):
            assert key[len(MOVE_PREFIX):] in stage_catalog.LOOP_MOVES, key
        else:
            assert key in names, key
