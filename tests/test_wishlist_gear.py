"""D79 template gear rules without the PoB runtime."""

from __future__ import annotations

from dataclasses import replace

import pytest

from junkroan.optimizer.objective import Objective, Score
from junkroan.optimizer.rails import Rails, _wishlist_rails
from junkroan.optimizer.wishlist_gear import (
    BaseChoice,
    BasePayment,
    WishlistGear,
    WishlistMod,
    WishlistSlotResult,
    _is_elemental_resistance_group,
    is_pure_es,
    solve_resistances,
    template_for,
)
import junkroan.optimizer.wishlist_gear as wishlist_module


def _mod(group: str, affix_type: str, *, mod_id: str | None = None, level: int = 70, weight: int = 100,
         line: str | None = None, tags: tuple[str, ...] = ()) -> dict:
    return {
        "mod_id": mod_id or group,
        "type": affix_type,
        "group": group,
        "level": level,
        "weight": weight,
        "lines": [line or group],
        "mod_tags": list(tags),
    }


def _tiers(group: str, affix_type: str, count: int, *, weight: int = 100, tags: tuple[str, ...] = (),
           line: str | None = None) -> list[dict]:
    return [_mod(group, affix_type, mod_id=f"{group}{rank}", level=(count - rank + 1) * 8, weight=weight,
                 line=line or f"{group} T{rank}", tags=tags) for rank in range(1, count + 1)]


class FakePob:
    """A mod table plus PoB-like batched item trials, enough to test the filler policy."""

    def __init__(self, mods: list[dict], *, worth: dict[str, float] | None = None, bench: list[dict] | None = None,
                 baseline: dict[str, float] | None = None, stats_by_token: dict[str, dict[str, float]] | None = None) -> None:
        self.mods = mods
        self.worth = worth or {}
        self.bench = bench or []
        self.baseline = baseline or {}
        self.stats_by_token = stats_by_token or {}
        self.items: dict[str, str] = {}

    def list_item_mods(self, base: str, *, ilvl: int | None = None, pool: str = "explicit") -> dict:
        return {"mods": [mod for mod in self.mods if mod["level"] <= (ilvl or 100)]}

    def list_bench_mods(self, base: str, *, ilvl: int | None = None) -> dict:
        return {"mods": self.bench}

    def craft_rare(self, base: str, *, prefixes=(), suffixes=(), ilvl=None, quality=None, sockets=None) -> dict:
        ids = [str(row["mod_id"]) for row in prefixes] + [str(row["mod_id"]) for row in suffixes]
        return {"raw": "|".join([base, *ids]), "problems": [], "unsupported_lines": []}

    def _stats(self, items: dict[str, str], keys) -> dict[str, float]:
        tokens = [token for raw in items.values() for token in raw.replace("\n", "|").split("|")]
        stats = {key: 0.0 for key in keys} | self.baseline
        for token in tokens:
            for key, value in self.stats_by_token.get(token, {}).items():
                stats[key] = stats.get(key, 0.0) + value
        stats["CombinedDPS"] = 1_000.0 + sum(self.worth.get(token, 0.0) for token in tokens)
        return stats

    def stats(self, keys):
        return self._stats(self.items, keys)

    def trial_stats(self, trials, keys, mode="fast"):
        return [{"ok": True, "stats": self._stats(self.items | {trial["item"]["slot"]: trial["item"]["raw"]}, keys)} for trial in trials]

    def equip(self, updates):
        for slot, raw in updates.items():
            if raw:
                self.items[slot] = raw
            else:
                self.items.pop(slot, None)


def _rails(**changes) -> Rails:
    """Today's fixed template: the template v4 move switches are off here unless a test asks for them
    (tests/test_wishlist_gear_flexible.py), because every number below pins the template as constructed."""

    rails = Rails.load()
    changes = {"flexible_lines": False, "boots_movement_floor": False, **changes}
    return replace(rails, gear=replace(rails.gear, wishlist=replace(rails.gear.wishlist, **changes)))


def _normal_armour_mods() -> list[dict]:
    return [
        *_tiers("IncreasedLife", "Prefix", 8),
        *_tiers("FireResistance", "Suffix", 8, line="+(20-24)% to Fire Resistance"),
        *_tiers("ColdResistance", "Suffix", 8, line="+(20-24)% to Cold Resistance"),
        *_tiers("LightningResistance", "Suffix", 8, line="+(20-24)% to Lightning Resistance"),
        *_tiers("MovementVelocity", "Suffix", 8, line="+(20-24)% increased Movement Speed"),
        *_tiers("OpenDamage", "Prefix", 8),
    ]


def test_templates_fix_the_same_three_line_shape_on_two_builds() -> None:
    mods = _normal_armour_mods()
    results = []
    for worth in ({"IncreasedLife2": 1.0}, {"OpenDamage4": 9_000.0}):
        pob = FakePob(mods, worth=worth)
        gear = WishlistGear(pob, Objective(maximize="CombinedDPS"), _rails())
        gear._resistance_assignments["Helmet"] = "cold"
        results.append(gear.fill_slot("Helmet", "Fake Helmet"))

    assert [result.rolled for result in results] == [2, 3]
    assert [[mod.group for mod in result.affixes[:2]] for result in results] == [
        ["IncreasedLife", "ColdResistance"],
        ["IncreasedLife", "ColdResistance"],
    ]
    assert [len(result.affixes) for result in results] == [2, 3]
    assert results[0].shopping[-1] == {"kind": "free_line", "line": "anything", "delta": 0.0}


def test_a_template_group_missing_from_the_base_is_skipped_and_logged() -> None:
    mods = [mod for mod in _normal_armour_mods() if mod["group"] != "IncreasedLife"]
    lines: list[str] = []
    gear = WishlistGear(FakePob(mods), Objective(maximize="CombinedDPS"), _rails(), log=lines.append)
    gear._resistance_assignments["Helmet"] = "fire"

    result = gear.fill_slot("Helmet", "Fake Helmet")

    assert result.rolled == 1
    assert any("fixed IncreasedLife: skipped" in line for line in result.steps)
    assert any("fixed IncreasedLife: skipped" in line for line in lines)


def test_resistance_solver_caps_all_elements_and_reports_overcap() -> None:
    plan = solve_resistances(
        {"FireResist": 20, "ColdResist": -10, "LightningResist": 35},
        [(f"slot {index}", {"fire": 30, "cold": 30, "lightning": 30}) for index in range(9)],
    )

    assert len(plan.assignments) == 9
    assert all(value >= 75 for value in plan.totals.values())
    assert all(value == 0 for value in plan.shortfall.values())
    assert sum(plan.overcap.values()) > 0


def test_t3_resistance_solver_counts_two_two_stone_implicits_and_reports_overcap() -> None:
    plan = solve_resistances(
        {"FireResist": 48, "ColdResist": 18, "LightningResist": 63},
        [(f"slot {index}", {"fire": 38.5, "cold": 38.5, "lightning": 38.5}) for index in range(9)],
    )

    assert all(value >= 75 for value in plan.totals.values())
    assert sum(plan.overcap.values()) > 0


def test_resistance_solver_spends_at_most_two_extra_t3_lines_before_a_third_line_craft() -> None:
    plan = solve_resistances(
        {"FireResist": -100, "ColdResist": -100, "LightningResist": -100},
        [(f"slot {index}", {"fire": 38.5, "cold": 38.5, "lightning": 38.5}) for index in range(6)],
        extra_slots=[
            ("Ring 1", {"fire": 38.5, "cold": 38.5, "lightning": 38.5}),
            ("Ring 2", {"fire": 38.5, "cold": 38.5, "lightning": 38.5}),
            ("Amulet", {"fire": 38.5, "cold": 38.5, "lightning": 38.5}),
        ],
        max_extra=2,
    )

    assert len(plan.extra_assignments) <= 2
    assert sum(plan.shortfall.values()) > 0


def test_extra_resistance_lines_are_never_assigned_to_weapons() -> None:
    gear = WishlistGear(FakePob(_normal_armour_mods()), Objective(maximize="CombinedDPS"), _rails())
    plan = gear._plan_resistances({"Weapon 1": "Fake Wand", "Ring 1": "Fake Ring"})

    assert "Weapon 1" not in plan.extra_assignments


