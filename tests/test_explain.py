"""Build explanation and Pareto front from the optimizer's trace (no PoB)."""

from junkroan.optimizer.explain import explain, pareto_front
from junkroan.optimizer.pipeline import BuildResult, StageRecord
from junkroan.search.skeleton import Skeleton, SocketGroup


def test_explanation_carries_the_numbers_it_came_from() -> None:
    sk = Skeleton(class_name="Duelist", ascendancy="Slayer", main_link=["Smite", "Multistrike", "Immolate"], rare_bases={"Weapon 1": "Infernal Sword"},
                  extra_groups=[SocketGroup(gems=["Anger"], slot="Boots", picked=True), SocketGroup(gems=["Dash"], slot="Helmet")])
    res = BuildResult(skeleton=sk)
    res.final_stats = {"CombinedDPS": 722_437.0, "Life": 3710, "TotalEHP": 10104.0, "FireResist": 75, "ColdResist": 75, "LightningResist": 75, "ChaosResist": -60,
                       "EffectiveMovementSpeedMod": 1.35, "RampSeconds": 0.0, "RampBudget": 2.5}
    res.conservative_stats = {"CombinedDPS": 722_437.0}
    res.optimistic_stats = {"CombinedDPS": 1_602_051.0}
    res.config_reasons = {"useFrenzyCharges": "charge generator found in build text; shown by PoB", "buffOnslaught": "off: source not found in build", "enemyIsBoss": "rails boss target"}
    res.keystones = ["Wind Dancer"]
    res.picks = [{"what": "supports", "choice": "Multistrike, Immolate", "value": 48_000.0, "before": 44_000.0, "seconds": 1.0},
                 {"what": "utilities", "choice": "Anger", "value": 65_000.0, "before": 48_000.0, "seconds": 1.0}]
    res.tree_steps = [{"name": "Fatal Blade", "kind": "notable", "cost": 4, "gain": 40_000.0}, {"name": "Life", "kind": "normal", "cost": 1, "gain": 0.0},
                      {"name": "Sword Mastery", "kind": "mastery", "cost": 1, "gain": 12_000.0}]
    res.stages = [StageRecord(name="tree greedy", seconds=90, stats={}, score_value=402_000.0, violation=0.5), StageRecord(name="config (final lanes)", seconds=9, stats={}, score_value=722_437.0, violation=0.0)]
    text = explain(res, variants=[("without Wind Dancer", 568_666.0), ("weapon Void Sceptre", 27_550.0)], reference=438_843.0)
    assert "Wind Dancer (rebuilt without it: 568,666, -21%)" in text
    assert "Infernal Sword (alternatives rebuilt as whole builds: Void Sceptre 27,550)" in text
    assert "supports chosen by PoB (Multistrike, Immolate; value 44,000 -> 48,000)" in text
    assert "picked by PoB: Anger (48,000 -> 65,000)" in text and "Dash" in text
    assert "Fatal Blade 40,000 (6%)" in text and "Masteries: Sword Mastery" in text
    assert "useFrenzyCharges" in text and "buffOnslaught" not in text and "enemyIsBoss" not in text
    assert "1,602,051 (+122% over conservative)" in text
    assert "CombinedDPS 722,437 conservative (+65% vs the reference 438,843)" in text and "ramp 0.0 s against a 2.5 s budget" in text
    assert "Audit: clean" in text and "Trajectory: tree 402,000 -> final config 722,437" in text


def test_pareto_front_keeps_the_undominated() -> None:
    rows = [{"value": 722, "ehp": 10_100}, {"value": 695, "ehp": 11_200}, {"value": 668, "ehp": 11_500}, {"value": 590, "ehp": 10_000}, {"value": 553, "ehp": 10_200}]
    assert pareto_front(rows) == {0, 1, 2}


def test_explanation_names_and_uses_the_full_dps_objective() -> None:
    res = BuildResult(skeleton=Skeleton(class_name="Witch", ascendancy="Necromancer", main_link=["Summon Raging Spirit"]), objective_stat="FullDPS")
    res.final_stats = {"CombinedDPS": 37_694.0, "FullDPS": 1_796_945.0, "Life": 3000, "TotalEHP": 8000.0,
                       "FireResist": 75, "ColdResist": 75, "LightningResist": 75, "ChaosResist": 0,
                       "EffectiveMovementSpeedMod": 1.2}
    res.conservative_stats = {"CombinedDPS": 37_694.0, "FullDPS": 1_796_945.0}
    res.optimistic_stats = {"CombinedDPS": 40_000.0, "FullDPS": 2_100_000.0}

    text = explain(res, reference=1_000_000.0)

    assert "Numbers: FullDPS 1,796,945 conservative (+80% vs the reference 1,000,000)" in text
    assert "Optimistic lane (every unproven toggle on): FullDPS 2,100,000 (+17% over conservative)." in text


def test_explanation_prints_the_template_shopping_list_in_order() -> None:
    result = BuildResult(skeleton=Skeleton(class_name="Witch", ascendancy="Elementalist", main_link=["Fireball"]), gear_mode="wishlist")
    result.gear_shopping = [{
        "slot": "Ring 1",
        "base": "Two-Stone Ring",
        "implicit": "+(12-16)% to Fire and Cold Resistances",
        "lines": [
            {"kind": "fixed", "line": "+70 to maximum Life", "tier": 2},
            {"kind": "resistance", "line": "+38% to Lightning Resistance", "tier": 3},
            {"kind": "open_or_craft", "line": "{crafted} 20% increased Damage", "delta": 1_234.0},
        ],
    }]

    text = explain(result)

    assert "Day-1 shopping list:" in text
    assert "Ring 1: Two-Stone Ring" in text
    assert "fixed T2 +70 to maximum Life; resistance T3 +38% to Lightning Resistance; open_or_craft {crafted} 20% increased Damage, delta 1,234" in text



def test_mapping_lines_name_what_pays_on_maps_and_what_is_missing() -> None:
    from junkroan.optimizer.mapping import mapping_lines

    stats = {"LifeOnKill": 60, "BlockChance": 65, "SpellBlockChance": 20, "TotalEHP": 24000, "PhysicalMaximumHitTaken": 4500, "EffectiveMovementSpeedMod": 1.3, "ProjectileCount": 3}
    text = "8% chance to gain a frenzy charge on kill\n10% increased movement speed\nrecover 2% of life on kill"
    lines = mapping_lines(stats, text, ["Spectral Throw", "Whirling Blades"], {"whirling blades": ("attack", "travel", "movement"), "spectral throw": ("attack", "projectile")})
    joined = " | ".join(lines)
    assert "recovery on kill: life 60" in joined
    assert "on-kill effects" in joined and "frenzy charge on kill" in joined and "recover 2% of life on kill" in joined
    assert "block 65%" in joined and "24,000" in joined and "4,500" in joined
    assert "movement 1.30x with Whirling Blades" in joined and "3 projectiles" in joined
    assert not any(l.startswith("lacks") for l in lines)
    bare = mapping_lines({"TotalEHP": 9000, "EffectiveMovementSpeedMod": 1.0}, "", ["Spark"], {})
    assert bare[-1] == "lacks: no life, mana or energy shield on kill, no travel skill"
