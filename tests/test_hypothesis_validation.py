"""Hypothesis validation is corpus-only and fast."""

from junkroan.search.hypothesis import Hypothesis, validate


def test_valid_hypothesis_becomes_a_skeleton() -> None:
    h = Hypothesis.from_dict({"name": "t", "class": "Witch", "ascendancy": "Elementalist", "main_skill": "Fireball", "supports": ["Burning Damage", "deadly ailments"],
                              "keystones": ["Elemental Overload"], "ascendancy_nodes": ["Shaper of Flames"], "uniques": {"Weapon 1": "Pledge of Hands"}, "rare_bases": {"Body Armour": "Vaal Regalia"}})
    v = validate(h)
    assert v.ok, v.problems
    sk = v.skeleton
    assert sk.main_link == ["Fireball", "Burning Damage", "Deadly Ailments"]
    assert sk.keystones and sk.ascendancy_nodes == [53123] and sk.uniques == {"Weapon 1": "Pledge of Hands"} and sk.rare_bases == {"Body Armour": "Vaal Regalia"}


def test_request_named_ascendancy_nodes_are_forced_on_the_skeleton() -> None:
    # #1157 unit 2: the ascendancy-swap move reads Skeleton.forced_ascendancy_nodes; a node the request named must end there
    named = Hypothesis.from_dict({"class": "Witch", "ascendancy": "Elementalist", "main_skill": "Fireball", "supports": ["Burning Damage"],
                                  "ascendancy_nodes": ["Shaper of Flames"]})
    v = validate(named)
    assert v.ok, v.problems
    assert v.skeleton.forced_ascendancy_nodes == [53123] == v.skeleton.ascendancy_nodes
    unnamed = Hypothesis.from_dict({"class": "Witch", "ascendancy": "Elementalist", "main_skill": "Fireball", "supports": ["Burning Damage"]})
    v2 = validate(unnamed)
    assert v2.ok, v2.problems
    assert v2.skeleton.forced_ascendancy_nodes == []


def test_invalid_names_and_geometry_are_rejected_not_guessed() -> None:
    h = Hypothesis.from_dict({"class": "Witch", "ascendancy": "Inquisitor", "main_skill": "Firebal", "supports": ["Awakened Burning Damage", "Empower"],
                              "keystones": ["Elemental Overlord"], "uniques": {"Helmet": "Pledge of Hands", "Ring 1": "Nonexistent Ring", "Weapon 1": "Pledge of Hands"}, "rare_bases": {"Weapon 1": "Void Sceptre"}})
    v = validate(h)
    assert not v.ok
    text = " ".join(v.problems)
    for needle in ("belongs to Templar", "unknown active skill", "Awakened", "Empower", "unknown keystone", "cannot go in Helmet", "unknown unique", "has both a unique and a rare base"):
        assert needle in text, (needle, v.problems)