def test_resistance_plan_uses_existing_sources_before_spending_extra_lines() -> None:
    gear = WishlistGear(
        FakePob(_normal_armour_mods(), baseline={"FireResist": 75, "ColdResist": 75, "LightningResist": 75}),
        Objective(maximize="CombinedDPS"),
        _rails(),
    )

    plan = gear._plan_resistances({"Ring 1": "Fake Ring"})

    assert sum(plan.shortfall.values()) == 0


def test_resistance_solver_reports_the_shortfall_when_slots_cannot_cap() -> None:
    plan = solve_resistances(
        {"FireResist": 20, "ColdResist": -10, "LightningResist": 35},
        [("only slot", {"fire": 30, "cold": 30, "lightning": 30})],
    )

    assert sum(plan.shortfall.values()) > 0
    assert any(value > 0 for value in plan.shortfall.values())


def test_resistance_solver_never_uses_an_unavailable_element_to_avoid_overcap() -> None:
    plan = solve_resistances(
        {"FireResist": 75, "ColdResist": 75, "LightningResist": 75},
        [("ring", {"fire": 30, "cold": 30, "lightning": 0})],
    )

    assert plan.assignments == {"ring": "cold"}


def test_resistance_solver_accepts_each_elements_current_cap() -> None:
    plan = solve_resistances(
        {"FireResist": 80, "ColdResist": 75, "LightningResist": 75},
        (),
        floor={"fire": 80, "cold": 75, "lightning": 75},
    )

    assert plan.shortfall == {"fire": 0.0, "cold": 0.0, "lightning": 0.0}


def test_all_elemental_base_implicit_counts_for_every_resistance() -> None:
    gear = WishlistGear(FakePob([]), Objective(maximize="CombinedDPS"), _rails())
    values = gear._implicit_resistances("Prismatic Ring")

    assert values["fire"] == values["cold"] == values["lightning"] > 0


def test_resistance_planning_keeps_pobs_uncapped_total() -> None:
    gear = WishlistGear(
        FakePob([], baseline={"FireResist": 75, "ColdResist": 75, "LightningResist": 50,
                              "FireResistOverCap": 25, "ColdResistOverCap": 0, "LightningResistOverCap": 0}),
        Objective(maximize="CombinedDPS"),
        _rails(),
    )

    assert gear._resistance_baseline() == {"FireResist": 100.0, "ColdResist": 75.0, "LightningResist": 50.0}


def test_resistance_planning_reads_the_builds_own_elemental_maxima() -> None:
    gear = WishlistGear(
        FakePob([], baseline={"FireResistMax": 80, "ColdResistMax": 76, "LightningResistMax": 75}),
        Objective(maximize="CombinedDPS"),
        _rails(),
    )

    assert gear._resistance_floors() == {"fire": 80.0, "cold": 76.0, "lightning": 75.0}


def test_fixed_tier_is_ranked_on_the_whole_ladder_then_clamped_to_ilvl() -> None:
    gear = WishlistGear(FakePob(_normal_armour_mods()), Objective(maximize="CombinedDPS"), _rails())

    mod = gear._mod_at_tier("Fake Helmet", 24, "IncreasedLife", 3)

    assert mod is not None
    assert (mod.mod_id, mod.tier, mod.ladder) == ("IncreasedLife6", 6, 8)


def test_every_flexible_line_records_the_candidates_pob_judged() -> None:
    """The per-line table the reports print: candidate, before -> after, taken / refused, reason."""

    mods = [
        _mod("FlatPhys", "Prefix", mod_id="FlatPhys", line="Adds (21-21) to (39-39) Physical Damage", weight=5_000),
        _mod("Intelligence", "Suffix", mod_id="Int28", line="+(28-28) to Intelligence", tags=("attribute",), weight=5_000),
    ]
    objective = Objective(maximize="CombinedDPS", floors={"Life": 1_000.0})
    pob = FakePob(mods, worth={"FlatPhys": 142_099.0}, baseline={"Life": 810.0},
                  stats_by_token={"Int28": {"Life": 190.0}})

    result = WishlistGear(pob, objective, _rails()).fill_slot("Weapon 1", "Fake Bow")

    first = result.candidate_log[0]
    assert first["kind"] == "open" and first["buys_value"] is True
    rows = {str(row["candidate"]): row for row in first["rows"]}
    taken = next(row for row in first["rows"] if row["taken"])
    assert "Adds (21-21) to (39-39) Physical Damage" in str(taken["candidate"])
    assert taken["before"] == 1_000.0 and taken["after"] == 1_000.0 + 142_099.0
    assert not any("Intelligence" in label for label in rows)  # weapon requirements are paid by the rest of the set, never its own open line


def test_a_hybrid_mod_prints_every_line_it_has() -> None:
    """Rule 7: "Spell Damage + Mana" must not read as a second pure spell-damage mod."""

    hybrid = {
        "mod_id": "SpellDamageAndMana", "type": "Prefix", "group": "SpellDamageAndMana",
        "level": 70, "weight": 5_000,
        "lines": ["(25-30)% increased Spell Damage", "+(20-24) to maximum Mana"],
        "mod_tags": [],
    }
    gear = WishlistGear(FakePob([hybrid, _mod("Filler", "Suffix", weight=5_000)]),
                        Objective(maximize="CombinedDPS"), _rails())

    mod = next(entry for entry in gear._median_mods("Fake Wand", 76, affix_type="Prefix"))

    assert mod.text == "(25-30)% increased Spell Damage / +(20-24) to maximum Mana"
    assert mod.label == "T1/1 (25-30)% increased Spell Damage / +(20-24) to maximum Mana"
    # the fixed-tier and attribute readers carry the same lines
    assert gear._mod_at_tier("Fake Wand", 76, "SpellDamageAndMana", 1).text == mod.text


def test_the_shopping_list_records_the_whole_hybrid_line() -> None:
    hybrid = {
        "mod_id": "SpellDamageAndMana", "type": "Prefix", "group": "SpellDamageAndMana",
        "level": 70, "weight": 5_000,
        "lines": ["(25-30)% increased Spell Damage", "+(20-24) to maximum Mana"],
        "mod_tags": [],
    }
    gear = WishlistGear(FakePob([hybrid], worth={"SpellDamageAndMana": 10_000}),
                        Objective(maximize="CombinedDPS"), _rails())

    result = gear.fill_slot("Weapon 1", "Fake Wand")

    assert any("+(20-24) to maximum Mana" in str(line.get("line")) for line in result.shopping)


def test_an_open_mod_below_the_day_one_share_rail_is_never_offered() -> None:
    """The 0.2% rail survives rule 5; only the two-line PRICE is gone."""

    mods = [_mod("Common", "Suffix", weight=10_000), _mod("VeryRare", "Suffix", weight=1)]
    gear = WishlistGear(FakePob(mods), Objective(maximize="CombinedDPS"), _rails())

    assert {mod.group for mod in gear._median_mods("Fake Wand", 76, affix_type="Suffix")} == {"Common"}


def _gem_mods() -> list[dict]:
    """PoB's own shapes: a gem-tagged level mod, a gem-tagged non-level mod, an ordinary one."""

    return [
        _mod("Ordinary", "Prefix", weight=66_860),
        _mod("ColdSpellGems", "Prefix", mod_id="cold", weight=250,
             line="+1 to Level of all Cold Spell Skill Gems", tags=("elemental", "cold", "caster", "gem")),
        _mod("SocketedMelee", "Prefix", mod_id="melee", weight=500,
             line="+2 to Level of Socketed Melee Gems", tags=("attack", "gem")),
        _mod("SocketedGemQuality", "Prefix", mod_id="quality", weight=500,
             line="+7% to Quality of Socketed Gems", tags=("gem",)),
        _mod("AllSpellGems", "Prefix", mod_id="all", weight=50,
             line="+1 to Level of all Spell Skill Gems", tags=("caster", "gem")),
    ]


