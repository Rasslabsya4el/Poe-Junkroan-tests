"""PoB-free tests of junkroan.optimizer.trace (#498)."""

import threading

from junkroan.optimizer import trace as tr
from junkroan.optimizer.trace import TRACE, classify, output_counts

UNIQUE = "Rarity: UNIQUE\nKikazaru\nTopaz Ring\nItem Level: 83\nLevelReq: 20\nImplicits: 0\n"
BOOTS = "Rarity: Rare\nSmoke Boots\nTitan Greaves\nItem Level: 70\nImplicits: 0\n+80 to maximum Life\n"
ANOINT = "Rarity: RARE\nDoom Gaze\nOnyx Amulet\nItem Level: 84\nImplicits: 1\n{enchant}Allocates Heart of Flame\n+50 to maximum Life\n"
CRAFTED = "Rarity: RARE\nDoom Coil\nTwo-Stone Ring\nItem Level: 84\nImplicits: 0\n{crafted}+25 to Dexterity\n+30 to maximum Life\n"
FLASK = "Rarity: MAGIC\nSeething Divine Life Flask of Staunching\nItem Level: 80\n"
CLUSTER = "Rarity: RARE\nDoom Jewel\nLarge Cluster Jewel\nItem Level: 84\nAdds 8 Passive Skills\n"


def _plain(trial):
    """classes without the registered ones: #438 `base-level:` (item_bases) and #432 `oil:` (anoint_candidates), added when imported"""
    return {c for c in classify(trial) if not c.startswith(("base-level:", "oil:"))}


def item(raw, slot="S"):
    return {"item": {"slot": slot, "raw": raw}}


def _builtin(trial):
    """classify() without the `rare-lines:*` classes a registered function adds once useful_lines is imported."""

    return {c for c in _plain(trial) if not c.startswith(("rare-lines:", "loot-base-"))}


def test_classify_items() -> None:
    assert _builtin(item(UNIQUE, "Ring 1")) == {"slot:Ring 1", "rarity:unique", "unique:Kikazaru", "base:Topaz Ring", "unique-tier:4"}
    assert _builtin(item(BOOTS, "Boots")) == {"slot:Boots", "rarity:rare", "base:Titan Greaves"}
    assert _builtin(item(ANOINT, "Amulet")) == {"slot:Amulet", "rarity:rare", "base:Onyx Amulet", "anoint"}
    assert _builtin(item(CRAFTED, "Ring 2")) == {"slot:Ring 2", "rarity:rare", "base:Two-Stone Ring", "bench-craft"}
    assert _builtin(item(FLASK, "Flask 1")) == {"slot:Flask 1", "rarity:magic", "base:Seething Divine Life Flask", "flask"}
    assert _builtin(item(CLUSTER, "Jewel 1")) == {"slot:Jewel 1", "rarity:rare", "base:Large Cluster Jewel", "cluster:large"}


def test_classify_tree_and_garbage() -> None:
    assert classify({"add": [1, 2]}, lambda n: "notable") == {"node:1", "node:2", "node-kind:notable"}
    assert classify({"remove": [3]}) == {"node-rm:3", "node-kind-rm:unknown"}
    assert classify({"mastery": {"5": 1}}) == {"node-kind:mastery"}
    for bad in ({}, {"item": None}, 42, None):
        assert classify(bad) == {"other"}


def test_classify_swap_sides_and_path() -> None:
    kinds = {11: "small", 12: "attribute+30"}
    nk = kinds.__getitem__
    assert classify({"add": [11], "remove": [12]}, nk) == {
        "node:11", "node-kind:small", "node-rm:12", "node-kind-rm:attribute+30"}
    assert classify({"add": [11], "path": [12, 11]}, nk) == {
        "node:12", "node-kind:attribute+30", "node:11", "node-kind:small"}


def test_default_node_kind_from_real_tree_data() -> None:
    # ids read from TreeGraph (var/vendor/poe-data); 5456 is "Might", a notable whose line is "+30 to Strength"
    for nid, kind in [(5456, "attribute+30"), (6, "notable"), (3354, "keystone"), (89, "mastery"), (94, "small")]:
        assert f"node-kind-rm:{kind}" in classify({"remove": [nid]}), nid
        assert f"node-kind:{kind}" in classify({"add": [nid]}), nid
        assert f"node:{nid}" in classify({"add": [nid]})


def test_default_node_kind_unknown_and_failing_loader(monkeypatch) -> None:
    from junkroan.optimizer.tree_graph import TreeGraph

    assert "node-kind-rm:unknown" in classify({"remove": [999999999]})
    assert tr.default_node_kind(999999999) == "unknown"

    def boom(cls):
        raise RuntimeError("no tree")

    monkeypatch.setattr(TreeGraph, "load", classmethod(boom))
    assert classify({"remove": [94]}) >= {"node-rm:94", "node-kind-rm:unknown"}
    assert output_counts([], [94])["node-kind:unknown"] == 1


def test_registry_swallows_errors() -> None:
    saved = list(tr._REGISTRY)  # classes registered at import (item_bases' base-level, #438) must survive this test

    def boom(t):
        raise RuntimeError

    tr.register_class(boom)
    tr.register_class(lambda t: ["extra"])
    try:
        assert classify({"remove": [1]}) == {"node-rm:1", "node-kind-rm:unknown", "extra"}
    finally:
        tr._REGISTRY[:] = saved


def test_counts_flush_move_pending() -> None:
    TRACE.reset()
    flask = item(FLASK)
    TRACE.count_candidates([flask] * 3)
    TRACE.count_trial(flask)
    TRACE.count_trial(flask)
    assert "(unattributed)" in TRACE.considered()
    TRACE.flush("picks")
    assert TRACE.considered()["picks"]["flask"] == {"generated": 3, "evaluated": 2}
    assert "(unattributed)" not in TRACE.considered()
    TRACE.count_trial(flask)
    TRACE.flush("picks")
    assert TRACE.considered()["picks"]["flask"] == {"generated": 3, "evaluated": 3}
    with TRACE.move("a"):
        TRACE.add_generated(["x"], 2)
        with TRACE.move("b"):
            TRACE.add_evaluated(["x"])
        TRACE.add_evaluated(["x"], 4)
    c = TRACE.considered()
    assert c["a"]["x"] == {"generated": 2, "evaluated": 4}
    assert c["b"]["x"] == {"generated": 0, "evaluated": 1}
    assert list(c) == ["picks", "a", "b"]
    TRACE.reset()
    assert TRACE.considered() == {}


def test_thread_safety() -> None:
    TRACE.reset()

    def work():
        for _ in range(1000):
            TRACE.add_evaluated({"x"})

    ts = [threading.Thread(target=work) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert TRACE.considered()["(unattributed)"]["x"]["evaluated"] == 8000
    TRACE.reset()


def test_output_counts() -> None:
    got = output_counts([UNIQUE, FLASK, CRAFTED], [10, 11], lambda n: "small")
    assert got["flask"] == 1 and got["bench-craft"] == 1 and got["rarity:unique"] == 1
    assert got["node:10"] == 1 and got["node-kind:small"] == 2
    TRACE.set_output(got)
    assert TRACE.output() == got
    TRACE.reset()
