"""#553 unit 6: the line-by-line choice inside one wishlist item follows the order fill_slot was given."""

from __future__ import annotations

from types import SimpleNamespace

from junkroan.optimizer import wishlist_gear
from junkroan.optimizer.objective import Score
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.wishlist_gear import WishlistGear, WishlistMod

# the item as it stands: violation 0.5 at value 1000
CURRENT = (0.5, 1000.0)
# A cuts violation to 0.3 at a large value loss; B keeps the value at violation 0.45
STATS = {"cur": CURRENT, "A": (0.3, 400.0), "B": (0.45, 1000.0)}


class _Objective:
    stat_keys = ("k",)

    def score(self, stats):
        violation, value = stats["k"]
        return Score(-violation, value)

    def violations(self, stats):
        return {"floor": stats["k"][0]}


class _Pob:
    def stats(self, _keys):
        return {"k": STATS["cur"]}

    def trial_stats(self, trials, _keys, mode="fast"):
        return [{"ok": True, "stats": {"k": STATS[t["item"]["raw"]]}} for t in trials]


def _gear(monkeypatch) -> tuple[WishlistGear, WishlistMod, WishlistMod]:
    gear = object.__new__(WishlistGear)
    gear.rails, gear.objective, gear.pob = Rails.load(), _Objective(), _Pob()
    gear.flexible_by_value = False
    gear.forced_lines = {}  # set by __init__ (#1152 reads it in _refuses)
    gear._raw = lambda base, ilvl, affixes, bench, sockets: affixes[-1].mod_id
    gear._forced_lacking = lambda slot, raw: False
    monkeypatch.setattr(wishlist_gear, "_count_items", lambda *_a, **_k: None)
    return gear, WishlistMod("A", "Prefix", "ga", 1, 1, "a"), WishlistMod("B", "Prefix", "gb", 1, 1, "b")


def test_choose_trial_default_cuts_violation_priced_keeps_value(monkeypatch) -> None:
    gear, a, b = _gear(monkeypatch)
    cands = [(a, None), (b, None)]
    kw = dict(sockets=None, buys_value=False)
    assert gear._choose_trial("Helmet", "Base", 80, [], None, cands, **kw)[0] is a
    assert gear._choose_trial("Helmet", "Base", 80, [], None, cands, order="floors", **kw)[0] is a
    assert gear._choose_trial("Helmet", "Base", 80, [], None, cands, order="priced", **kw)[0] is b


def test_fill_slot_passes_its_order_to_choose_trial(monkeypatch) -> None:
    gear = object.__new__(WishlistGear)
    seen: list[str] = []

    def fake_build(result, base, **kw):
        seen.append(kw["order"])
        result.raw = "raw"
        return Score(0.0, 1.0)

    gear.rails = Rails.load()
    gear.objective = _Objective()
    gear.pob = SimpleNamespace(stats=lambda _k: {"k": CURRENT}, equip=lambda _x: None)
    gear.current_raw = {}
    gear._build_on_base = fake_build
    gear._rank_bases = lambda *a, **k: [SimpleNamespace(base="Base", payment=None)]
    gear._resistance_assignments = {"Helmet": "fire"}
    gear._keep_incumbent = lambda slot, result, score, **kw: score
    gear.base_candidates = lambda base: [base]
    gear.base_screen = {}
    monkeypatch.setattr(wishlist_gear, "restore_weapon_partner", lambda *a, **k: None)
    try:
        gear.fill_slot("Helmet", "Base", order="priced")
    except Exception:
        pass  # only the call into _build_on_base matters here
    assert seen == ["priced"]