def test_a_gem_level_mod_is_read_from_pobs_parse_not_from_the_words() -> None:
    gear = WishlistGear(FakePob(_gem_mods()), Objective(maximize="CombinedDPS"), _rails())

    candidates = {mod.mod_id: mod for mod in gear._median_mods("Fake Wand", 76, affix_type="Prefix")}

    assert candidates["cold"].gem_level and candidates["melee"].gem_level  # all-cold-spell and socketed
    assert not candidates["quality"].gem_level  # gem-tagged, but not a level
    assert not candidates["Ordinary"].gem_level
    assert candidates["cold"].share == 250 / 68_160
    assert "all" not in candidates  # 50 / 68,160 = 0.07% < the 0.2% share rail


def test_a_gem_level_mod_takes_the_whole_open_budget_when_it_beats_ordinary_filling() -> None:
    """Rule 5: 100,000 beats the ordinary lines' 27,000, so it takes the whole three-line weapon."""

    mods = [
        _mod("SpellGemLevel", "Prefix", mod_id="gem1", weight=5_000,
             line="+1 to Level of all Chaos Spell Skill Gems", tags=("caster", "gem")),
        _mod("OpenA", "Prefix", weight=5_000),
        _mod("OpenB", "Suffix", weight=5_000),
        _mod("OpenC", "Suffix", weight=5_000),
    ]
    worth = {"gem1": 100_000, "OpenA": 10_000, "OpenB": 9_000, "OpenC": 8_000}

    result = WishlistGear(FakePob(mods, worth=worth), Objective(maximize="CombinedDPS"), _rails()).fill_slot("Weapon 1", "Fake Wand")

    assert result.mod_ids == ["gem1"] and result.bench_line is None
    assert sum("consumed by the gem-level line" in step for step in result.steps) == 2
    assert result.gem_level_trials and result.gem_level_trials[0]["kept"] is True


def test_a_gem_level_mod_that_loses_to_ordinary_filling_is_dropped() -> None:
    mods = [
        _mod("SpellGemLevel", "Prefix", mod_id="gem1", weight=5_000,
             line="+1 to Level of all Chaos Spell Skill Gems", tags=("caster", "gem")),
        _mod("OpenA", "Prefix", weight=5_000),
        _mod("OpenB", "Suffix", weight=5_000),
        _mod("OpenC", "Suffix", weight=5_000),
    ]
    worth = {"gem1": 15_000, "OpenA": 10_000, "OpenB": 9_000, "OpenC": 8_000}

    result = WishlistGear(FakePob(mods, worth=worth), Objective(maximize="CombinedDPS"), _rails()).fill_slot("Weapon 1", "Fake Wand")

    assert "gem1" not in result.mod_ids
    assert sorted(result.mod_ids) == ["OpenA", "OpenB"]
    assert result.gem_level_trials[0]["kept"] is False


def test_a_gem_level_mod_may_take_a_rings_single_open_line() -> None:
    mods = [
        *_tiers("IncreasedLife", "Prefix", 8),
        *_tiers("FireResistance", "Suffix", 8, line="+(20-24)% to Fire Resistance"),
        *_tiers("ColdResistance", "Suffix", 8, line="+(20-24)% to Cold Resistance"),
        *_tiers("LightningResistance", "Suffix", 8, line="+(20-24)% to Lightning Resistance"),
        _mod("ColdSpellGems", "Prefix", mod_id="cold", weight=250,
             line="+1 to Level of all Cold Spell Skill Gems", tags=("cold", "caster", "gem")),
        _mod("Ordinary", "Prefix", weight=66_910),
    ]

    def fill(gem_worth: float) -> object:
        gear = WishlistGear(FakePob(mods, worth={"cold": gem_worth, "Ordinary": 50_000}),
                            Objective(maximize="CombinedDPS"), _rails())
        gear._resistance_assignments["Ring 1"] = "fire"
        return gear.fill_slot("Ring 1", "Fake Ring")

    assert "cold" in fill(100_000).mod_ids
    assert "cold" not in fill(10_000).mod_ids


def _weapon_mods() -> list[dict]:
    """One flat damage prefix PoB pays for, one attribute suffix it does not."""

    return [
        _mod("LocalPhysicalDamage", "Prefix", mod_id="FlatPhys", line="Adds (21-21) to (39-39) Physical Damage"),
        _mod("IncreasedIntelligence", "Suffix", mod_id="Int28", line="+(28-28) to Intelligence", tags=("attribute",)),
        _mod("IncreasedMana", "Suffix", mod_id="Mana90", line="+(90-90) to maximum Mana"),
    ]


def test_a_weapon_line_buys_value_not_a_zero_value_floor_repair() -> None:
    """Rule 2: +142,099 DPS beats a +0 line that removes 0.19 of violation."""

    objective = Objective(maximize="CombinedDPS", floors={"Life": 1_000.0})
    pob = FakePob(
        _weapon_mods(),
        worth={"FlatPhys": 142_099.0},
        baseline={"Life": 810.0},
        stats_by_token={"Int28": {"Life": 190.0}},
    )
    gear = WishlistGear(pob, objective, _rails())

    result = gear.fill_slot("Weapon 1", "Fake Bow")

    assert "FlatPhys" in result.mod_ids
    assert "Int28" not in result.mod_ids  # +0 value: not a weapon purchase
    assert result.after.value == 1_000.0 + 142_099.0


def test_a_mandatory_slot_is_judged_against_its_bare_base_not_the_empty_slot() -> None:
    """impale_ballista's shape: the bow's EXISTENCE costs the mana, no line on it does.

    With the slot empty the main skill cannot be used, its cost is 0 and the
    sustain relation is trivially met; every bow then "worsens" it by the same
    amount and rule 2 refused all 24 open candidates and every craft, leaving the
    bow bare. Judged against the BARE BASE the candidates sit at the base's own
    violation and the best value wins.
    """

    mods = [
        _mod("LocalPhysicalDamage", "Prefix", mod_id="FlatPhys", weight=5_000,
             line="Adds (21-21) to (39-39) Physical Damage"),
        _mod("AttackSpeed", "Suffix", mod_id="Costly", weight=5_000,
             line="(11-13)% increased Attack Speed"),
    ]
    objective = Objective(maximize="CombinedDPS", relations=(("ManaRegen", "ManaPerSecondCost", 1.0),))
    pob = FakePob(
        mods,
        worth={"FlatPhys": 142_099.0, "Costly": 500_000.0},
        baseline={"ManaRegen": 50.0},
        # the base costs 100/s on its own; "Costly" doubles that
        stats_by_token={"Fake Bow": {"ManaPerSecondCost": 100.0}, "Costly": {"ManaPerSecondCost": 100.0}},
    )
    gear = WishlistGear(pob, objective, _rails())
    gear.base_candidates = lambda base: [base]

    result = gear.fill_slot("Weapon 1", "Fake Bow")

    assert result.mod_ids == ["FlatPhys"]  # same violation as the bare base: not "worse"
    first = result.candidate_log[0]
    assert first["before"] == 1_000.0  # the bare base's value, not the empty slot's
    rows = {str(row["candidate"]): row for row in first["rows"]}
    # the bare base already violates the relation by (100 - 50) / 100
    assert all(abs(float(row["before_violation"]) - 0.5) < 1e-9 for row in first["rows"])
    assert abs(float(rows["T1/1 Adds (21-21) to (39-39) Physical Damage"]["after_violation"]) - 0.5) < 1e-9
    costly = rows["T1/1 (11-13)% increased Attack Speed"]
    assert costly["taken"] is False and abs(float(costly["after_violation"]) - 0.75) < 1e-9
    assert str(costly["reason"]).startswith("refused: worsens")


def test_the_bare_base_baseline_also_holds_when_no_fixed_line_can_be_rolled() -> None:
    """An armour slot whose life and resistance lines are unavailable is still not empty."""

    pob = FakePob(
        [_mod("OpenDamage", "Prefix", mod_id="Open1", weight=5_000)],
        worth={"Fake Helmet": 7_000.0, "Open1": 10_000.0},
    )
    gear = WishlistGear(pob, Objective(maximize="CombinedDPS"), _rails())
    gear._resistance_assignments["Helmet"] = "fire"

    result = gear.fill_slot("Helmet", "Fake Helmet")

    assert "Open1" in result.mod_ids
    assert any("skipped (base cannot roll it)" in step for step in result.steps)
    taken = next(row for row in result.candidate_log[0]["rows"] if row["taken"])
    assert taken["before"] == 8_000.0 and taken["after"] == 18_000.0  # 1,000 empty + 7,000 base


