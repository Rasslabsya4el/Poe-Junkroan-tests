"""#718: a weapon line (value_first) buys the most DPS at every floor violation, under every order."""

from __future__ import annotations

import pytest

from junkroan.optimizer import wishlist_gear
from junkroan.optimizer.objective import Score
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.wishlist_gear import WishlistGear, WishlistMod

# (violation, value)
CUR_BIG = (1.2445, 1_000_000.0)
CUR_SMALL = (0.30, 900_000.0)


class _Objective:
    stat_keys = ("k",)

    def score(self, stats):
        violation, value = stats["k"]
        return Score(-violation, value)

    def violations(self, stats):
        return {"floor": stats["k"][0]}


class _Pob:
    def __init__(self, table):
        self.table = table

    def stats(self, _keys):
        return {"k": self.table["cur"]}

    def trial_stats(self, trials, _keys, mode="fast"):
        return [{"ok": True, "stats": {"k": self.table[t["item"]["raw"]]}} for t in trials]


def _pick(monkeypatch, table, order="priced"):
    gear = object.__new__(WishlistGear)
    gear.rails, gear.objective, gear.pob = Rails.load(), _Objective(), _Pob(table)
    gear.flexible_by_value = False
    gear.forced_lines = {}  # set by __init__ (#1152 reads it in _refuses)
    gear._raw = lambda base, ilvl, affixes, bench, sockets: affixes[-1].mod_id
    gear._forced_lacking = lambda slot, raw: False
    monkeypatch.setattr(wishlist_gear, "_count_items", lambda *_a, **_k: None)
    mods = {n: WishlistMod(n, "Prefix", "g" + n, 1, 1, n) for n in table if n != "cur"}
    cands = [(m, None) for m in mods.values()]
    got = gear._choose_trial("Weapon", "Base", 80, [], None, cands, sockets=None, buys_value=True, order=order)
    return None if got is None else got[0]


@pytest.mark.parametrize("order", ["priced", "floors"])
def test_row1_more_dps_wins_over_bigger_violation_cut(monkeypatch, order) -> None:
    table = {"cur": CUR_BIG, "A": (1.20, 1_111_066.0), "B": (0.90, 1_086_027.0)}
    assert _pick(monkeypatch, table, order).mod_id == "A"


def test_row2_more_dps_wins_at_violation_below_one(monkeypatch) -> None:
    table = {"cur": CUR_SMALL, "A": (0.30, 1_100_000.0), "B": (0.10, 1_000_000.0)}
    assert _pick(monkeypatch, table).mod_id == "A"


def test_row3_worsening_and_zero_value_lines_are_refused(monkeypatch) -> None:
    table = {"cur": CUR_BIG, "W": (1.30, 2_000_000.0), "Z": (1.0, 1_000_000.0)}
    assert _pick(monkeypatch, table) is None
