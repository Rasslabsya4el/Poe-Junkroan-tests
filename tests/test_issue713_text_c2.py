from junkroan.optimizer import stage_catalog, step_text_c2

KEYS = ["tree seed toward <stat>", "tree greedy", "gear pass 2 (with tree)", "tree rebuilt on gear", "anoint", "flasks"]


def test_keys_present():
    assert sorted(step_text_c2.TEXT) == sorted(KEYS)


def test_each_complete():
    for key in KEYS:
        assert step_text_c2.TEXT[key].is_complete(), key


def test_keys_are_real_steps():
    names = {s.name for s in stage_catalog.STEPS}
    for key in KEYS:
        assert key in names, key
