"""#34 unit 3: an enabler-hook Score measured on the old gear is never reused after a kept gear move (no PoB)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_tree_optimizer_speed import POWER_ON, S, _graph, _hooking, _opt, _Pob  # noqa: E402


def _two_allocates(*, gear_move_kept: bool):
    graph = _graph()
    pob = _Pob(graph, toggles=POWER_ON)
    opt = _opt(pob, graph)
    _hooking(opt, [])
    opt.allocate(2, allocated={S})
    first = opt.hook_calls
    if gear_move_kept:
        opt.note_build_change()  # what the pipeline sends after a kept gear move
    opt.allocate(2, allocated=set(pob.allocated))
    return opt, first


def test_kept_gear_move_makes_the_next_allocate_ask_the_hook_again() -> None:
    opt, first = _two_allocates(gear_move_kept=True)
    assert first == 1
    assert opt.hook_calls > first, "a hook Score measured on the old gear was reused"


def test_without_a_gear_move_the_hook_answer_is_still_cached() -> None:
    opt, first = _two_allocates(gear_move_kept=False)
    assert opt.hook_calls == first == 1
    assert opt.hook_skipped_cached >= 1
