"""#510 unit 1: nodes / affixes in a day-1 request, resolved against PoB data, echoed as `fixed ...` (PoB-free)."""

from __future__ import annotations

from junkroan import cli
from junkroan.search.request import BuildRequest, expand

BASE = ["build", "--skill", "Fireball", "--ascendancy", "Elementalist", "--mode", "hit", "--dry-run"]
NODES = ["--nodes", "Elemental Overload,Holy Dominion"]
AFFIX = ["--affixes", "Wand=+1 to Level of all Fire Spell Skill Gems"]
UNIQUE = ["--unique", "Body Armour=Tabula Rasa"]


def _run(capfd, *extra: str) -> tuple[int, str]:
    rc = cli.main([*BASE, *extra])
    return rc, capfd.readouterr().out


def test_row1_all_five_are_fixed(capfd):
    rc, out = _run(capfd, *NODES, *AFFIX, *UNIQUE)
    assert rc == 0, out
    for line in ("fixed ascendancy: Elementalist", "fixed node: Elemental Overload", "fixed node: Holy Dominion",
                 "fixed affix: Weapon 1 (Wand): +1 to Level of all Fire Spell Skill Gems", "fixed unique: Body Armour = Tabula Rasa"):
        assert line in out, out
    assert "PROBLEMS" not in out


def test_row2_unknown_node_is_one_problem_line(capfd):
    rc, out = _run(capfd, "--nodes", "Elemental Overlord,Holy Dominion", *AFFIX, *UNIQUE)
    assert rc != 0
    assert out.count("unknown passive node 'Elemental Overlord'") == 1
    assert out.count("PROBLEMS") == 1 and "cannot roll" not in out


def test_row3_affix_that_cannot_roll_is_one_problem_line(capfd):
    rc, out = _run(capfd, *NODES, "--affixes", "Wand=+1 to Level of Socketed Melee Gems", *UNIQUE)
    assert rc != 0
    assert out.count("mod line '+1 to Level of Socketed Melee Gems' cannot roll on Wand") == 1
    assert "unknown" not in out


def _expand(**raw):
    return expand(BuildRequest.from_dict({"skill": "Fireball", "ascendancy": "Elementalist", "mode": "hit", **raw}))


def test_skeleton_carries_the_forced_directions():
    exp = _expand(nodes=["Elemental Overload", "Holy Dominion"], keystones=["Resolute Technique"],
                  affixes={"Wand": ["+1 to Level of all Fire Spell Skill Gems"]}, uniques={"Body Armour": "Tabula Rasa"},
                  rare_bases={"Helmet": "Hubris Circlet"})
    assert exp.ok, exp.problems
    sk = exp.validations[0].skeleton
    assert sk.forced_uniques == {"Body Armour": "Tabula Rasa"}
    assert sk.forced_bases == {"Helmet": "Hubris Circlet"}
    assert sk.forced_affixes == {"Weapon 1": ["+1 to Level of all Fire Spell Skill Gems"]}
    assert len(sk.forced_nodes) == 3 and set(sk.keystones) <= set(sk.forced_nodes)
    assert sk.weapon_types == ["Wand"]


def test_keystones_alias_joins_nodes():
    assert BuildRequest.from_dict({"nodes": ["A"], "keystones": ["B", "A"]}).nodes == ["A", "B"]


def test_affix_key_rules():
    ring = _expand(affixes={"Ring": ["+# to maximum Life"]})
    assert any("Ring 1 or Ring 2" in p for p in ring.problems)
    weapon = _expand(affixes={"Weapon 1": ["+1 to Level of all Fire Spell Skill Gems"]})
    assert any("needs one item class" in p for p in weapon.problems)
    ok = _expand(affixes={"Weapon 1": ["+1 to Level of all Fire Spell Skill Gems"]}, weapon_types=["Wand"])
    assert ok.ok, ok.problems
    clash = _expand(affixes={"Body Armour": ["+# to maximum Life"]}, uniques={"Body Armour": "Tabula Rasa"})
    assert any("holds the unique" in p for p in clash.problems)
    assert any("unknown mod line" in p for p in _expand(affixes={"Helmet": ["Makes you very strong"]}).problems)


def test_affixes_flag_accumulates_lines():
    assert cli._multi_pairs(["Wand=a", "Wand=b", "Helmet=c"]) == {"Wand": ["a", "b"], "Helmet": ["c"]}
