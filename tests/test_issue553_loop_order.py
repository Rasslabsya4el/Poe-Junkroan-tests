"""#553 / D116 unit 3: the improvement loop orders its moves by the priced score; construction keeps the
violation-first order. PoB-free: the Scores of the issue's impale_ballista row, a fake PoB for the fills."""

from types import SimpleNamespace

from junkroan.optimizer.improvement_loop import LoopPlan, accepts
from junkroan.optimizer.loot_gear import LootGear, _rank
from junkroan.optimizer.objective import Objective, Score, accepts_under, better_loop_score, better_score, score_key
from junkroan.optimizer.pipeline import tune_flat_reservation_aura_levels
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.useful_lines import item_lines
from junkroan.optimizer.wishlist_gear import pick_attempt

from loop_fakes import _Loot, _Pob, _Tree, _skeleton, loop_over

V = 1_000_000.0


# -- the loop's acceptance ---------------------------------------------------------------------------------


def test_accepts_refuses_the_impale_ballista_cluster_move_and_keeps_the_feasible_one() -> None:
    cur = Score(-0.0195, V)
    assert accepts(Score(-0.0024, 0.2547 * V), cur, min_gain=0.0) is False  # -74.5 % DPS for a crumb of floor
    assert better_score(Score(-0.0024, 0.2547 * V), cur) is True  # the order construction keeps
    assert accepts(Score(0.0, 0.99 * V), cur, min_gain=0.0) is True


def test_the_order_selectors_are_the_two_rules() -> None:
    new, cur = Score(-0.0024, 0.2547 * V), Score(-0.0195, V)
    assert accepts_under("floors") is better_score and accepts_under("priced") is better_loop_score
    assert accepts_under()(new, cur) is True and accepts_under("priced")(new, cur) is False
    low, high = Score(0.0, 100.0), Score(-0.05, 1000.0)
    assert score_key("floors")(high) < score_key("floors")(low)  # a feasible score beats a violating one
    assert score_key("priced")(high) > score_key("priced")(low)


# -- the candidate choice of the gear fill ------------------------------------------------------------------


def _attempt(base: str, score: Score):
    return score, SimpleNamespace(base=base)


def test_wishlist_attempts_pick_by_violation_first_by_default_and_by_price_in_the_loop() -> None:
    near, high = Score(0.0, 100.0), Score(-0.05, 1000.0)  # a feasible low-value item, a slightly infeasible high-value one
    attempts = [_attempt("A", near), _attempt("B", high)]
    assert pick_attempt(attempts)[1].base == "A"
    assert pick_attempt(attempts, "floors")[1].base == "A"
    assert pick_attempt(attempts, "priced")[1].base == "B"
    assert pick_attempt(list(reversed(attempts)), "priced")[1].base == "B"


def test_wishlist_attempts_tie_break_on_the_base_name_last_in_both_orders() -> None:
    same = Score(-0.1, 500.0)
    attempts = [_attempt("Amber", same), _attempt("Zircon", same)]
    assert pick_attempt(attempts, "floors")[1].base == "Zircon"
    assert pick_attempt(attempts, "priced")[1].base == "Zircon"


def test_loot_rank_priced_ignores_what_the_slot_wore_and_the_default_does_not() -> None:
    current = Score(0.0, 1000.0)
    near, high = Score(0.0, 1100.0), Score(-0.05, 2000.0)
    assert _rank(current, near) > _rank(current, high)
    assert _rank(current, near, order="priced") < _rank(current, high, order="priced")
    dead = Score(-0.1, float("-inf"))
    assert _rank(current, dead, order="priced") < _rank(current, near, order="priced")  # nan-safe, a dead item ranks last


class _FakePob:
    """A ring slot: an item's line is (DPS, Life); the build is 1000 DPS and 1000 Life plus the worn item."""

    LINES = {"Near": (100.0, 0.0), "High": (1000.0, -50.0)}

    def __init__(self, rolled: list[dict]) -> None:
        self.rolled, self.worn = rolled, {}

    def _sum(self, raw: str | None) -> tuple[float, float]:
        parts = [self.LINES[ln.text] for ln in item_lines(raw)] if raw else []
        return sum(p[0] for p in parts), sum(p[1] for p in parts)

    def _stats(self, raws, keys) -> dict:
        raws = list(raws)
        dps, life = 1000.0 + sum(self._sum(r)[0] for r in raws), 1000.0 + sum(self._sum(r)[1] for r in raws)
        return {k: {"CombinedDPS": dps, "Life": life}.get(k, 0.0) for k in keys}

    def stats(self, keys):
        return self._stats(self.worn.values(), keys)

    def random_rares(self, base, n=None, ilvl=None, quality=None, sockets=None, seed=None, **_kw):
        return list(self.rolled)

    def trial_stats(self, trials, keys, mode="fast"):
        return [{"ok": True, "stats": self._stats([r for s, r in self.worn.items() if s != t["item"]["slot"]] + [t["item"]["raw"]], keys)} for t in trials]

    def equip(self, items):
        self.worn.update(items)

    def list_bench_mods(self, base, ilvl=None):
        return {"mods": []}

    def list_item_mods(self, base, **_kw):
        return {"mods": []}


