"""#1158 unit 2: the loop's base swap runs on every gear slot with more than one base for the loadout (PoB-free).

Kind B (a loop fix) with a trace counter: `base-swap:<slot>` generated > 0 and evaluated > 0 on every swappable slot, the
loadout's excluded base (Prismatic Ring on day 1) never generated; the replay bench has a `base-swap` move.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import junkroan.optimizer.item_bases as item_bases_module  # noqa: E402
from junkroan.optimizer.improvement_loop import LoopPlan, base_swap_slots, pass_plan  # noqa: E402
from junkroan.optimizer.item_bases import bases_of_type  # noqa: E402
from junkroan.optimizer.loot_gear import LootGear, ordered_slots  # noqa: E402
from junkroan.optimizer.objective import Objective  # noqa: E402
from junkroan.optimizer.pipeline import BuildResult  # noqa: E402
from junkroan.optimizer.rails import Rails  # noqa: E402
from junkroan.optimizer.trace import TRACE, classify  # noqa: E402
from junkroan.optimizer.wishlist_gear import WishlistGear  # noqa: E402
from junkroan.pob.session import PobSession  # noqa: E402
from junkroan.search.generator import ARMOUR_SLOT_TYPES  # noqa: E402

from loop_fakes import loop_over  # noqa: E402

PRISMATIC = "Prismatic Ring"
SWAP_SLOTS = ["Weapon 1", "Weapon 2", "Helmet", "Body Armour", "Gloves", "Boots", "Ring 1", "Ring 2", "Amulet", "Belt"]
SLOT_TYPE = {**ARMOUR_SLOT_TYPES, "Weapon 1": "One Handed Sword", "Weapon 2": "Shield"}
PER_SLOT_COUNTED = ["Weapon 1", "Weapon 2", "Helmet", "Body Armour", "Gloves", "Boots", "Ring 1", "Amulet", "Belt"]


def _base(slot: str) -> str:
    return bases_of_type(SLOT_TYPE[slot], max_level=70)[0]


def _raw(base: str) -> str:
    return f"Rarity: RARE\nLoop Item\n{base}\nCrafted: true\nItem Level: 86\nQuality: 20\nSockets: R-R\nPrefix: {{range:0.500}}LifeMod\nImplicits: 0\n"


class _Loot(LootGear):
    """The loot filler's candidate rule over the day-1 rails; no PoB."""

    def __init__(self, rails: Rails, rare_bases: dict[str, str]) -> None:
        self.rails = rails
        self.current_raw = {slot: _raw(base) for slot, base in rare_bases.items()}
        self.uniques = {}


def _build(slots=SWAP_SLOTS):
    rails = Rails.load()  # day 1
    rare_bases = {slot: _base(slot) for slot in slots}
    skeleton = SimpleNamespace(rare_bases=dict(rare_bases), uniques={}, forced_bases={})
    return rails, skeleton, _Loot(rails, rare_bases)


def _raw_base(raw: str) -> str:
    return raw.splitlines()[2]


# -- the plan ------------------------------------------------------------------------------------------------


def test_pass_plan_lists_a_base_swap_step_for_every_gear_slot_with_more_than_one_base() -> None:
    _rails, skeleton, loot = _build()
    slots = ordered_slots(skeleton.rare_bases)

    swappable = base_swap_slots(slots, skeleton=skeleton, loot=loot, raw_base=_raw_base)
    plan = pass_plan(slots, swappable, has_flat_reservation_aura=False, local_only=True, moves=None)

    assert [slot for kind, _i, slot in plan if kind == "weapon-base"] == slots  # every slot, in the fill order
    assert set(slots) == set(SWAP_SLOTS)


def test_a_slot_with_a_single_base_gets_no_step(monkeypatch) -> None:
    _rails, skeleton, loot = _build()
    real = item_bases_module.bases_of_type
    monkeypatch.setattr(item_bases_module, "bases_of_type", lambda item_type, max_level: real(item_type, max_level=max_level)[:1] if item_type == "Belt" else real(item_type, max_level=max_level))
    slots = ordered_slots(skeleton.rare_bases)

    swappable = base_swap_slots(slots, skeleton=skeleton, loot=loot, raw_base=_raw_base)

    assert "Belt" not in swappable and "Helmet" in swappable


def test_a_unique_or_forced_base_slot_gets_no_step() -> None:
    _rails, skeleton, loot = _build()
    skeleton.forced_bases = {"Helmet": skeleton.rare_bases["Helmet"]}
    slots = [slot for slot in ordered_slots(skeleton.rare_bases) if slot != "Gloves"]  # a unique slot is not among `rare`

    swappable = base_swap_slots(slots, skeleton=skeleton, loot=loot, raw_base=_raw_base)

    assert "Helmet" not in swappable and "Gloves" not in swappable and "Body Armour" in swappable


