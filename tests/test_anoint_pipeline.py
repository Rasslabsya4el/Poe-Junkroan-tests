"""#432 unit 5: the anoint step and the end re-pick in the pipeline, and `scripts/check_anoints.py`.

Fake PoB: the build is one number, 1000 plus the bonus of the worn amulet's anoint while its node is not on the tree.
The fake models the PoB pitfall of unit 2 (a plain amulet equipped over an anointed one inherits the anoint), for a
full equip and, as the worst case, for a fast trial, so a pipeline that forgets to empty the slot first fails here.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from judging_fakes import _Lanes, _Reads

from junkroan.optimizer import pipeline as pipeline_module
from junkroan.optimizer.anoint_candidates import OIL_ORDER, Candidate
from junkroan.optimizer.anoint_line import anoint_of, apply_anoint, cannot_be_anointed_bases
from junkroan.optimizer.improvement_loop import ImprovementLoop, LoopOutcome
from junkroan.optimizer.judging import Judging
from junkroan.optimizer.loot_gear import LootGear
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.pipeline import BuildPipeline, BuildResult
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.wishlist_gear import WishlistGear

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_anoints  # noqa: E402

AMULET_BASE = "Amber Amulet"
TALISMAN = sorted(cannot_be_anointed_bases())[0]
A, B, C = "Heart of Oak", "Whispers of Doom", "Combat Stamina"
NODES = {A: 101, B: 102, C: 103}
BONUS = {A: 500.0, B: 300.0, C: -50.0}  # C is worse than no anoint
CANDIDATES = [Candidate(name, node, ("Clear", "Clear", "Clear"), "Clear") for name, node in NODES.items()]


def _raw(base: str = AMULET_BASE, tag: str = "x") -> str:
    return f"Rarity: RARE\nRoll {tag}\n{base}\nCrafted: true\nItem Level: 84\nPrefix: {{range:0.5}}IncreasedLife2\nImplicits: 1\n+(20-30) to Strength"


class _Pob:
    def __init__(self, amulet: str | None = None, tree: set[int] | None = None) -> None:
        self.worn = amulet
        self.tree = set(tree or ())
        self.events: list[tuple] = []
        self.fulldps_shortcut = False
        self.mean_parts = None
        self.nodes: set[int] = set()

    # the value of an amulet raw on this tree
    def _value(self, raw: str | None) -> float:
        notable = anoint_of(raw) if raw else None
        gain = BONUS.get(notable, 0.0) if notable and NODES.get(notable) not in self.tree else 0.0
        return 1000.0 + gain

    def _inherit(self, raw: str) -> str:
        worn = anoint_of(self.worn) if self.worn else None
        return apply_anoint(raw, worn) if worn and anoint_of(raw) is None else raw

    def equip(self, items: dict) -> None:
        for slot, raw in items.items():
            self.events.append(("equip", slot, None if raw is None else anoint_of(raw)))
            if slot == "Amulet":
                self.worn = None if raw is None else self._inherit(raw)

    def stats(self, keys):
        return {k: 0.0 for k in keys} | {"CombinedDPS": self._value(self.worn)}

    def trial_stats(self, trials, keys, mode="fast"):
        self.events.append(("trial", len(trials)))
        return [{"ok": True, "stats": {k: 0.0 for k in keys} | {"CombinedDPS": self._value(self._inherit(t["item"]["raw"]))}} for t in trials]

    def random_rares(self, base, n=None, ilvl=None, quality=None, sockets=None, seed=None):
        return [{"raw": _raw(base, f"r{i}"), "mod_ids": []} for i in range(3)]

    def tree_light(self) -> dict:
        return {"user_allocated_node_ids": sorted(self.tree), "mastery_effect_ids": []}

    def calc(self, lane: str) -> dict:
        return {"CombinedDPS": self._value(self.worn)}

    # what construction touches
    def set_tree(self, *, class_id, ascendancy_id, ascendancy_nodes) -> None:
        self.nodes = set(ascendancy_nodes)

    def add_nodes(self, nodes) -> None:
        self.nodes.update(nodes)

    def mutate_nodes(self, **_kwargs) -> dict:
        return {"points_used": len(self.nodes)}

    @staticmethod
    def read_state() -> dict:
        return {"skills_state": {"socket_groups": []}}

    def export_xml(self) -> str:
        return "<Build/>"


class _Skeleton:
    class_name, ascendancy, ascendancy_nodes, keystones, level, mode = "Witch", "Elementalist", [1], [9], 10, "hit"
    main_link, main_part, gem_counts = ["Fireball", "Controlled Destruction"], "Fireball", {}
    uniques: dict[str, str] = {}
    sockets: dict[str, str] = {}
    pure_es, forbid_keystones, scaling, extra_groups, utility_groups = False, [], None, [], 0

    def __init__(self, amulet_base: str = AMULET_BASE) -> None:
        self.rare_bases = {"Weapon 1": "Driftwood Wand", "Amulet": amulet_base}

    def apply(self, pob, **_kwargs) -> None:
        pass

    def refresh_minion_counts(self, _pob, **_kwargs) -> dict:
        return {}

    def tune_minion_skills(self, _pob, _score, **_kwargs) -> dict:
        return {}

    @staticmethod
    def flat_reservation_auras() -> list[str]:
        return []


class _Tree:
    def __init__(self, pob, objective, **_kwargs) -> None:
        self.pob, self.objective, self.history, self.graph = pob, objective, [], SimpleNamespace()

    def forbid(self, _n) -> None: ...

    def forbid_text(self, _t) -> None: ...

    def allocate(self, points: int):
        return SimpleNamespace(stopped_reason="budget", points_spent=points)

    def refine(self, **_kwargs):
        return SimpleNamespace(steps=[])

    def current_score(self):
        return None, None


class _Loot:
    """The filler: its first fill wears a plain amulet and remembers it, as a real fill does."""

    instances: list = []

    def __init__(self, pob, objective, _rails, **_kwargs) -> None:
        self.pob, self.objective, self.rails = pob, objective, _rails
        self.current_raw: dict[str, str] = {}
        self.uniques: dict[str, str] = {}
        self.anoint: str | None = None
        self._results_by_raw: dict = {}
        type(self).instances.append(self)

    def carry_result(self, slot, old_raw, new_raw, **fields) -> None:  # WishlistGear's own: the pipeline asks the gear, not its class
        prior = self._results_by_raw.get((slot, old_raw))
        if prior is not None:
            moved = copy.deepcopy(prior)
            moved.raw = new_raw
            self._results_by_raw[(slot, new_raw)] = moved

    def resistance_plan_snapshot(self) -> dict:
        return {}

    def restore_resistance_plan(self, saved) -> None:
        pass

    def shopping_results(self) -> list:
        return []

    def item_level_for(self, slot: str) -> int:
        return self.rails.gear.item_level

    def fill(self, bases, *, passes=1, n=None, seed=1, **_kwargs) -> None:
        if "Amulet" in bases and "Amulet" not in self.current_raw:
            self.current_raw["Amulet"] = _raw(bases["Amulet"], "first")
            self.pob.equip({"Amulet": self.current_raw["Amulet"]})


class _Wish(_Loot):
    pass


class _Rec:
    """Records, in order, what the pipeline stub points were asked to do."""

    def __init__(self) -> None:
        self.order: list[str] = []


def _run(monkeypatch: pytest.MonkeyPatch, *, screen: bool = False, gear_mode: str = "loot", amulet_base: str = AMULET_BASE,
         tree_added_by_loop: int | None = None):
    _Loot.instances = []
    rec = _Rec()
    monkeypatch.setattr(pipeline_module, "TreeOptimizer", _Tree)
    monkeypatch.setattr(pipeline_module, "LootGear", _Loot)
    monkeypatch.setattr(pipeline_module, "WishlistGear", _Wish)
    monkeypatch.setattr(pipeline_module, "anoint_candidates", lambda oil: [c for c in CANDIDATES if OIL_ORDER.index(c.highest_oil) <= OIL_ORDER.index(oil)])
    monkeypatch.setattr(pipeline_module, "objective_for", lambda _r, _s, objective, **_k: objective)
    monkeypatch.setattr(pipeline_module, "self_cost_tree_patterns", lambda *_a, **_k: ())
    monkeypatch.setattr("junkroan.search.hypothesis.active_gems", lambda: {})
    rails = SimpleNamespace(gems=SimpleNamespace(level=18, quality=0, main_quality=0, main_link_max=5, other_link_max=4), gear=SimpleNamespace(construction_best_of_n=600, loot_best_of_n=200, item_level=84, quality=0, jewels=SimpleNamespace(count_max=0, lines=1), clusters=SimpleNamespace(count_max=0)),
                            forbidden_node_text=(), utility_max_groups=0, attribute_plus30_nodes_max=1, anoint=SimpleNamespace(oil_max="Black"),
                            ascendancy_points=None)  # #1157: no ascendancy-swap in these plans (as loop_fakes.py)
    pob = _Pob()
    pipeline = BuildPipeline(pob, rails, objective=Objective(maximize="CombinedDPS"))
    pipeline._rails_identity = lambda _s: None
    calls: list = []
    pipeline.judging = Judging(_Lanes(calls), _Reads(calls), objective=pipeline.judging.objective, log=pipeline.log)
    pipeline.judging.main_tags = frozenset()
    pipeline.judging.main_gem_levels = ()
    pipeline.judging.post_holders = lambda *_a, **_k: None
    pipeline.judging.refresh_castability = lambda *_a, **_k: None
    pipeline.judging.rejudge = lambda *_a, **_k: rec.order.append("reconfigure") or pipeline.judging.objective
    pipeline._points_used = lambda: 0
    pipeline._take_picks = lambda *_a, **_k: None

    def rebuild(_s, _t, _p) -> str:
        rec.order.append("rebuild")
        return "rebuilt"

    class _Gen:
        def pick_supports(self, skeleton, **_kwargs) -> None:
            rec.order.append("supports")

    def loop(*_a, **_k) -> LoopOutcome:
        rec.order.append("loop")
        if tree_added_by_loop is not None:
            pob.tree.add(tree_added_by_loop)
        return LoopOutcome(note="", stopped="", kept=(), counts={}, passes=0)

    def finish(result, _s, _t, **_k):
        rec.order.append("finish")
        return result

    pipeline._rebuild_tree, pipeline._generator, pipeline._finish = rebuild, lambda: _Gen(), finish
    monkeypatch.setattr(ImprovementLoop, "run", lambda _self, *_a, **_k: loop())  # `run` reaches the loop through `ImprovementLoop`
    result = pipeline.run(_Skeleton(amulet_base), tree_points=10, screen=screen, repick_supports=True, pick_utilities=False, gear_mode=gear_mode, fixed_point_check=False)
    return result, pob, _Loot.instances[0], rec, pipeline


def _stages(result: BuildResult) -> list[str]:
    return [s.name for s in result.stages]


@pytest.mark.parametrize("gear_mode", ["loot", "wishlist"])
def test_the_step_runs_after_the_tree_rebuild_and_before_the_supports_repick(monkeypatch, gear_mode) -> None:
    result, pob, loot, rec, _p = _run(monkeypatch, gear_mode=gear_mode)

    names = _stages(result)
    assert names.index("tree rebuilt on gear") + 1 == names.index("anoint") and names.index("anoint") + 1 == names.index("supports re-picked")
    assert rec.order.index("rebuild") < rec.order.index("supports")
    note = next(s.notes for s in result.stages if s.name == "anoint")
    assert note.startswith(f"anoint: {A}, score 1,000 -> 1,500, 3 measured, ")
    # the pick is on the worn amulet, the filler's book and the generator, once
    assert anoint_of(pob.worn) == A and pob.worn.count("Allocates") == 1
    assert anoint_of(loot.current_raw["Amulet"]) == A and loot.anoint == A
    assert isinstance(loot, _Wish) == (gear_mode == "wishlist")
    # the build's number is the anointed one, recorded on the stage
    assert next(s.score_value for s in result.stages if s.name == "anoint") == 1500.0


def test_a_notable_the_tree_holds_is_not_a_candidate(monkeypatch) -> None:
    class _TreeWithA(_Pob):
        def __init__(self) -> None:
            super().__init__(tree={NODES[A]})

    monkeypatch.setattr(sys.modules[__name__], "_Pob", _TreeWithA)
    result, pob, loot, _rec, _p = _run(monkeypatch)

    assert anoint_of(pob.worn) == B and loot.anoint == B
    assert next(s.notes for s in result.stages if s.name == "anoint").startswith(f"anoint: {B}, score 1,000 -> 1,300, 2 measured, ")


def test_the_screen_skips_the_step_and_the_repick(monkeypatch) -> None:
    result, pob, loot, rec, _p = _run(monkeypatch, screen=True)

    assert "anoint" not in _stages(result) and "anoint re-pick" not in _stages(result)
    assert loot.anoint is None and anoint_of(pob.worn) is None
    assert all(not (e[0] == "equip" and e[1] == "Amulet" and e[2]) for e in pob.events)


def test_an_amulet_that_cannot_be_anointed_skips_the_step(monkeypatch) -> None:
    lines: list[str] = []
    real_init = BuildPipeline.__init__

    def init(self, *a, **k) -> None:
        real_init(self, *a, **k)
        self.log = lines.append

    monkeypatch.setattr(BuildPipeline, "__init__", init)
    result, pob, loot, rec, _p = _run(monkeypatch, amulet_base=TALISMAN)

    assert "anoint" not in _stages(result) and "anoint re-pick" not in _stages(result)
    assert loot.anoint is None and anoint_of(pob.worn) is None
    assert any(line.startswith("anoint: skipped") and TALISMAN in line for line in lines)


def test_the_end_repick_drops_an_anoint_whose_notable_the_tree_took(monkeypatch) -> None:
    result, pob, loot, rec, _p = _run(monkeypatch, tree_added_by_loop=NODES[A])

    names = _stages(result)
    assert names.index("anoint re-pick") > names.index("anoint") and rec.order.index("loop") < rec.order.index("finish")
    assert rec.order[-1] == "finish" and names[-1] == "anoint re-pick"
    note = next(s.notes for s in result.stages if s.name == "anoint re-pick")
    assert note.startswith(f"anoint re-pick: {A} -> {B}, score 1,000 -> 1,300, "), note  # the tree holds A: worth nothing twice
    assert anoint_of(pob.worn) == B and pob.worn.count("Allocates") == 1
    assert anoint_of(loot.current_raw["Amulet"]) == B and loot.anoint == B
    assert result.moves[-1]["move"] == "anoint re-pick" and result.moves[-1]["after"] - result.moves[-1]["before"] == 300.0


def test_the_end_repick_keeps_a_still_best_anoint(monkeypatch) -> None:
    result, pob, loot, _rec, _p = _run(monkeypatch)

    note = next(s.notes for s in result.stages if s.name == "anoint re-pick")
    assert note.startswith(f"anoint re-pick: kept {A}, score 1,500 -> 1,500, "), note
    assert anoint_of(pob.worn) == A and loot.anoint == A and not result.moves


def _rails_for_gear() -> SimpleNamespace:
    from dataclasses import replace

    return SimpleNamespace(gear=replace(Rails.load().gear, loot_best_of_n=3, item_level=84, quality=0), anoint=SimpleNamespace(oil_max="Black"))


def test_a_later_one_slot_amulet_reroll_carries_the_anoint() -> None:
    pob = _Pob()
    loot = LootGear(pob, Objective(maximize="CombinedDPS"), Rails.load(), log=lambda _m: None)
    loot.rails = _rails_for_gear()
    loot.current_raw["Amulet"] = _raw(tag="first")
    pob.equip({"Amulet": loot.current_raw["Amulet"]})
    loot.anoint = A
    pob.equip({"Amulet": None})  # the loop empties the slot, then re-rolls it
    res = loot.fill_slot("Amulet", AMULET_BASE, n=3, bench=False)

    assert anoint_of(res.raw) == A and res.raw.count("Allocates") == 1
    assert anoint_of(pob.worn) == A and anoint_of(loot.current_raw["Amulet"]) == A


def test_the_wishlist_book_follows_the_anointed_raw() -> None:
    wish = WishlistGear.__new__(WishlistGear)
    wish.current_raw, wish.uniques, wish.anoint = {"Amulet": _raw()}, {}, None
    prior = SimpleNamespace(raw=wish.current_raw["Amulet"], slot="Amulet")
    wish._results_by_raw = {("Amulet", prior.raw): prior}
    pob = _Pob(amulet=prior.raw)
    p = BuildPipeline.__new__(BuildPipeline)
    p.pob, p.judging = pob, SimpleNamespace(rejudge=lambda _s: None)

    assert p._set_amulet_anoint(SimpleNamespace(), wish, B)
    new_raw = wish.current_raw["Amulet"]
    assert anoint_of(new_raw) == B and wish.anoint == B
    assert wish._results_by_raw[("Amulet", new_raw)].raw == new_raw and ("Amulet", prior.raw) in wish._results_by_raw


def test_a_skeletons_unique_amulet_is_anointed_too(monkeypatch) -> None:
    pob = _Pob(amulet=_raw(tag="unique"))
    loot = SimpleNamespace(current_raw={}, uniques={"Amulet": _raw(tag="unique")}, anoint=None, carry_result=lambda *a, **k: None)
    p = BuildPipeline.__new__(BuildPipeline)
    p.pob, p.judging = pob, SimpleNamespace(rejudge=lambda _s: None)

    assert p._set_amulet_anoint(SimpleNamespace(), loot, A)
    assert anoint_of(loot.uniques["Amulet"]) == A and anoint_of(pob.worn) == A and loot.anoint == A
    assert p._set_amulet_anoint(SimpleNamespace(), loot, None)  # and the line goes by emptying the slot, not by equipping plain text
    assert anoint_of(pob.worn) is None and "Allocates" not in loot.uniques["Amulet"]


# ---- scripts/check_anoints.py ------------------------------------------------------------------------------


def _xml(amulet_lines: str, nodes: str = "1,2,3", base: str = AMULET_BASE) -> str:
    return (
        '<PathOfBuilding><Build/><Tree activeSpec="1"><Spec treeVersion="3_29" nodes="' + nodes + '"/></Tree>'
        '<Items activeItemSet="1">'
        f'<Item id="1">Rarity: RARE\nRoll\n{base}\nImplicits: {amulet_lines.count(chr(10)) + 1 if amulet_lines else 0}\n{amulet_lines}\n+10 to Life</Item>'
        '<ItemSet id="1"><Slot name="Amulet" itemId="1"/></ItemSet></Items></PathOfBuilding>'
    )


DAY1 = {A: 101, B: 102}


def test_check_anoints_passes_one_allocates_line_in_the_day1_set_off_the_tree() -> None:
    xml = _xml(f"{{enchant}}Allocates {A}")
    row = check_anoints.check_xml(xml, DAY1)

    assert row.ok and row.notable == A and not row.problems


def test_check_anoints_fails_a_notable_that_is_on_the_tree() -> None:
    row = check_anoints.check_xml(_xml(f"{{enchant}}Allocates {A}", nodes="1,101,3"), DAY1)

    assert not row.ok and any("also allocated on the tree" in p for p in row.problems)


def test_check_anoints_fails_no_line_two_lines_and_a_notable_outside_the_day1_set() -> None:
    assert not check_anoints.check_xml(_xml(""), DAY1).ok
    two = check_anoints.check_xml(_xml(f"{{enchant}}Allocates {A}\n{{enchant}}Allocates {B}"), DAY1)
    assert not two.ok and any("2 Allocates lines" in p for p in two.problems)
    outside = check_anoints.check_xml(_xml("{enchant}Allocates Not A Day1 Notable"), DAY1)
    assert not outside.ok and any("day1 set" in p for p in outside.problems)


def test_check_anoints_excepts_and_names_an_amulet_that_cannot_be_anointed() -> None:
    row = check_anoints.check_xml(_xml("", base=TALISMAN), DAY1)

    assert row.ok and row.excepted and TALISMAN in row.line()


def test_check_anoints_main_exits_1_on_a_violation(tmp_path, capsys) -> None:
    good, bad = tmp_path / "good.xml", tmp_path / "bad.xml"
    good.write_text(_xml(f"{{enchant}}Allocates {A}"), encoding="utf-8")
    bad.write_text(_xml(f"{{enchant}}Allocates {A}", nodes="101"), encoding="utf-8")

    assert check_anoints.main([str(good)], day1=DAY1) == 0
    assert check_anoints.main([str(good), str(bad)], day1=DAY1) == 1
    out = capsys.readouterr().out
    assert "good.xml" in out and "bad.xml" in out and "1 of 2" in out