def test_a_weapon_line_refuses_a_candidate_that_worsens_a_floor() -> None:
    mods = [
        _mod("LocalPhysicalDamage", "Prefix", mod_id="FlatPhys", line="Adds (21-21) to (39-39) Physical Damage"),
        _mod("ReducedLife", "Suffix", mod_id="Costly", line="+(10-10)% increased Attack Speed"),
    ]
    objective = Objective(maximize="CombinedDPS", floors={"Life": 1_000.0})
    pob = FakePob(
        mods,
        worth={"FlatPhys": 10.0, "Costly": 500_000.0},
        baseline={"Life": 1_000.0},
        stats_by_token={"Costly": {"Life": -400.0}},
    )
    gear = WishlistGear(pob, objective, _rails())

    result = gear.fill_slot("Weapon 1", "Fake Bow")

    assert "Costly" not in result.mod_ids and "FlatPhys" in result.mod_ids


def _armour_open_line_fill(shortfall: float, repair: float, *, other_shortfall: float = 0.0) -> object:
    """One Helmet template fill whose open line may buy `repair` of a `shortfall` Mana floor.

    ``other_shortfall`` is a second, untouchable floor: with it the repair leaves
    the build infeasible however much of the Mana floor it closes.
    """

    mods = [
        *_tiers("IncreasedLife", "Prefix", 8),
        *_tiers("FireResistance", "Suffix", 8, line="+(20-24)% to Fire Resistance"),
        *_tiers("ColdResistance", "Suffix", 8, line="+(20-24)% to Cold Resistance"),
        *_tiers("LightningResistance", "Suffix", 8, line="+(20-24)% to Lightning Resistance"),
        _mod("IncreasedMana", "Suffix", mod_id="Mana", line="+(90-90) to maximum Mana"),
    ]
    floors = {"Mana": 1_000.0}
    baseline = {"Mana": 1_000.0 - shortfall * 1_000.0}
    if other_shortfall:
        floors["TotalEHP"] = 1_000.0
        baseline["TotalEHP"] = 1_000.0 - other_shortfall * 1_000.0
    pob = FakePob(mods, baseline=baseline, stats_by_token={"Mana": {"Mana": repair * 1_000.0}})
    gear = WishlistGear(pob, Objective(maximize="CombinedDPS", floors=floors), _rails())
    gear._resistance_assignments["Helmet"] = "fire"
    return gear.fill_slot("Helmet", "Fake Helmet")


def test_an_armour_open_line_buys_a_real_floor_repair_but_not_a_rounding_one() -> None:
    """Rule 3: 0.02 of violation is a purchase at +0 value; 0.0016 that leaves the build infeasible is not."""

    bought = _armour_open_line_fill(0.52, 0.02, other_shortfall=0.5)
    refused = _armour_open_line_fill(0.5016, 0.0016, other_shortfall=0.5)

    assert "Mana" in bought.mod_ids
    assert "Mana" not in refused.mod_ids
    assert refused.shopping[-1] == {"kind": "free_line", "line": "anything", "delta": 0.0}


def test_an_armour_open_line_buys_the_small_repair_that_ends_the_whole_violation() -> None:
    """#174: the 0.01 floor is against noise, and a line that makes the build feasible is not noise.

    The shape is ground_slam_autocry s4's: 0.00195 of violation left
    (`NetLifeRegen+NetEnergyShieldRegen+SelfCostPerSecond = -15.6` against `Life
    = 7970`), no tree move that buys it without losing more than it gains, and one
    open jewellery/armour line that ends it at +0 value.
    """

    bought = _armour_open_line_fill(0.00195, 0.00195)
    still_refused = _armour_open_line_fill(0.5016, 0.0016, other_shortfall=0.5)

    assert "Mana" in bought.mod_ids
    assert "Mana" not in still_refused.mod_ids
    rows = {str(row["candidate"]): row for row in bought.candidate_log[-1]["rows"]}
    taken = rows["T1/1 +(90-90) to maximum Mana"]
    assert taken["taken"] is True and float(taken["after_violation"]) == 0.0
    assert abs(float(taken["violation_removed"]) - 0.00195) < 1e-9
    assert float(taken["after"]) == float(taken["before"])  # +0 value


def test_a_shield_in_the_weapon_two_slot_keeps_the_armour_rule() -> None:
    """The discriminator is the template, not the slot name.

    ``_buys_value`` reads the per-instance rails (template v4: a quiver may
    take the weapon shape under ``quiver_weapon_shape``), so it is an instance
    method now; any ``WishlistGear`` with today's default rails does.
    """

    gear = WishlistGear(FakePob([]), Objective(maximize="CombinedDPS"), _rails())
    assert not gear._buys_value("Fake Shield", "Weapon 2")
    assert gear._buys_value("Fake Bow", "Weapon 1")


def test_a_repaired_floor_counts_as_removed_violation() -> None:
    """A floor a candidate repairs outright leaves Objective.violations entirely."""

    assert WishlistGear._violation_removed({"Life": 0.19}, {}) == 0.19
    assert WishlistGear._violation_removed({}, {"Life": 0.19}) == -0.19


def test_elemental_resistance_groups_stay_with_the_solver_but_chaos_is_open() -> None:
    assert _is_elemental_resistance_group("FireAndLightningResistance")
    assert _is_elemental_resistance_group("AllResistances")
    assert not _is_elemental_resistance_group("ChaosResistance")


def test_the_resistance_predicate_never_swallows_an_elemental_damage_group() -> None:
    """Rule 7: elemental DAMAGE was never offered on any item because of this test."""

    for group in ("LocalLightningDamage", "SpellAddedLightningDamage", "LocalFireDamage",
                  "IncreasedWeaponElementalDamagePercent", "FireDamageOverTimeMultiplier",
                  "ColdDamageOverTimeMultiplier", "ElementalDamagePercent",
                  "LocalAttackReduceEnemyElementalResistance"):
        assert not _is_elemental_resistance_group(group), group
    for group in ("FireResistance", "ColdResistance", "LightningResistance",
                  "FireAndColdResistance", "FireAndLightningResistance", "ColdAndLightningResistance",
                  "AllResistances", "AllResistancesMinionResistances",
                  "FireAndChaosDamageResistance", "ColdAndChaosDamageResistance",
                  "LightningAndChaosDamageResistance"):
        assert _is_elemental_resistance_group(group), group


def test_bench_gem_level_line_cannot_share_a_weapon_with_open_mods() -> None:
    """Rule 5 on the craft line: once an open line is spent, the gem craft is out."""

    mods = _normal_armour_mods()
    bench = [
        {"type": "Prefix", "group": "SpellGemLevel", "level": 1, "rolled_lines": ["+1 to Level of all Chaos Spell Skill Gems"], "mod_tags": ["gem"], "families": ["SpellGemLevel"], "mod_id": None},
        {"type": "Suffix", "group": "CraftDamage", "level": 1, "rolled_lines": ["Craft damage"], "families": ["CraftDamage"], "mod_id": None},
    ]
    worth = {"{crafted}+1 to Level of all Chaos Spell Skill Gems": 100_000, "{crafted}Craft damage": 10,
             "OpenDamage3": 5_000}

    result = WishlistGear(FakePob(mods, worth=worth, bench=bench), Objective(maximize="CombinedDPS"), _rails()).fill_slot("Weapon 1", "Fake Wand")

    assert "OpenDamage3" in result.mod_ids
    assert result.bench_line == "Craft damage"


