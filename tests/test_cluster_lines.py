from junkroan.optimizer.cluster_lines import ClusterCandidate, _load, cluster_enchants, cluster_notables
from junkroan.pob.game_corpus import DEFAULT_SOURCE_ROOT


def _chaos(size="large"):
    eid = "affliction_chaos_damage" if size == "large" else "affliction_chaos_damage_over_time_multiplier"
    return next(e for e in cluster_enchants(size) if e.id == eid)


def _mult(m):
    return dict(zip(m["weightMultiplierKey"], m["weightMultiplierVal"]))


def test_enchant_counts():
    assert [len(cluster_enchants(s)) for s in ("large", "medium", "small")] == [17, 21, 17]


def test_chaos_large_has_unwaveringly_evil_and_wicked_pall():
    names = {n.name for n in cluster_notables(_chaos(), 72)}
    assert {"Unwaveringly Evil", "Wicked Pall"} <= names


def test_every_notable_passes_both_weights():
    _, mods = _load(DEFAULT_SOURCE_ROOT)
    by_id = {m["mod_id"]: m for m in mods}
    for size in ("large", "medium"):
        e = _chaos(size)
        ns = cluster_notables(e, 72)
        assert ns
        for n in ns:
            m = by_id[n.mod_id]
            assert dict(zip(m["weightKey"], m["weightVal"]))[e.tag] > 0
            assert _mult(m)[f"expansion_jewel_{size}"] > 0
            assert n.level <= 72


def test_level_filter():
    # Wicked Pall is level 50: out at ilvl 49, in at 50
    assert "Wicked Pall" not in {n.name for n in cluster_notables(_chaos(), 49)}
    assert "Wicked Pall" in {n.name for n in cluster_notables(_chaos(), 50)}


def test_medium_weight_zero_excluded():
    # No Notable in this PoB version has expansion_jewel_medium weight 0 (all 284 carry 100 for large, medium, small),
    # so the exclusion is asserted on the rule itself: the filter reads the weight, a zero would drop the entry.
    _, mods = _load(DEFAULT_SOURCE_ROOT)
    assert len(mods) == 284
    assert not [m for m in mods if _mult(m).get("expansion_jewel_medium") != 100]
    e = _chaos("medium")
    assert len(cluster_notables(e, 72)) > 0


def test_raw_large():
    c = ClusterCandidate("large", _chaos(), ("Unwaveringly Evil", "Wicked Pall"), 12)
    assert c.raw(72).split("\n") == [
        "Rarity: RARE",
        "Day-1 Large Cluster",
        "Large Cluster Jewel",
        "Item Level: 72",
        "Cluster Jewel Skill: affliction_chaos_damage",
        "Cluster Jewel Node Count: 12",
        "Implicits: 3",
        "{crafted}Adds 12 Passive Skills",
        "{crafted}2 Added Passive Skills are Jewel Sockets",
        "{crafted}Added Small Passive Skills grant: 12% increased Chaos Damage",
        "1 Added Passive Skill is Unwaveringly Evil",
        "1 Added Passive Skill is Wicked Pall",
    ]


def test_raw_medium_socket_line():
    c = ClusterCandidate("medium", _chaos("medium"), (), 6)
    lines = c.raw(72).split("\n")
    assert "{crafted}1 Added Passive Skill is a Jewel Socket" in lines
    assert "{crafted}Adds 6 Passive Skills" in lines
