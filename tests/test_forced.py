"""#510 unit 0: the shared shape of a request's forced directions (PoB-free)."""

from junkroan.optimizer.trace import Trace
from junkroan.search.forced import affix_template, forced_of, has_forced, raw_has_affix
from junkroan.search.skeleton import Skeleton


def test_affix_template_drops_numbers_and_case() -> None:
    assert affix_template("+1 to Level of all Fire Spell Skill Gems") == affix_template("+2 to level of all Fire Spell  Skill Gems")
    assert affix_template("+(10-15) to maximum Life") != affix_template("+12 to maximum Mana")


def test_raw_has_affix_reads_one_line_of_the_item() -> None:
    raw = "Rarity: RARE\nDoom Song\nImbued Wand\n+1 to Level of all Fire Spell Skill Gems\n+30 to maximum Mana"
    assert raw_has_affix(raw, "+1 to Level of all Fire Spell Skill Gems")
    assert not raw_has_affix(raw, "+1 to Level of Socketed Melee Gems")


def test_forced_fields_round_trip_through_the_skeleton_json() -> None:
    sk = Skeleton(class_name="Witch", ascendancy="Elementalist", forced_uniques={"Body Armour": "Tabula Rasa"},
                  forced_bases={"Weapon 1": "Imbued Wand"}, forced_nodes=[1, 2],
                  forced_affixes={"Weapon 1": ["+1 to Level of all Fire Spell Skill Gems"]})
    back = Skeleton.from_json(sk.to_json())
    assert forced_of(back) == forced_of(sk)
    assert not has_forced(forced_of(Skeleton(class_name="Witch", ascendancy="Elementalist")))


def test_forced_of_and_trace_holder() -> None:
    class S:
        forced_uniques = {"Body Armour": "Tabula Rasa"}
        forced_bases: dict = {}
        forced_nodes = [1, 2]
        forced_affixes = {"Weapon 1": ["+1 to Level of all Fire Spell Skill Gems"]}

    f = forced_of(S())
    assert f["uniques"] == {"Body Armour": "Tabula Rasa"} and f["nodes"] == [1, 2] and has_forced(f)
    assert not has_forced(forced_of(object()))
    t = Trace()
    t.set_forced(f)
    assert t.forced() == f
    t.reset()
    assert t.forced() is None


def test_affix_template_reads_pob_item_lines_and_mod_ranges() -> None:
    line = "+1 to Level of all Fire Spell Skill Gems"
    assert raw_has_affix("Imbued Wand\n{tags:gem}{prefix}+1 to Level of all Fire Spell Skill Gems", line)
    assert affix_template("+(1-2) to Level of all Fire Spell Skill Gems") == affix_template(line)
    assert affix_template("{crafted}{range:0.5}+(10-15)% increased Spell Damage") == affix_template("12% increased Spell Damage".replace("12", "+12"))