def test_open_or_craft_uses_the_measured_higher_scoring_candidate() -> None:
    mods = _normal_armour_mods()
    bench = [{"type": "Prefix", "group": "CraftDamage", "level": 1, "rolled_lines": ["Craft damage"], "families": ["CraftDamage"], "mod_id": None}]

    craft = WishlistGear(FakePob(mods, worth={"{crafted}Craft damage": 10_000}, bench=bench), Objective(maximize="CombinedDPS"), _rails())
    craft._resistance_assignments["Amulet"] = "fire"
    crafted = craft.fill_slot("Amulet", "Fake Amulet")
    open_mod = WishlistGear(FakePob(mods, worth={"OpenDamage4": 10_000}, bench=bench), Objective(maximize="CombinedDPS"), _rails())
    open_mod._resistance_assignments["Amulet"] = "fire"
    opened = open_mod.fill_slot("Amulet", "Fake Amulet")

    assert crafted.bench_line == "Craft damage" and "OpenDamage4" not in crafted.mod_ids
    assert opened.bench_line is None and "OpenDamage4" in opened.mod_ids


def test_shopping_results_keep_identical_items_in_their_own_slots() -> None:
    gear = WishlistGear(FakePob(_normal_armour_mods()), Objective(maximize="CombinedDPS"), _rails())
    gear._resistance_assignments.update({"Ring 1": "fire", "Ring 2": "fire"})

    first = gear.fill_slot("Ring 1", "Fake Ring")
    second = gear.fill_slot("Ring 2", "Fake Ring")

    assert first.raw == second.raw
    assert [result.slot for result in gear.shopping_results()] == ["Ring 1", "Ring 2"]


def test_pure_es_replaces_the_life_line_with_energy_shield() -> None:
    mods = [
        *_tiers("IncreasedLife", "Prefix", 8),
        *_tiers("IncreasedEnergyShield", "Prefix", 8, line="+(20-30) to maximum Energy Shield"),
        *_tiers("FireResistance", "Suffix", 8, line="+(20-24)% to Fire Resistance"),
        *_tiers("ColdResistance", "Suffix", 8, line="+(20-24)% to Cold Resistance"),
        *_tiers("LightningResistance", "Suffix", 8, line="+(20-24)% to Lightning Resistance"),
        *_tiers("OpenDamage", "Suffix", 8),
    ]
    gear = WishlistGear(FakePob(mods, baseline={"Life": 1_000, "EnergyShield": 5_000}), Objective(maximize="CombinedDPS"), _rails())
    gear._resistance_assignments["Body Armour"] = "lightning"

    result = gear.fill_slot("Body Armour", "Fake Body Armour")

    assert is_pure_es({"Life": 1_000, "EnergyShield": 5_000})
    assert result.affixes[0].group == "IncreasedEnergyShield"
    assert "IncreasedLife" not in [mod.group for mod in result.affixes]


def test_base_attribute_payment_uses_the_template_open_line_not_a_fourth_affix() -> None:
    mods = [
        *_tiers("IncreasedLife", "Prefix", 8),
        *_tiers("FireResistance", "Suffix", 8, line="+(20-24)% to Fire Resistance"),
        *_tiers("ColdResistance", "Suffix", 8, line="+(20-24)% to Cold Resistance"),
        *_tiers("LightningResistance", "Suffix", 8, line="+(20-24)% to Lightning Resistance"),
        _mod("Strength", "Suffix", mod_id="Strength1", level=70, line="+(60-60) to Strength", tags=("attribute",)),
    ]
    objective = Objective(maximize="CombinedDPS", relations=(("Str", "ReqStr", 1.0),))
    pob = FakePob(
        mods,
        worth={"Eternal Burgonet": 10_000},
        baseline={"Str": 100, "ReqStr": 0},
        stats_by_token={"Eternal Burgonet": {"ReqStr": 150}, "Strength1": {"Str": 60}},
    )
    gear = WishlistGear(pob, objective, _rails())
    gear._resistance_assignments["Helmet"] = "fire"

    result = gear.fill_slot("Helmet", "Iron Hat")

    assert result.base == "Eternal Burgonet"
    assert result.mod_ids == ["IncreasedLife3", "FireResistance3", "Strength1"]  # helmet resistance is T3 (#429)
    assert result.rolled == 3
    assert result.after.feasible


def test_base_screen_does_not_count_a_partial_attribute_payment_as_paid() -> None:
    mods = [
        *_tiers("IncreasedLife", "Prefix", 8),
        *_tiers("FireResistance", "Suffix", 8, line="+(20-24)% to Fire Resistance"),
        *_tiers("ColdResistance", "Suffix", 8, line="+(20-24)% to Cold Resistance"),
        *_tiers("LightningResistance", "Suffix", 8, line="+(20-24)% to Lightning Resistance"),
        _mod("Strength", "Suffix", mod_id="Strength1", level=70, line="+(20-20) to Strength", tags=("attribute",)),
    ]
    objective = Objective(maximize="CombinedDPS", relations=(("Str", "ReqStr", 1.0),))
    pob = FakePob(
        mods,
        worth={"Eternal Burgonet": 10_000},
        baseline={"Str": 100, "ReqStr": 0},
        stats_by_token={"Eternal Burgonet": {"ReqStr": 150}, "Strength1": {"Str": 20}},
    )
    gear = WishlistGear(pob, objective, _rails())
    gear.base_candidates = lambda _base: ["Eternal Burgonet"]

    ranked = gear._rank_bases("Helmet", "Iron Hat", 72, None)

    assert ranked == [BaseChoice("Eternal Burgonet")]


def test_base_attribute_bench_payment_occupies_the_open_or_craft_line() -> None:
    mods = [
        *_tiers("IncreasedLife", "Prefix", 8),
        *_tiers("FireResistance", "Suffix", 8, line="+(20-24)% to Fire Resistance"),
        *_tiers("ColdResistance", "Suffix", 8, line="+(20-24)% to Cold Resistance"),
        *_tiers("LightningResistance", "Suffix", 8, line="+(20-24)% to Lightning Resistance"),
    ]
    bench = [{"type": "Suffix", "group": "Strength", "level": 70, "rolled_lines": ["+60 to Strength"], "mod_tags": ["attribute"], "families": ["Strength"], "mod_id": None}]
    objective = Objective(maximize="CombinedDPS", relations=(("Str", "ReqStr", 1.0),))
    pob = FakePob(
        mods,
        worth={"Eternal Burgonet": 10_000},
        bench=bench,
        baseline={"Str": 100, "ReqStr": 0},
        stats_by_token={"Eternal Burgonet": {"ReqStr": 150}, "{crafted}+60 to Strength": {"Str": 60}},
    )
    gear = WishlistGear(pob, objective, _rails())
    gear.base_candidates = lambda _base: ["Eternal Burgonet"]
    gear._resistance_assignments["Helmet"] = "fire"

    result = gear.fill_slot("Helmet", "Iron Hat")

    assert result.bench_line == "+60 to Strength"
    assert result.rolled == 3 and len(result.affixes) == 2
    assert result.after.feasible


def test_one_item_never_carries_two_attribute_affixes() -> None:
    """Rule 4 / D73: at most one attribute affix or craft per ITEM."""

    mods = [
        *_tiers("IncreasedLife", "Prefix", 8),
        *_tiers("FireResistance", "Suffix", 8, line="+(20-24)% to Fire Resistance"),
        _mod("Strength", "Prefix", mod_id="Str1", line="+(60-60) to Strength", tags=("attribute",)),
        _mod("Dexterity", "Prefix", mod_id="Dex1", line="+(60-60) to Dexterity", tags=("attribute",)),
        _mod("Intelligence", "Suffix", mod_id="Int1", line="+(60-60) to Intelligence", tags=("attribute",)),
    ]
    objective = Objective(maximize="CombinedDPS", relations=(("Str", "ReqStr", 1.0),))
    pob = FakePob(mods, worth={"Str1": 5_000, "Dex1": 4_000, "Int1": 3_000}, baseline={"Str": 100, "ReqStr": 0})
    gear = WishlistGear(pob, objective, _rails())
    gear.base_candidates = lambda base: [base]
    gear._resistance_assignments["Weapon 1"] = "fire"

    result = gear.fill_slot("Weapon 1", "Fake Wand")

    assert sum(mod.attribute for mod in result.affixes) <= 1


