"""#427: `replay_bench --mark-picked` marks only the groups the live utility picker could have made."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from junkroan.search.skeleton import SocketGroup  # noqa: E402
from replay_bench import mark_picked_utilities  # noqa: E402

ACTIVE = {"blink arrow": {}, "frostblink": {}}


class _Skel:
    def __init__(self) -> None:
        self.main_link = ["Fireball", "Spell Echo"]
        self.extra_groups = [
            SocketGroup(gems=["Blink Arrow"], slot="Boots"),
            SocketGroup(gems=["Frostblink", "Faster Casting"], slot="Gloves"),
            SocketGroup(gems=["Spell Echo"], slot="Helmet"),
            SocketGroup(gems=["Frostblink"], slot="Weapon 1", enabled=False),
        ]


def test_marks_only_single_active_gem_enabled_groups() -> None:
    skel = _Skel()
    assert mark_picked_utilities(skel, ACTIVE) == 1
    assert [g.picked for g in skel.extra_groups] == [True, False, False, False]
    assert skel.main_link == ["Fireball", "Spell Echo"]


def test_without_the_flag_nothing_is_marked() -> None:
    skel = _Skel()  # the helper is only called under --mark-picked
    assert not any(g.picked for g in skel.extra_groups)
