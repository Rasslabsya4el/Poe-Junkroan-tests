"""The construction loot roll (2026-09-18): the two construction rolls draw best of 600, the
improvement loop's per-slot re-rolls keep best of 200.

The seed-to-seed spread of a rebuilt reference is born in gear pass 1's loot roll and the
deterministic tree greedy amplifies it: N=600 measured on stormbrand / bleed_bow at the greedy
stage lifted the value by +6.7 / +35.5 points of the author's number and cut the spread by
7.5 / 8.4 points, for +22 / +39 s per construction. No PoB needed.
"""

from __future__ import annotations

import json
from pathlib import Path

from junkroan.optimizer.loot_gear import LootGear
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.pipeline import SCREEN_LOOT_N, construction_loot_n
from junkroan.optimizer.rails import Rails


def test_the_rails_carry_600_for_construction_and_200_for_the_loop() -> None:
    rails = Rails.load()
    assert rails.gear.construction_best_of_n == 600
    assert rails.gear.loot_best_of_n == 200


def test_a_rails_file_without_the_field_still_loads_at_200(tmp_path: Path) -> None:
    """Old rails files (and the dataclass default) keep the pre-2026-09-18 behaviour."""

    path = tmp_path / "rails.json"
    path.write_text(json.dumps({"name": "old", "gear": {"loot_best_of_n": 200}}), encoding="utf-8")
    rails = Rails.load(path)
    assert rails.gear.construction_best_of_n == 200 and rails.gear.loot_best_of_n == 200


def test_construction_loot_n_default_screen_and_explicit() -> None:
    rails = Rails.load()
    assert construction_loot_n(rails, None, False) == 600  # the construction rolls of a real build
    assert construction_loot_n(rails, SCREEN_LOOT_N, True) == SCREEN_LOOT_N  # a screen keeps its cheap roll
    assert construction_loot_n(rails, None, True) == SCREEN_LOOT_N
    assert construction_loot_n(rails, 42, False) == 42  # the caller's own N wins over both


class _Pob:
    """Enough of PobSession for `fill_slot` to reach its roll and return with nothing."""

    def __init__(self) -> None:
        self.rolled_n: list[int] = []

    def stats(self, keys):
        return {k: 0.0 for k in keys} | {"CombinedDPS": 1000.0}

    def random_rares(self, base, n=None, ilvl=None, quality=None, sockets=None, seed=None):
        self.rolled_n.append(n)
        return []

    def trial_stats(self, trials, keys, mode="fast"):
        return []


def test_a_per_slot_re_roll_with_no_n_rolls_loot_best_of_n() -> None:
    """The improvement loop hands `fill_slot` its `loot_n` (None on a normal run), so the re-rolls
    stay at `loot_best_of_n` = 200 while the construction rolls are asked for 600."""

    pob = _Pob()
    loot = LootGear(pob, Objective(maximize="CombinedDPS"), Rails.load())

    loot.fill_slot("Boots", "Two-Toned Boots", n=None, seed=1)

    assert pob.rolled_n == [200]


def test_the_log_line_says_the_roll_it_actually_made() -> None:
    """The per-slot line prints the rolls PoB returned, so a construction roll reads "best of 600"
    and a loop re-roll "best of 200" -- never a constant."""

    class _RollingPob(_Pob):
        def __init__(self) -> None:
            super().__init__()
            self.equipped: list[dict] = []

        def random_rares(self, base, n=None, ilvl=None, quality=None, sockets=None, seed=None):
            self.rolled_n.append(n)
            return [{"raw": f"r{i}", "mod_ids": set()} for i in range(n)]

        def trial_stats(self, trials, keys, mode="fast"):
            return [{"ok": True, "stats": {k: 0.0 for k in keys} | {"CombinedDPS": 1000.0 + i}} for i, _t in enumerate(trials)]

        def equip(self, items):
            self.equipped.append(items)

    for n, expected in ((600, "best of 600"), (200, "best of 200")):
        lines: list[str] = []
        pob = _RollingPob()
        loot = LootGear(pob, Objective(maximize="CombinedDPS"), Rails.load(), log=lines.append)

        loot.fill_slot("Boots", "Two-Toned Boots", n=n, seed=1, bench=False)

        assert pob.rolled_n == [n]
        assert lines and expected in lines[0], lines


def test_the_gear_dataclass_default_is_the_old_number() -> None:
    """A Rails built in code, with no file behind it, behaves as it did before 2026-09-18."""

    assert Rails().gear.construction_best_of_n == 200