def test_the_attribute_budget_counts_items_not_affixes() -> None:
    gear = WishlistGear(FakePob([]), Objective(maximize="CombinedDPS"), _rails())
    both = WishlistSlotResult(slot="Ring 1", base="Fake Ring", ilvl=72, bench_attribute=True)
    both.affixes = [WishlistMod("a", "Prefix", "Strength", 1, 1, "+30 to Strength", attribute=True)]
    gear.current_raw["Ring 1"] = "raw"
    gear._results_by_raw[("Ring 1", "raw")] = both

    assert gear._attribute_lines_used() == 1  # one ITEM, even with a rolled line and a craft


def test_a_weapon_does_not_pay_attributes_when_a_free_base_is_within_five_percent() -> None:
    """Rule 4: the weapon's base screen refuses the payment unless nothing comes close."""

    gear = WishlistGear(FakePob([]), Objective(maximize="CombinedDPS"), _rails())
    paid = ("Heavy Bow", Score(0.0, 100_000.0), BasePayment(mod=None, bench={"type": "Suffix"}))
    close = ("Light Bow", Score(0.0, 96_000.0), None)
    far = ("Light Bow", Score(0.0, 90_000.0), None)

    kept_close = gear._drop_weapon_payments_with_a_free_alternative("Weapon 1", "Fake Bow", [paid, close], [96_000.0])
    kept_far = gear._drop_weapon_payments_with_a_free_alternative("Weapon 1", "Fake Bow", [paid, far], [90_000.0])

    assert [entry[2] for entry in kept_close] == [None]  # 96,000 >= 95% of 100,000
    assert [entry[2] for entry in kept_far] == [paid[2], None]


def test_an_armour_slot_never_drops_an_attribute_payment_for_a_close_base() -> None:
    gear = WishlistGear(FakePob([]), Objective(maximize="CombinedDPS"), _rails())
    paid = ("Eternal Burgonet", Score(0.0, 100_000.0), BasePayment(mod=None, bench={"type": "Suffix"}))
    close = ("Iron Hat", Score(0.0, 99_000.0), None)

    kept = gear._drop_weapon_payments_with_a_free_alternative("Helmet", "Fake Helmet", [paid, close], [99_000.0])

    assert [entry[2] for entry in kept] == [paid[2], None]


def test_attribute_payments_are_limited_across_the_complete_template_set() -> None:
    mods = [
        *_tiers("IncreasedLife", "Prefix", 8),
        *_tiers("FireResistance", "Suffix", 8, line="+(20-24)% to Fire Resistance"),
        *_tiers("ColdResistance", "Suffix", 8, line="+(20-24)% to Cold Resistance"),
        *_tiers("LightningResistance", "Suffix", 8, line="+(20-24)% to Lightning Resistance"),
        _mod("Strength", "Suffix", mod_id="Strength1", level=70, line="+(60-60) to Strength", tags=("attribute",)),
    ]
    objective = Objective(maximize="CombinedDPS", relations=(("Str", "ReqStr", 1.0),))
    pob = FakePob(
        mods,
        baseline={"Str": 100, "ReqStr": 0},
        stats_by_token={"Heavy Helmet": {"ReqStr": 150}, "Heavy Gloves": {"ReqStr": 150}, "Strength1": {"Str": 60}},
    )
    gear = WishlistGear(pob, objective, _rails(attribute_affixes_max=1))
    gear.base_candidates = lambda base: [base]
    gear._resistance_assignments.update({"Helmet": "fire", "Gloves": "cold"})

    helmet = gear.fill_slot("Helmet", "Heavy Helmet")
    gloves = gear.fill_slot("Gloves", "Heavy Gloves")

    assert sum(mod.attribute for mod in helmet.affixes) == 1
    assert sum(mod.attribute for mod in gloves.affixes) == 0
    assert gear._attribute_lines_used() == 1


def test_paid_base_loses_to_a_better_finished_base_that_keeps_its_open_line() -> None:
    mods = [
        *_tiers("IncreasedLife", "Prefix", 8),
        *_tiers("FireResistance", "Suffix", 8, line="+(20-24)% to Fire Resistance"),
        *_tiers("ColdResistance", "Suffix", 8, line="+(20-24)% to Cold Resistance"),
        *_tiers("LightningResistance", "Suffix", 8, line="+(20-24)% to Lightning Resistance"),
        *_tiers("OpenDamage", "Prefix", 8),
        _mod("Strength", "Suffix", mod_id="Strength1", level=70, line="+(60-60) to Strength", tags=("attribute",)),
    ]
    objective = Objective(maximize="CombinedDPS", relations=(("Str", "ReqStr", 1.0),))
    pob = FakePob(
        mods,
        worth={"Heavy Helmet": 100, "OpenDamage4": 200},
        baseline={"Str": 100, "ReqStr": 0},
        stats_by_token={"Heavy Helmet": {"ReqStr": 150}, "Strength1": {"Str": 60}},
    )
    gear = WishlistGear(pob, objective, _rails())
    gear.base_candidates = lambda _base: ["Heavy Helmet", "Light Helmet"]
    gear._resistance_assignments["Helmet"] = "fire"

    result = gear.fill_slot("Helmet", "Heavy Helmet")

    assert result.base == "Light Helmet"
    assert "OpenDamage4" in result.mod_ids
    assert not any(mod.attribute for mod in result.affixes)


def test_the_base_screen_records_every_base_and_marks_the_one_the_slot_wears() -> None:
    mods = [
        *_tiers("IncreasedLife", "Prefix", 8),
        *_tiers("FireResistance", "Suffix", 8, line="+(20-24)% to Fire Resistance"),
        *_tiers("OpenDamage", "Prefix", 8),
        _mod("Strength", "Suffix", mod_id="Strength1", level=70, line="+(60-60) to Strength", tags=("attribute",)),
    ]
    objective = Objective(maximize="CombinedDPS", relations=(("Str", "ReqStr", 1.0),))
    pob = FakePob(
        mods,
        worth={"Heavy Helmet": 100, "OpenDamage4": 200},
        baseline={"Str": 100, "ReqStr": 0},
        stats_by_token={"Heavy Helmet": {"ReqStr": 150}, "Strength1": {"Str": 60}},
    )
    gear = WishlistGear(pob, objective, _rails())
    gear.base_candidates = lambda _base: ["Heavy Helmet", "Light Helmet"]
    gear._resistance_assignments["Helmet"] = "fire"

    result = gear.fill_slot("Helmet", "Heavy Helmet")

    assert result.base == "Light Helmet"
    assert ("Light Helmet", "TAKEN") in {(row["base"], row["verdict"]) for row in result.base_log}
    assert {"Heavy Helmet", "Light Helmet"} <= {str(row["base"]) for row in result.base_log}
    assert all(
        {"base", "implicit", "requirements", "drop_level", "value", "violation", "payment", "verdict"} <= set(row)
        for row in result.base_log
    )


def test_the_base_screen_reads_requirements_from_pobs_own_base_data() -> None:
    """burning_arrow_snipe's bow: the screen ranks violation first, and these differ by 132 dex."""

    assert WishlistGear._base_requirements("Bone Bow") == "dex 80, lvl 23"
    assert WishlistGear._base_requirements("Imperial Bow") == "dex 212, lvl 66"


def test_failed_reroll_keeps_the_existing_shopping_record() -> None:
    pob = FakePob(_normal_armour_mods())
    gear = WishlistGear(pob, Objective(maximize="CombinedDPS"), _rails())
    gear._resistance_assignments["Helmet"] = "fire"
    first = gear.fill_slot("Helmet", "Fake Helmet")
    original_craft = pob.craft_rare

    pob.craft_rare = lambda *_args, **_kwargs: {"problems": ["blocked"], "unsupported_lines": []}
    retry = gear.fill_slot("Helmet", "Other Helmet")
    pob.craft_rare = original_craft

    assert retry.raw == first.raw and retry.kept_incumbent
    assert gear.shopping_results() == [first]


def test_template_data_has_the_settled_armour_and_weapon_shapes() -> None:
    assert [line.kind for line in template_for("Fake Boots", "Boots")] == ["fixed", "resistance", "movement"]
    # #429: a weapon is 3 lines -- two open and one craft (rulebook i-day1-templates).
    assert [line.kind for line in template_for("Fake Wand", "Weapon 1")] == ["open", "open", "craft"]
    assert [line.affix_type for line in template_for("Fake Wand", "Weapon 1")] == ["either"] * 3
    assert len(template_for("Fake Helmet", "Helmet")) == 3
    assert len(template_for("Blazing Arrow Quiver", "Weapon 2", quiver_weapon_shape=True)) == 3


