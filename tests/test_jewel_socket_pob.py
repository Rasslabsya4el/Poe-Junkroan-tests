"""#434 unit 2: a jewel in an allocated passive-tree socket, put / removed through `PobSession`, counted by PoB.

Build: the Stormbrand fixture of tuadh_329 (Templar / Inquisitor, no jewel socket allocated). The cheapest
reachable jewel socket is node 36634 (two nodes of path, found with `trial_stats` add trials over every
`isJewelSocket` node of tree 3_28); 41263 is the second one, also two nodes, used as "another socket".
The jewel is a rare Crimson Jewel with one line, `8% increased maximum Life`.

Asserts: (a) the jewel moves `Life` against the empty socket; (b) the `fast` removal trial of the socket
equals the real removal to 0.1 %; (c) the jewel survives `mutate_nodes` of other nodes; (d) it survives
`set_tree(..., jewels=...)` and a `set_tree` without `jewels` drops it; (e) the export carries it in its socket.
A plain unit test checks the `socketed_jewel_items` payload shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree

import pytest

from junkroan.pob.session import PobSession, decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]

SOCKET = 36634
OTHER_SOCKET = 41263
KEYS = ("Life", "CombinedDPS", "TotalEHP")
LIFE_LINE = "8% increased maximum Life"
JEWEL = "\n".join([
    "Rarity: RARE",
    "Doom Eye",
    "Crimson Jewel",
    "Item Level: 84",
    "Implicits: 0",
    LIFE_LINE,
])

_RUNTIME_MISSING = pytest.mark.skipif(
    not (RUNTIME_ROOT / "lua51.dll").is_file(),
    reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}",
)


def needs_pob(test):
    """The `pob` mark plus the skip when the pinned runtime is absent."""

    return pytest.mark.pob(_RUNTIME_MISSING(test))


@pytest.fixture()
def pob():
    with PobSession(run_id="test-jewel-socket", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as session:
        session.load_xml(decode_import_code((FIXTURES / "stormbrand.pob.txt").read_text(encoding="utf-8").strip()))
        session.add_nodes([SOCKET])
        yield session


def _within(a: float, b: float, rel: float = 0.001) -> bool:
    return abs(a - b) <= rel * max(abs(a), abs(b))


def test_set_tree_payload_carries_jewels_as_socketed_jewel_items() -> None:
    """No PoB: `set_tree(jewels=...)` sends `{node_id, raw_item_text}` entries in `socketed_jewel_items`."""

    class Adapter:
        payload: dict | None = None

        def apply_tree_state(self, handle, payload):
            Adapter.payload = payload
            return {}

    session = PobSession.__new__(PobSession)
    session._adapter = Adapter()
    session._handle = object()
    session._measured_call = lambda name, fn, *args: fn(*args)  # type: ignore[method-assign]
    session.set_tree(class_id="Templar", jewels={36634: JEWEL})
    assert Adapter.payload is not None
    assert Adapter.payload["socketed_jewel_items"] == [{"node_id": 36634, "raw_item_text": JEWEL}]
    session.set_tree(class_id="Templar")
    assert "socketed_jewel_items" not in Adapter.payload
    with pytest.raises(ValueError):
        session.set_tree(class_id="Templar", jewels={1: JEWEL}, extra={"socketed_jewel_items": []})


@needs_pob
def test_a_jewel_moves_the_build_and_an_unallocated_socket_refuses(pob: PobSession) -> None:
    empty = pob.stats(KEYS)
    assert pob.socketed_jewels() == {}
    with pytest.raises(Exception, match="not allocated"):
        pob.put_jewel(OTHER_SOCKET, JEWEL)
    with pytest.raises(Exception, match="not a jewel socket"):
        pob.put_jewel(1, JEWEL)
    assert pob.socketed_jewels() == {}
    held = pob.put_jewel(SOCKET, JEWEL)
    assert list(held) == [SOCKET] and LIFE_LINE in held[SOCKET]
    with_jewel = pob.stats(KEYS)
    print(f"\n(a) Life {empty['Life']} -> {with_jewel['Life']}  CombinedDPS {empty['CombinedDPS']:.1f} -> {with_jewel['CombinedDPS']:.1f}")
    assert with_jewel["Life"] > empty["Life"] * 1.02
    assert pob.socketed_jewels() == held
    assert pob.remove_jewel(SOCKET) == {}
    assert pob.stats(KEYS) == empty
    pob.remove_jewel(SOCKET)  # an empty socket is a no-op


@needs_pob
def test_b_fast_removal_trial_of_the_socket_agrees_with_the_real_removal(pob: PobSession) -> None:
    pob.put_jewel(SOCKET, JEWEL)
    with_jewel = pob.stats(KEYS)
    fast = pob.trial_stats([{"remove": [SOCKET]}], KEYS, mode="fast")[0]
    full = pob.trial_stats([{"remove": [SOCKET]}], KEYS, mode="full")[0]
    assert fast["ok"] and full["ok"], (fast, full)
    assert pob.stats(KEYS) == with_jewel  # a trial leaves the build as it was
    pob.remove_nodes([SOCKET])
    real = pob.stats(KEYS)
    print("\n(b) with jewel", {k: round(v, 3) for k, v in with_jewel.items()})
    for key in ("CombinedDPS", "Life", "TotalEHP"):
        pct = 100 * abs(fast["stats"][key] - real[key]) / max(abs(real[key]), 1e-9)
        print(f"(b) {key}: fast {fast['stats'][key]:.3f}  full-trial {full['stats'][key]:.3f}  real {real[key]:.3f}  diff {pct:.4f} %")
        assert _within(fast["stats"][key], real[key]), key
        assert _within(full["stats"][key], real[key]), key
    assert not _within(fast["stats"]["Life"], with_jewel["Life"]), "the removal trial ignores the jewel"


@needs_pob
def test_c_the_jewel_survives_mutate_nodes_of_other_nodes(pob: PobSession) -> None:
    pob.put_jewel(SOCKET, JEWEL)
    life = pob.stats(("Life",))["Life"]
    before_tree = set(pob.tree_light()["user_allocated_node_ids"])
    added = pob.mutate_nodes(add=[OTHER_SOCKET])["added_node_ids"]
    assert OTHER_SOCKET in added
    assert list(pob.socketed_jewels()) == [SOCKET]
    pob.mutate_nodes(remove=added)
    assert set(pob.tree_light()["user_allocated_node_ids"]) == before_tree
    held = pob.socketed_jewels()
    assert list(held) == [SOCKET] and LIFE_LINE in held[SOCKET]
    assert pob.stats(("Life",))["Life"] == life


@needs_pob
def test_d_set_tree_with_jewels_keeps_it_and_without_jewels_clears_it(pob: PobSession) -> None:
    pob.put_jewel(SOCKET, JEWEL)
    state = pob.read_state()["tree_state"]
    tree = dict(
        class_id=state["class_id"],
        ascendancy_id=state["ascendancy_id"],
        nodes=state["user_allocated_node_ids"],
        ascendancy_nodes=state["allocated_ascendancy_node_ids"],
        keystones=state["keystone_node_ids"],
        masteries=state["mastery_effect_ids"],
    )
    pob.set_tree(**tree)
    assert pob.socketed_jewels() == {}  # set_tree clears every socket and re-applies only `jewels`
    bare = pob.stats(KEYS)
    pob.set_tree(**tree, jewels={SOCKET: JEWEL})
    held = pob.socketed_jewels()
    assert list(held) == [SOCKET] and LIFE_LINE in held[SOCKET]
    with_jewel = pob.stats(KEYS)
    print(f"\n(d) set_tree Life {bare['Life']} -> {with_jewel['Life']}")
    assert with_jewel["Life"] > bare["Life"] * 1.02



def _xml_sockets(xml: str) -> dict[int, int]:
    """{socket node id: item id} of the active spec's `<Sockets>` (attribute order in the export varies)."""

    return {int(s.get("nodeId")): int(s.get("itemId")) for s in ElementTree.fromstring(xml).iter("Socket")}


@needs_pob
def test_e_export_xml_carries_the_jewel_in_its_socket(pob: PobSession) -> None:
    pob.put_jewel(SOCKET, JEWEL)
    xml = pob.export_xml()
    sockets = _xml_sockets(xml)
    assert sockets.get(SOCKET, 0) > 0, sockets
    items = {int(i.get("id")): "".join(i.itertext()) for i in ElementTree.fromstring(xml).iter("Item")}
    assert LIFE_LINE in items[sockets[SOCKET]] and "Crimson Jewel" in items[sockets[SOCKET]]
    # the exported build loads back with the jewel in the same socket and the same Life
    life = pob.stats(("Life",))["Life"]
    pob.load_xml(xml)
    assert list(pob.socketed_jewels()) == [SOCKET]
    assert pob.stats(("Life",))["Life"] == life
    pob.remove_jewel(SOCKET)
    assert _xml_sockets(pob.export_xml()).get(SOCKET, 0) == 0
