"""The Scion's Reliquarian is a real subclass, and PoB scores its nodes.

Until 2026-09-18 `NOT_PLAYER_ASCENDANCIES` held both Luminary and Reliquarian, on the claim
that their nodes "change nothing on the player". Measured on the smoke rig (Scion, level 90,
Fireball + Spell Echo + Controlled Destruction + Elemental Focus + Fire Penetration, smoke
boots, Pinnacle boss), baseline Life 1208 / SpellSuppressionChance 0 / CombinedDPS 10,641:

    Kaom's Roots (35448)        Life 1208 -> 1308 (+100)
    Elevore (48040)             SpellSuppressionChance 0 -> 25
    Xirgil's Crank (17386)      CombinedDPS 10,641 -> 12,014 (+12.9%)
    Presence of Chayula (54569) Life 1208 -> 966, EnergyShield 0 -> 246

Luminary stays excluded: its nodes are the Mercenary system, which PoB does not model.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest

from junkroan.optimizer.rails import Rails
from junkroan.pob.host_runtime import PoBHeadlessHostContractError
from junkroan.pob.session import PobSession
from junkroan.search.generator import SkeletonGenerator, _ascendancy_picks
from junkroan.search.hypothesis import Hypothesis, _records, ascendancy, validate
from junkroan.search.skeleton import Skeleton

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")

BOOTS = """Rarity: Rare
Smoke Boots
Titan Greaves
Item Level: 70
Quality: 0
Sockets: R-R-R-R
LevelReq: 68
Implicits: 0
+80 to maximum Life
30% increased Movement Speed
+35% to Fire Resistance
"""

MAIN_LINK = ["Fireball", "Spell Echo", "Controlled Destruction", "Elemental Focus", "Fire Penetration"]
KAOMS_ROOTS = 35448          # Armour Display hub:        +100 to maximum Life
ELEVORE = 48040              # Armour Display hub:        +25% chance to Suppress Spell Damage
XIRGILS_CRANK = 17386        # Caster Weapon Display hub: +1 to Level of all Spell Skill Gems


def _adjacency(nodes: dict[int, dict]) -> dict[int, set[int]]:
    adj: dict[int, set[int]] = defaultdict(set)
    for nid, n in nodes.items():
        for other in (*(n.get("incoming_node_ids") or []), *(n.get("outgoing_node_ids") or [])):
            if int(other) in nodes:
                adj[nid].add(int(other))
                adj[int(other)].add(nid)
    return adj


def _nodes(ascendancy_id: str) -> dict[int, dict]:
    for rec in _records("ascendancies.json"):
        if rec["ascendancy_id"] == ascendancy_id:
            return {int(n["node_id"]): n for n in rec["nodes"]}
    raise AssertionError(f"{ascendancy_id} is missing from the corpus")


# -- corpus only (fast) --------------------------------------------------------


def test_reliquarian_is_a_player_ascendancy_and_luminary_is_not() -> None:
    reliquarian = ascendancy("Reliquarian")
    assert reliquarian is not None and reliquarian["class_name"] == "Scion"
    assert ascendancy("Luminary") is None

    ok = validate(Hypothesis.from_dict({"class": "Scion", "ascendancy": "Reliquarian", "main_skill": "Fireball",
                                        "ascendancy_nodes": ["Kaom's Roots", "Xirgil's Crank"]}))
    assert ok.ok, ok.problems
    assert ok.skeleton is not None and ok.skeleton.ascendancy == "Reliquarian"
    assert sorted(ok.skeleton.ascendancy_nodes) == sorted([KAOMS_ROOTS, XIRGILS_CRANK])

    refused = validate(Hypothesis.from_dict({"class": "Scion", "ascendancy": "Luminary", "main_skill": "Fireball"}))
    assert not refused.ok
    assert "unknown ascendancy 'Luminary'" in " ".join(refused.problems)


def test_the_greedy_may_stop_on_a_choice_option_and_only_where_the_notable_is_empty() -> None:
    """A "choose one of these" group puts the stats on the options and leaves the notable empty,
    so notables alone leave the greedy nothing to score on the Reliquarian."""

    reliquarian = _nodes("Reliquarian")
    picks = _ascendancy_picks(reliquarian, _adjacency(reliquarian))
    assert {KAOMS_ROOTS, ELEVORE, XIRGILS_CRANK} <= picks
    # its only four notables are the empty "Display" hubs, which is why notables alone score nothing
    notables = [n for n in reliquarian.values() if n["is_notable"]]
    assert sorted(n["name"] for n in notables) == ["Armour Display", "Caster Weapon Display", "Jewellery Display", "Martial Weapon Display"]
    assert all(not n["stats"] for n in notables)

    # an ascendancy whose notables carry their own stats keeps exactly the notables it had
    for asc_id in ("Elementalist", "Deadeye", "Necromancer", "Hierophant"):
        nodes = _nodes(asc_id)
        assert _ascendancy_picks(nodes, _adjacency(nodes)) == {nid for nid, n in nodes.items() if n["is_notable"]}, asc_id


# -- PoB in the loop -----------------------------------------------------------


@pytest.mark.pob
@needs_pob
def test_reliquarian_nodes_move_pobs_numbers(tmp_path: Path) -> None:
    keys = ("Life", "SpellSuppressionChance", "CombinedDPS", "EnergyShield")
    with PobSession(run_id="test-reliquarian", artifacts_root=tmp_path) as pob:
        pob.set_identity(level=90)
        pob.set_tree(class_id="Scion", ascendancy_id="Reliquarian")
        pob.set_skills(main_link=MAIN_LINK)
        pob.set_items({"Boots": BOOTS})
        pob.set_config(enemy_state={"is_boss": "Pinnacle"})
        base = pob.stats(keys)
        assert pob.read_state()["tree_state"]["ascendancy_id"] == "Reliquarian"

        # two notables from two different hubs: PoB allocates each with its path and scores both
        pob.set_tree(class_id="Scion", ascendancy_id="Reliquarian", ascendancy_nodes=[KAOMS_ROOTS, XIRGILS_CRANK])
        state = pob.read_state()["tree_state"]
        assert {KAOMS_ROOTS, XIRGILS_CRANK} <= set(state["allocated_ascendancy_node_ids"])
        assert state["allocated_ascendancy_points"] == 8  # both picks carry their path
        both = pob.stats(keys)
        assert both["Life"] - base["Life"] == 100  # Kaom's Roots
        assert both["CombinedDPS"] > base["CombinedDPS"] * 1.1  # Xirgil's Crank, +1 spell gem level

        pob.set_tree(class_id="Scion", ascendancy_id="Reliquarian", ascendancy_nodes=[ELEVORE])
        assert pob.stats(keys)["SpellSuppressionChance"] - base["SpellSuppressionChance"] == 25

        # Kaom's Roots and Elevore are two options of the same hub: PoB keeps one and the
        # requested set does not materialize. The generator reads that refusal instead of
        # carrying a table of which options exclude which.
        with pytest.raises(PoBHeadlessHostContractError, match="did not materialize"):
            pob.set_tree(class_id="Scion", ascendancy_id="Reliquarian", ascendancy_nodes=[KAOMS_ROOTS, ELEVORE])


@pytest.mark.pob
@needs_pob
def test_the_generator_picks_reliquarian_nodes_by_pobs_numbers(tmp_path: Path) -> None:
    """pick_ascendancy_nodes must end on nodes that carry stats, not on the empty Display hubs."""

    rails = Rails.load()
    skeleton = Skeleton(class_name="Scion", ascendancy="Reliquarian", level=90, main_link=MAIN_LINK, main_slot="Body Armour")
    with PobSession(run_id="test-reliquarian-generator", artifacts_root=tmp_path) as pob:
        gen = SkeletonGenerator(pob, rails, objective=rails.objective().without_sustain())
        pob.set_identity(level=90)
        pob.set_tree(class_id="Scion", ascendancy_id="Reliquarian")
        pob.set_skills(main_link=MAIN_LINK)
        pob.set_items({"Boots": BOOTS})
        pob.set_config(enemy_state={"is_boss": "Pinnacle"})
        before = pob.stats(("Life", "TotalEHP"))
        chosen = gen.pick_ascendancy_nodes(skeleton, points=8)
        after = pob.stats(("Life", "TotalEHP"))

    nodes = _nodes("Reliquarian")
    assert chosen and set(chosen) <= set(nodes)
    # a pick that does something: not an empty Display hub, not a node that only grants a tree point
    real = [n for n in chosen if any("Passive Skill Point" not in s for s in nodes[n]["stats"])]
    assert real, f"the greedy stopped on hubs and passive points only: {[nodes[n]['name'] for n in chosen]}"
    assert after["Life"] > before["Life"] and after["TotalEHP"] > before["TotalEHP"]
    assert gen.picks and gen.picks[-1].what == "ascendancy" and gen.picks[-1].choice