def test_weapon_template_rails_change_only_the_weapon_open_shape() -> None:
    gear = WishlistGear(FakePob([]), Objective(maximize="CombinedDPS"), _rails(weapon_open_lines=5))

    assert [line.kind for line in gear._template_for("Fake Wand", "Weapon 1")] == ["open"] * 5 + ["craft"]
    assert [line.kind for line in gear._template_for("Fake Helmet", "Helmet")] == ["fixed", "resistance", "open_or_craft"]


def test_weapon_open_tier_positions_are_applied_per_rank_and_repeat_the_last() -> None:
    mods = [*_tiers("Two", "Prefix", 2), *_tiers("Five", "Prefix", 5), *_tiers("Eight", "Prefix", 8), *_tiers("Ten", "Prefix", 10)]
    gear = WishlistGear(FakePob(mods), Objective(maximize="CombinedDPS"), _rails())
    template = gear._template_for("Fake Wand", "Weapon 1")

    selected = {
        position: {mod.group: mod.tier for mod in gear._median_mods("Fake Wand", 76, tier_position=position)}
        for position in (gear._weapon_open_tier_position(template, index) for index in range(5))
    }

    assert selected == {
        0.35: {"Two": 1, "Five": 2, "Eight": 3, "Ten": 4},
        0.5: {"Two": 1, "Five": 3, "Eight": 4, "Ten": 5},
        0.57: {"Two": 2, "Five": 3, "Eight": 5, "Ten": 6},
    }
    assert [gear._weapon_open_tier_position(template, index) for index in range(5)] == [0.35, 0.5, 0.57, 0.57, 0.57]


def test_legacy_weapon_tier_position_reads_as_a_one_element_list() -> None:
    rails = _wishlist_rails({"weapon_open_tier_position": 0.4})

    assert rails.weapon_open_tier_positions == (0.4,)


def test_two_weapon_open_lines_use_their_respective_tier_positions() -> None:
    mods = [*_tiers("First", "Prefix", 10), *_tiers("Second", "Prefix", 10), *_tiers("Third", "Prefix", 10)]
    worth = {"First4": 30_000, "Second5": 20_000, "Third6": 10_000}

    result = WishlistGear(FakePob(mods, worth=worth), Objective(maximize="CombinedDPS"), _rails()).fill_slot("Weapon 1", "Fake Wand")

    assert result.mod_ids == ["First4", "Second5"]


def test_weapon_tier_position_selects_the_nearest_tier() -> None:
    gear = WishlistGear(FakePob(_tiers("Damage", "Prefix", 10)), Objective(maximize="CombinedDPS"), _rails())

    low = gear._median_mods("Fake Wand", 76, tier_position=0.10)[0]
    high = gear._median_mods("Fake Wand", 76, tier_position=0.80)[0]

    assert (low.tier, high.tier) == (2, 8)


def test_explicit_default_weapon_tier_positions_are_bit_identical_on_the_fake() -> None:
    mods = [*_tiers("Damage", "Prefix", 10), *_tiers("Speed", "Suffix", 8)]
    worth = {"Damage5": 10_000, "Speed4": 9_000}

    default = WishlistGear(FakePob(mods, worth=worth), Objective(maximize="CombinedDPS"), _rails()).fill_slot("Weapon 1", "Fake Wand")
    explicit = WishlistGear(
        FakePob(mods, worth=worth),
        Objective(maximize="CombinedDPS"),
        _rails(weapon_open_lines=2, weapon_open_tier_positions=(0.35, 0.5, 0.57)),
    ).fill_slot("Weapon 1", "Fake Wand")

    assert default.raw == explicit.raw
    assert default.mod_ids == explicit.mod_ids
    assert default.bench_line == explicit.bench_line


def _weapon_base_records(monkeypatch, *, paid_level: int = 66) -> None:
    records = {
        "Free Bow": {"requirements": {"level": 66}},
        "Paid Bow": {"requirements": {"level": paid_level, "str": 145}},
    }
    monkeypatch.setattr(wishlist_module, "base_record", lambda name: records.get(name, {"requirements": {}}))


def _weapon_base_gear(worth: dict[str, float], *, paid_stats: dict[str, float] | None = None,
                      share: float | None = None) -> WishlistGear:
    objective = Objective(maximize="CombinedDPS", floors={"Life": 100.0}, relations=(("Str", "ReqStr", 1.0),))
    pob = FakePob(
        [],
        worth=worth,
        baseline={"Str": 100, "ReqStr": 0, "Life": 100},
        stats_by_token={"Paid Bow": {"ReqStr": 145, **(paid_stats or {})}},
    )
    gear = WishlistGear(
        pob,
        objective,
        _rails(**({"weapon_base_open_line_share": share} if share is not None else {})),
    )
    gear.base_candidates = lambda _base: ["Free Bow", "Paid Bow"]
    gear._attribute_capacity = lambda _slot, _stat: (60.0, 15.0, 3, 0.0)
    return gear


def test_payable_weapon_requirement_ranks_by_effective_value_even_with_a_higher_violation(monkeypatch) -> None:
    _weapon_base_records(monkeypatch)
    # The paid base gains 23% before its three 2.94%-share attribute lines, so
    # it must beat the free base despite a 0.08 unrelated-floor violation.
    gear = _weapon_base_gear({"Free Bow": 100_000, "Paid Bow": 123_230}, paid_stats={"Life": -8})

    ranked = gear._rank_bases("Weapon 1", "Fake Bow", 76, None)

    assert ranked[:2] == [BaseChoice("Paid Bow"), BaseChoice("Free Bow")]
    row = next(row for row in gear.base_screen["Weapon 1"] if row["base"] == "Paid Bow")
    assert row["payable"] is True and row["lines_needed"] == 3
    assert row["violation"] == 0.08
    assert row["effective_value"] == pytest.approx(124_230 * (1 - 3 * 0.0294))


def test_effective_value_tie_falls_to_the_lower_violation(monkeypatch) -> None:
    _weapon_base_records(monkeypatch)
    gear = _weapon_base_gear(
        {"Free Bow": 100_000, "Paid Bow": 201_000},
        paid_stats={"Life": -8},
        share=1 / 6,
    )

    ranked = gear._rank_bases("Weapon 1", "Fake Bow", 76, None)

    assert ranked[:2] == [BaseChoice("Free Bow"), BaseChoice("Paid Bow")]
    paid = next(row for row in gear.base_screen["Weapon 1"] if row["base"] == "Paid Bow")
    assert paid["effective_value"] == 101_000


def test_an_unpayable_weapon_requirement_is_dropped_by_name(monkeypatch) -> None:
    _weapon_base_records(monkeypatch)
    gear = _weapon_base_gear({"Free Bow": 100_000, "Paid Bow": 130_000})
    gear._attribute_capacity = lambda _slot, _stat: (44.0, 15.0, 3, 0.0)

    ranked = gear._rank_bases("Weapon 1", "Fake Bow", 76, None)

    assert ranked == [BaseChoice("Free Bow")]
    assert "requirement not payable: needs 45 Str, the set can pay 44" == next(
        row for row in gear.base_screen["Weapon 1"] if row["base"] == "Paid Bow"
    )["verdict"]


def test_no_payable_weapon_base_raises_instead_of_wearing_an_unpayable_fallback(monkeypatch) -> None:
    _weapon_base_records(monkeypatch)
    gear = _weapon_base_gear({"Paid Bow": 130_000})
    gear.base_candidates = lambda _base: ["Paid Bow"]
    gear._attribute_capacity = lambda _slot, _stat: (44.0, 15.0, 3, 0.0)

    with pytest.raises(ValueError, match="no payable weapon base"):
        gear._rank_bases("Weapon 1", "Fake Bow", 76, None)