def test_the_replay_plan_of_the_base_swap_move_is_the_weapon_base_move_alone() -> None:
    from replay_bench import LEGAL_MOVES, loop_move_of, validate_move

    assert "base-swap" in LEGAL_MOVES and validate_move("base-swap") == "base-swap"
    plan = LoopPlan.replay(loop_move_of("base-swap"), seed=1, passes=1)
    assert plan.moves == frozenset({"weapon-base"})
    assert loop_move_of("gear") == "gear"


# -- the loadout's rail --------------------------------------------------------------------------------------


def test_prismatic_ring_is_never_offered_to_a_ring_swap_on_day_1() -> None:
    rails, _skeleton, loot = _build()
    ring = _base("Ring 1")
    assert PRISMATIC not in loot.other_weapon_bases(ring) and len(loot.other_weapon_bases(ring)) > 1
    wishlist = object.__new__(WishlistGear)
    wishlist.rails = rails
    assert PRISMATIC not in wishlist.other_weapon_bases(ring) and len(wishlist.other_weapon_bases(ring)) > 1
    assert PRISMATIC in bases_of_type("Ring", max_level=70)  # the base exists: it is the rail that keeps it out


# -- the trace counter at the PoB boundary --------------------------------------------------------------------


class _Pob(PobSession):
    """A PobSession whose PoB boundary is a fake: `trial_stats` is the real method, so the trace is counted as in a run."""

    def __init__(self) -> None:  # no PoB: the session's own constructor is not called
        self.payloads: list[dict] = []
        self.equipped: dict[str, str] = {}
        self._adapter = SimpleNamespace(trial_stats=self._trial_stats)
        self._handle, self.fulldps_shortcut, self.mean_parts = object(), False, ()

    def _trial_stats(self, _handle, payload):
        self.payloads.append(payload)
        return [{"ok": True, "stats": {"CombinedDPS": 100.0}} for _ in payload["trials"]]

    def craft_rare(self, base, **_kwargs):
        return {"raw": _raw(base), "problems": [], "unsupported_lines": []}

    def equip(self, items) -> None:
        self.equipped.update({k: v for k, v in items.items() if v is not None})

    def tree_light(self) -> dict:
        return {"user_allocated_node_ids": [1], "mastery_effect_ids": []}

    def config_inputs(self) -> dict:
        return {}

    def stats(self, keys):
        return {key: 100.0 for key in keys}


@pytest.fixture(autouse=True)
def _fresh_trace():
    TRACE.reset()
    yield
    TRACE.reset()


def _try_swap(slot: str) -> tuple[_Pob, dict]:
    rails, skeleton, loot = _build()
    pob = _Pob()
    objective = Objective(maximize="CombinedDPS")
    rig = loop_over(pob, tree=None, gear=loot, skeleton=skeleton, objective=objective, rails=rails)
    result = BuildResult(skeleton=skeleton)
    rig.weapon_base_move(
        result, skeleton, loot, slot, current_score=objective.score({"CombinedDPS": 100.0}), min_gain=0.005,
        move_state={"xml": "before", "judging": None, "lanes_fresh": True}, snapshot_fresh=True, t0=0.0,
        judge=lambda *_a, **_k: False, restore_move=lambda *_a, **_k: None, last_rejected={},
    )
    seen: dict[str, dict[str, int]] = {}
    for classes in TRACE.considered().values():
        for name, counts in classes.items():
            cell = seen.setdefault(name, {"generated": 0, "evaluated": 0})
            cell["generated"] += counts["generated"]
            cell["evaluated"] += counts["evaluated"]
    return pob, seen


@pytest.mark.parametrize("slot", PER_SLOT_COUNTED)
def test_base_swap_is_generated_and_evaluated_on_every_slot(slot: str) -> None:
    pob, seen = _try_swap(slot)

    cell = seen[f"base-swap:{slot}"]
    assert cell["generated"] > 0 and cell["evaluated"] > 0
    assert seen["base-swap"]["generated"] == cell["generated"] and seen["base-swap"]["evaluated"] == cell["evaluated"]
    assert cell["generated"] == cell["evaluated"] == sum(len(p["trials"]) for p in pob.payloads)
    assert not any("base_swap" in t for p in pob.payloads for t in p["trials"])  # trace-only: never in the PoB payload


def test_the_ring_swap_evaluates_other_rings_and_never_prismatic() -> None:
    _pob, seen = _try_swap("Ring 1")

    assert seen["base-swap:Ring 1"]["evaluated"] > 1
    assert seen.get("base-excluded-by-loadout", {"generated": 0, "evaluated": 0}) == {"generated": 0, "evaluated": 0}
    assert f"base:{PRISMATIC}" not in seen and "base-swap" in seen


def test_a_trial_that_is_not_a_base_swap_carries_no_such_class() -> None:
    trial = {"item": {"slot": "Helmet", "raw": _raw(_base("Helmet"))}}
    assert not {c for c in classify(trial) if c.startswith("base-swap")}
