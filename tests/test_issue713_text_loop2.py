from junkroan.optimizer import step_text_loop2, stage_catalog
from junkroan.optimizer.step_description import MOVE_PREFIX

KEYS = ("move: gear", "move: weapon-base", "move: picks", "move: kick-tree", "move: kick-joint", "move: ascendancy-swap")


def test_all_keys_present_and_complete():
    assert set(step_text_loop2.TEXT) == set(KEYS)
    for key, desc in step_text_loop2.TEXT.items():
        assert desc.is_complete(), key


def test_keys_are_loop_moves():
    for key in step_text_loop2.TEXT:
        assert key.startswith(MOVE_PREFIX)
        assert key[len(MOVE_PREFIX):] in stage_catalog.LOOP_MOVES