def test_weapon_base_level_requirement_stays_a_hard_veto(monkeypatch) -> None:
    _weapon_base_records(monkeypatch, paid_level=78)
    gear = _weapon_base_gear({"Free Bow": 100_000, "Paid Bow": 200_000})

    ranked = gear._rank_bases("Weapon 1", "Fake Bow", 76, None)

    assert ranked == [BaseChoice("Free Bow")]
    assert next(row for row in gear.base_screen["Weapon 1"] if row["base"] == "Paid Bow")["verdict"] == "level requirement above rail"


def test_weapon_base_screen_keeps_an_unrelated_gem_requirement_in_its_violation(monkeypatch) -> None:
    _weapon_base_records(monkeypatch)
    gear = _weapon_base_gear({"Free Bow": 100_000, "Paid Bow": 112_000})
    gear.pob.baseline["Str"] = 80
    gear.pob.baseline["ReqStr"] = 100

    score = gear._score_without_own_base_requirements(
        {"Str": 80, "ReqStr": 145, "Life": 100, "CombinedDPS": 1_000},
        "Paid Bow",
        {"Str": 80, "ReqStr": 100},
    )

    assert score.violation == 0.2


def test_weapon_requirement_refill_tries_the_next_payable_base_once() -> None:
    gear = WishlistGear(FakePob([]), Objective(maximize="CombinedDPS"), _rails())
    old = WishlistSlotResult(slot="Weapon 1", base="Paid Bow", ilvl=76, raw="paid")
    gear._weapon_base_choices["Weapon 1"] = [BaseChoice("Paid Bow"), BaseChoice("Free Bow")]
    gear._unmet_weapon_requirement = lambda _result: {"Dex": 12.0}
    calls = []

    def refill(*args, **kwargs):
        calls.append((args, kwargs))
        return WishlistSlotResult(slot="Weapon 1", base="Free Bow", ilvl=76, raw="free")

    gear.fill_slot = refill
    results = gear._refill_unmet_weapon_requirement([old], {"Weapon 1": "Fake Bow"}, None, bench=True)

    assert len(calls) == 1
    assert results[0].base == "Free Bow"
    assert gear.weapon_requirement_refills == [{"slot": "Weapon 1", "from": "Paid Bow", "unmet": {"Dex": 12.0}, "refilled": True, "to": "Free Bow"}]


def test_weapon_requirement_refill_moves_forward_from_the_taken_rank() -> None:
    gear = WishlistGear(FakePob([]), Objective(maximize="CombinedDPS"), _rails())
    old = WishlistSlotResult(slot="Weapon 1", base="Paid Bow", ilvl=76, raw="paid")
    gear._weapon_base_choices["Weapon 1"] = [BaseChoice("Best Bow"), BaseChoice("Paid Bow"), BaseChoice("Free Bow")]
    gear._unmet_weapon_requirement = lambda _result: {"Dex": 12.0}
    gear.fill_slot = lambda *_args, **_kwargs: WishlistSlotResult(slot="Weapon 1", base="Free Bow", ilvl=76, raw="free")

    gear._refill_unmet_weapon_requirement([old], {"Weapon 1": "Fake Bow"}, None, bench=True)

    assert gear.weapon_requirement_refills[0]["to"] == "Free Bow"


def test_weapon_refill_ignores_an_unmet_requirement_not_owned_by_the_weapon(monkeypatch) -> None:
    _weapon_base_records(monkeypatch)
    gear = WishlistGear(FakePob([], baseline={"Str": 145, "ReqStr": 200}), Objective(maximize="CombinedDPS"), _rails())

    assert gear._unmet_weapon_requirement(WishlistSlotResult(slot="Weapon 1", base="Paid Bow", ilvl=76)) == {}


def test_attribute_capacity_uses_the_median_template_roll(monkeypatch) -> None:
    gear = WishlistGear(FakePob([]), Objective(maximize="CombinedDPS"), _rails(attribute_affixes_max=3))
    gear._fill_bases_by_slot = {"Weapon 1": "Fake Bow", "Helmet": "Fake Helmet", "Amulet": "Fake Amulet"}
    gear._filling_slots = frozenset(gear._fill_bases_by_slot)
    monkeypatch.setattr(wishlist_module, "bases_of_type", lambda item_type, **_kwargs: [f"{item_type} A", f"{item_type} B"])
    monkeypatch.setattr(wishlist_module, "type_of", lambda base: "Amulet" if "Amulet" in base else "Helmet")
    monkeypatch.setattr(wishlist_module, "implicit_of", lambda _base: "")
    gear._payment_slots = lambda _slot: [("Helmet", "Fake Helmet"), ("Amulet", "Fake Amulet")]
    gear._median_mods = lambda base, _ilvl: [
        WishlistMod(base, "Suffix", "Strength", 1, 1, "+(20-20) to Strength", lines=("+(20-20) to Strength",)),
        WishlistMod(base + "b", "Suffix", "Strength", 1, 1, "+(40-40) to Strength", lines=("+(40-40) to Strength",)),
    ]

    capacity, roll, slots, implicit = gear._attribute_capacity("Weapon 1", "Str")

    assert (capacity, roll, slots, implicit) == (60.0, 30.0, 2, 0.0)


def test_template_resistance_tiers_are_the_authors_medians_per_slot() -> None:
    """#429 (rulebook i-day1-templates): Рез T3 (36-41%) on every slot, so tier 3 of the whole ladder everywhere."""

    tiers = {
        slot: next(line.tier for line in template_for(base, slot) if line.kind == "resistance")
        for slot, base in (
            ("Helmet", "Fake Helmet"), ("Gloves", "Fake Gloves"), ("Body Armour", "Fake Body Armour"),
            ("Boots", "Fake Boots"), ("Belt", "Fake Belt"), ("Ring 1", "Fake Ring"),
            ("Amulet", "Fake Amulet"), ("Weapon 2", "Fake Shield"),
        )
    }
    assert tiers == {"Helmet": 3, "Gloves": 3, "Body Armour": 3, "Boots": 3, "Belt": 3,
                     "Ring 1": 3, "Amulet": 3, "Weapon 2": 3}


def _helmet_with_a_floor_line_and_a_damage_line(*, by_value: bool, damage: bool = True) -> object:
    """Spec 2026-09-26-template-loop-lines-by-value: a +0 line that repairs a real Mana shortfall against a damage line."""

    mods = [
        *_tiers("IncreasedLife", "Prefix", 8),
        *_tiers("FireResistance", "Suffix", 8, line="+(20-24)% to Fire Resistance"),
        *_tiers("ColdResistance", "Suffix", 8, line="+(20-24)% to Cold Resistance"),
        *_tiers("LightningResistance", "Suffix", 8, line="+(20-24)% to Lightning Resistance"),
        _mod("IncreasedMana", "Suffix", mod_id="Mana", line="+(90-90) to maximum Mana"),
        *(_tiers("OpenDamage", "Prefix", 8) if damage else []),
    ]
    pob = FakePob(
        mods,
        worth={"OpenDamage4": 9_000.0},
        baseline={"Mana": 950.0},
        stats_by_token={"Mana": {"Mana": 50.0}},
    )
    gear = WishlistGear(pob, Objective(maximize="CombinedDPS", floors={"Mana": 1_000.0}), _rails())
    gear._resistance_assignments["Helmet"] = "fire"
    gear.flexible_by_value = by_value
    return gear.fill_slot("Helmet", "Fake Helmet")


def test_an_armour_open_line_buys_the_floor_by_default_and_damage_when_the_loop_asks_for_value() -> None:
    floors_first = _helmet_with_a_floor_line_and_a_damage_line(by_value=False)
    by_value = _helmet_with_a_floor_line_and_a_damage_line(by_value=True)

    assert "Mana" in floors_first.mod_ids and "OpenDamage4" not in floors_first.mod_ids
    assert "OpenDamage4" in by_value.mod_ids and "Mana" not in by_value.mod_ids


def test_by_value_an_armour_line_worth_nothing_is_left_free() -> None:
    result = _helmet_with_a_floor_line_and_a_damage_line(by_value=True, damage=False)

    assert "Mana" not in result.mod_ids
    assert result.shopping[-1] == {"kind": "free_line", "line": "anything", "delta": 0.0}