def _ring(name: str) -> dict:
    return {"raw": f"Rarity: RARE\n{name}\nIron Ring\nItem Level: 84\nPrefix: {{range:0.500}}{name}\nImplicits: 0", "mod_ids": [name]}


def _fill(order: str | None) -> str:
    near, high = _ring("Near"), _ring("High")
    pob = _FakePob([near, high])
    loot = LootGear(pob, Objective(maximize="CombinedDPS", floors={"Life": 1000.0}), Rails.load())
    res = loot.fill_slot("Ring 1", "Iron Ring", n=2, bench=False, **({} if order is None else {"order": order}))
    return "Near" if res.raw == near["raw"] else "High"


def test_loot_fill_picks_the_feasible_item_by_default_and_the_priced_best_in_the_loop() -> None:
    # Near: 1100 DPS, feasible. High: 2000 DPS at Life 950 against a floor of 1000 (violation 0.05) prices at 1900.
    assert _fill(None) == "Near"
    assert _fill("floors") == "Near"
    assert _fill("priced") == "High"


# -- the loop passes the priced order to every move it calls ------------------------------------------------


def test_the_loop_hands_the_priced_order_to_the_gear_fill_the_kick_joint_and_the_picks(monkeypatch) -> None:
    pob = _Pob(1000.0)
    tree = _Tree(pob, [])
    fills: list[str] = []
    picks: list[str] = []

    class _RecordingLoot(_Loot):
        def fill_slot(self, slot, base, *, order="floors", **kwargs):
            fills.append(order)
            return super().fill_slot(slot, base, **kwargs)

    class _Gen:
        def __init__(self, pob, rails, *, objective=None, log=None, castability_context=None, castability_metrics=None) -> None:
            self.pob, self.picks = pob, ()

        def rejudge_picks(self, skeleton, *, reconfigure=None, min_gain=0.005, max_sweeps=3, order="floors"):
            picks.append(order)
            return []

    monkeypatch.setattr("junkroan.search.generator.SkeletonGenerator", _Gen)
    loot = _RecordingLoot(pob, {})
    sk = _skeleton({"Boots": "Two-Toned Boots", "Helmet": "Iron Hat"}, main_link=("Fireball", "Controlled Destruction"))
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk)
    p.started()

    p.run(LoopPlan(seed=1, max_passes=3, max_seconds=600.0, min_gain=0.005, loot_n=5))

    assert fills and set(fills) == {"priced"}  # the gear move of the passes and the kick joint's refills
    assert picks and set(picks) == {"priced"}


class _Aura:
    def __init__(self) -> None:
        self.aura_levels: dict = {}

    def flat_reservation_auras(self):
        return ["Precision"]

    def apply_skills(self, pob, **_kw):
        pob.level = self.aura_levels.get("Precision", 3)


class _AuraPob:
    level = 3

    def stats(self, keys):
        # level 1: feasible, tiny DPS; level 2: 5 % short of the floor, a thousand times the DPS; level 3: far short
        dps, life = {1: (10.0, 1000.0), 2: (10_000.0, 950.0)}.get(self.level, (1.0, 0.0))
        return {k: {"CombinedDPS": dps, "Life": life}.get(k, 0.0) for k in keys}


def test_the_aura_level_choice_keeps_violation_first_by_default() -> None:
    rails = SimpleNamespace(gems=SimpleNamespace(level=3, quality=0, main_quality=0))
    objective = Objective(maximize="CombinedDPS", floors={"Life": 1000.0})
    for order, level in (("floors", 1), ("priced", 2)):
        assert tune_flat_reservation_aura_levels(_AuraPob(), objective, rails, _Aura(), order=order) == {"Precision": level}
    assert tune_flat_reservation_aura_levels(_AuraPob(), objective, rails, _Aura()) == {"Precision": 1}
