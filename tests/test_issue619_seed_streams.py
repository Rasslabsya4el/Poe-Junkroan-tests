"""#619: the seed reaches the picks that were a tie, and only those. PoB-free.

The weekly run of 2026-10-05 gave stormbrand and hit_penance_brand one build on seeds 4, 5 and 6, move for move.
The rows show where the seed went: of 78 (77) moves, the 7 seeded ones (kick tree x3, kick joint x4) are drawn per
seed but every one ends reverted with `before == after`, while the construction and the loop's gear and tree moves
never took the seed (`WishlistGear.fill_slot` did `del n, seed`; the tree greedy has no stream). The fix lets the seed
break an exact tie between candidates PoB scored the same, in the template's open line and in the tree greedy.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from junkroan.optimizer.objective import Score
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.seeds import PURPOSE_TEMPLATE_TIES, PURPOSE_TREE_TIES, derive_seed, tie_rank
from junkroan.optimizer.tree_optimizer import TreeOptimizer
from junkroan.optimizer.wishlist_gear import WishlistGear, WishlistMod

ROWS = Path(__file__).resolve().parents[1] / "artifacts" / "benchmark" / "20261005-1220-gate-20261005" / "rows"
SEEDS = (4, 5, 6)


# -- the recorded rows: what was seeded and what it left --------------------------------------------

@pytest.mark.skipif(not (ROWS / "stormbrand-s4.json").is_file(), reason="the recorded weekly rows are not present")
@pytest.mark.parametrize("slug", ["stormbrand", "hit_penance_brand"])
def test_recorded_rows_the_seeded_moves_were_drawn_and_left_nothing(slug: str) -> None:
    rows = [json.loads((ROWS / f"{slug}-s{s}.json").read_text(encoding="utf-8")) for s in SEEDS]
    assert [r["seed"] for r in rows] == list(SEEDS)  # (a) the seeds the rows record differ: the seed was given
    assert len({r["ours"] for r in rows}) == 1  # and the three finals are one number
    for row in rows:
        kicks = [m for m in row["move_rows"] if m["move"].startswith("kick")]
        assert len(kicks) == 7  # (b) 3 kick tree + 4 kick joint, the only moves that took a stream
        assert all(m["before"] == m["after"] and not m["kept"] for m in kicks)  # drawn, then discarded


def test_the_child_seeds_of_three_build_seeds_differ_at_every_tie_purpose() -> None:
    for purpose in (PURPOSE_TEMPLATE_TIES, PURPOSE_TREE_TIES):
        assert len({derive_seed(s, purpose) for s in SEEDS}) == 3


# -- the tie rank -----------------------------------------------------------------------------------

def test_tie_rank_is_stable_per_seed_and_orders_labels_differently_per_seed() -> None:
    labels = [f"candidate {i}" for i in range(12)]

    def order(seed: int) -> list[str]:
        return sorted(labels, key=lambda label: tie_rank(seed, PURPOSE_TREE_TIES, label), reverse=True)

    assert order(4) == order(4)
    assert len({tuple(order(s)) for s in SEEDS}) == 3


# -- the tree greedy --------------------------------------------------------------------------------

def _entry(node_id: int, value: float, *, neg_violation: float = 0.0, cost: int = 1):
    meta = {"candidate": SimpleNamespace(node_id=node_id), "trial": {}}
    return (meta, {}, Score(neg_violation, value), cost)


def _picked(tie_seed: int | None, entries) -> int:
    opt = object.__new__(TreeOptimizer)
    opt.tie_seed = tie_seed
    best = opt._choose(Score(0.0, 100.0), list(entries), 10)
    return best[0]["candidate"].node_id


def test_the_greedy_breaks_an_exact_tie_by_seed_and_keeps_the_first_without_one() -> None:
    tied = [_entry(node, 150.0) for node in range(1000, 1012)]  # twelve nodes PoB scored alike
    assert _picked(None, tied) == 1000  # no seed: the first listed, as before
    assert _picked(None, list(reversed(tied))) == 1011
    picks = {s: _picked(derive_seed(s, PURPOSE_TREE_TIES), tied) for s in SEEDS}
    assert len(set(picks.values())) >= 2, picks  # the old pick was one node for every seed
    for s in SEEDS:  # the pick does not depend on the listing order
        assert _picked(derive_seed(s, PURPOSE_TREE_TIES), list(reversed(tied))) == picks[s]


def test_the_greedy_never_overrules_a_number_pob_separated() -> None:
    entries = [_entry(node, 150.0) for node in range(1000, 1012)] + [_entry(2000, 150.5)]
    for s in SEEDS:
        assert _picked(derive_seed(s, PURPOSE_TREE_TIES), entries) == 2000


# -- the template's open line -----------------------------------------------------------------------

class _FakePob:
    def __init__(self, values: dict[str, float]) -> None:
        self.values = values

    def trial_stats(self, trials, keys, mode="fast"):
        return [{"ok": True, "stats": {"v": self.values[t["item"]["raw"]]}} for t in trials]

    def stats(self, keys):
        return {"v": 100.0}


class _FakeObjective:
    stat_keys = ("v",)

    def score(self, stats):
        return Score(0.0, stats["v"])

    def violations(self, stats):
        return {}


def _gear(values: dict[str, float], tie_seed: int | None) -> WishlistGear:
    gear = object.__new__(WishlistGear)
    gear.rails = Rails.load()
    gear.pob = _FakePob(values)
    gear.objective = _FakeObjective()
    gear.tie_seed = tie_seed
    gear.forced_lines = {}  # set by __init__ (#1152 reads it in _refuses)
    gear.flexible_by_value = True  # the value-first branch: a weapon-like line buys DPS
    gear._buys_value = lambda base, slot: True
    gear._forced_lacking = lambda slot, raw: False
    gear._raw = lambda base, ilvl, affixes, bench, sockets: f"raw:{affixes[-1].mod_id}"
    gear._last_choice_rows = []
    return gear


def _open_pick(tie_seed: int | None, mods: list[WishlistMod], values: dict[str, float]) -> str:
    gear = _gear(values, tie_seed)
    picked = gear._choose_trial("Weapon 1", "Void Sceptre", 80, [], None, [(m, None) for m in mods], sockets=None)
    assert picked is not None
    return picked[0].mod_id


def _mods(count: int) -> list[WishlistMod]:
    return [WishlistMod(f"Mod{i}", "Prefix", f"Group{i}", 1, 1, f"line {i}", lines=(f"line {i}",)) for i in range(count)]


def test_the_open_line_breaks_an_exact_tie_by_seed_and_keeps_the_first_without_one() -> None:
    mods = _mods(12)
    values = {f"raw:Mod{i}": 150.0 for i in range(12)}
    assert _open_pick(None, mods, values) == "Mod0"
    picks = {s: _open_pick(derive_seed(s, PURPOSE_TEMPLATE_TIES), mods, values) for s in SEEDS}
    assert len(set(picks.values())) >= 2, picks
    for s in SEEDS:  # the listing order does not move the pick
        assert _open_pick(derive_seed(s, PURPOSE_TEMPLATE_TIES), list(reversed(mods)), values) == picks[s]


def test_the_open_line_never_overrules_a_number_pob_separated() -> None:
    mods = _mods(12)
    values = {f"raw:Mod{i}": 150.0 for i in range(12)} | {"raw:Mod7": 150.5}
    for s in SEEDS:
        assert _open_pick(derive_seed(s, PURPOSE_TEMPLATE_TIES), mods, values) == "Mod7"


def test_fill_slot_no_longer_drops_the_seed() -> None:
    gear = object.__new__(WishlistGear)
    gear.tie_seed = None
    gear.rails = Rails.load()
    gear.objective = _FakeObjective()
    gear.pob = SimpleNamespace(stats=lambda keys: {"v": 1.0}, equip=lambda items: None)
    for seed in (derive_seed(4, PURPOSE_TEMPLATE_TIES), derive_seed(5, PURPOSE_TEMPLATE_TIES)):
        try:
            gear.fill_slot("Boots", "Two-Toned Boots", seed=seed)
        except Exception:
            pass  # the fake stops past the point the seed is taken; only what the call stored matters
        assert gear.tie_seed == seed


def test_pick_attempt_seed_only_separates_an_exact_tie() -> None:
    """The seeded `tie` of `pick_attempt` (#619) replaces the base name only as the last key."""

    from types import SimpleNamespace

    from junkroan.optimizer.objective import Score
    from junkroan.optimizer.wishlist_gear import pick_attempt

    better = (Score(neg_violation=0.0, value=10.0), SimpleNamespace(base="A"))
    tied_1 = (Score(neg_violation=0.0, value=20.0), SimpleNamespace(base="B"))
    tied_2 = (Score(neg_violation=0.0, value=20.0), SimpleNamespace(base="C"))
    ranks = {"A": 99, "B": 1, "C": 2}
    for order in ("floors", "priced"):
        assert pick_attempt([better, tied_1, tied_2], order, tie=ranks.get)[1].base == "C"  # the value wins first, the tie only separates B / C
        assert pick_attempt([better, tied_2, tied_1], order, tie=ranks.get)[1].base == "C"
        assert pick_attempt([better, tied_1, tied_2], order, tie={"A": 0, "B": 5, "C": 2}.get)[1].base == "B"
        assert pick_attempt([better, tied_1, tied_2], order)[1].base == "C"  # no tie callable: the base name, as before
