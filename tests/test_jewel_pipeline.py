"""#434 unit 4: the jewel step wired into the pipeline.

Plain tests (a fake session, no PoB): every `set_tree` the pipeline calls after the step passes the jewels it
holds; `_finish` drops a jewel whose socket a later step freed; the step is loaded back when the build, with its
lanes derived again, scores below what it was before; the end re-pick writes one `result.moves` row per jewel.

`pob` tests: one short build of the Stormbrand fixture with `count_max` 1 (the log line, the jewel in the exported
XML in an allocated socket, a jewel only when it beats the build), the probe's `restore` giving the score back, and
the 7 hybrid lines PoB parses like `craft_rare` writes them.
"""

from __future__ import annotations

import dataclasses
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest

from junkroan.optimizer import pipeline as pipeline_module
from junkroan.optimizer.jewel_lines import JewelLine, jewel_line_candidates, rare_jewel_raw
from junkroan.optimizer.jewel_step import JewelStepResult, PlacedJewel
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.pipeline import BuildPipeline, BuildResult
from junkroan.pob.session import PobSession, decode_import_code, is_cluster_jewel_raw

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
_RUNTIME_MISSING = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")


def needs_pob(test):
    return pytest.mark.pob(_RUNTIME_MISSING(test))


class Line:
    def __init__(self, id: str) -> None:
        self.id = id
        self.base = "Crimson Jewel"  # the trace classes read a candidate's base (#434 unit 8)
        self.mod_id = id
        self.lines = (id,)


class FakePob:
    """What the pipeline's jewel code asks of a session: stats, XML, the tree, the jewels."""

    def __init__(self, value: float = 100.0, allocated=(1, 2, 3)) -> None:
        self.value = value
        self.allocated = list(allocated)
        self.held: dict[int, str] = {}
        self.xml = "xml-0"
        self.loaded: list[str] = []
        self.set_tree_calls: list[dict] = []
        self.removed: list[int] = []

    def stats(self, keys):
        return {k: 0 for k in keys} | {"CombinedDPS": self.value}

    def export_xml(self):
        return self.xml

    def load_xml(self, xml):
        self.loaded.append(xml)
        self.value, self.held = 100.0, {}  # the pre-step build

    def tree_light(self):
        return {"user_allocated_node_ids": list(self.allocated)}

    def socketed_jewels(self):
        return dict(self.held)

    def remove_jewel(self, socket):
        self.removed.append(socket)
        self.held.pop(socket, None)

    def set_tree(self, **kwargs):
        self.set_tree_calls.append(kwargs)

    def add_nodes(self, nodes):
        pass


def _pipeline(pob: FakePob, *, count_max: int = 2) -> BuildPipeline:
    p = BuildPipeline.__new__(BuildPipeline)
    p.pob = pob
    p.judging = SimpleNamespace(objective=None, rejudge=lambda *_a, **_k: None)
    p.objective = Objective(maximize="CombinedDPS")
    p.rails = SimpleNamespace(gear=SimpleNamespace(jewels=SimpleNamespace(count_max=count_max, lines=1)))
    p.logged = []
    p.log = p.logged.append
    p._jewels = {}
    p._jewel_placed = []
    p._trees = ()
    return p


def _result() -> BuildResult:
    return BuildResult(skeleton=SimpleNamespace(class_name="Templar", ascendancy="Inquisitor", main_link=["Stormbrand"]))


def _placed(socket: int, line: str = "8% increased maximum Life", **kw) -> PlacedJewel:
    return PlacedJewel(socket_id=socket, candidate=Line(line), score_before=100.0, score_after=150.0, measured=3, ranking=((Line(line), 150.0),), **kw)


# -- set_tree carries the jewels ----------------------------------------------------------------------------


def test_set_tree_passes_the_jewels_only_when_there_are_some() -> None:
    pob = FakePob()
    p = _pipeline(pob)
    skeleton = SimpleNamespace(class_name="Templar", ascendancy="Inquisitor", ascendancy_nodes=[7], keystones=[])
    tree = SimpleNamespace(history=[1], invalidate_after_recovery=lambda **_k: None)
    p._reset_construction_tree(skeleton, tree)
    assert "jewels" not in pob.set_tree_calls[-1]  # no jewel: the call is the one a session without the argument takes
    p._jewels = {36634: "raw jewel"}
    p._reset_construction_tree(skeleton, tree)
    assert pob.set_tree_calls[-1]["jewels"] == {36634: "raw jewel"}


def test_rebuild_tree_passes_the_jewels(monkeypatch: pytest.MonkeyPatch) -> None:
    pob = FakePob()
    pob.mutate_nodes = lambda **_k: {"points_used": 0}
    p = _pipeline(pob)
    p._jewels = {36634: "raw jewel"}
    p.judging.rejudge = lambda *_a, **_k: p.objective
    score = p.objective.score({"CombinedDPS": 100.0})
    tree = SimpleNamespace(objective=p.objective, history=[], repair_estimate_mode="sum", current_score=lambda: (score, None),
                           allocate=lambda *_a, **_k: None, refine=lambda **_k: None)
    skeleton = SimpleNamespace(class_name="Templar", ascendancy="Inquisitor", ascendancy_nodes=[], keystones=[], scaling=None)
    p._rebuild_tree(skeleton, tree, 10)
    assert [c["jewels"] for c in pob.set_tree_calls] == [{36634: "raw jewel"}] * 2  # sum and cover


# -- _finish drops a jewel in a socket nobody allocates -------------------------------------------------------


def test_drop_stray_jewels_keeps_the_allocated_one_and_drops_the_freed_one() -> None:
    pob = FakePob(allocated=(1, 2, 5))
    pob.held = {5: "raw a", 9: "raw b"}  # 9 was freed by a later step
    p = _pipeline(pob)
    p._jewels = dict(pob.held)
    p._jewel_placed = [_placed(5), _placed(9)]
    assert p._drop_stray_jewels() == [9]
    assert pob.held == {5: "raw a"} and p._jewels == {5: "raw a"} and [j.socket_id for j in p._jewel_placed] == [5]
    assert p._drop_stray_jewels() == []


def test_a_build_without_step_jewels_is_not_touched() -> None:
    pob = FakePob(allocated=(1,))
    pob.held = {9: "a request's own jewel"}
    p = _pipeline(pob)
    assert p._drop_stray_jewels() == [] and pob.held == {9: "a request's own jewel"}


def test_finish_drops_the_stray_jewel_before_anything_else() -> None:
    class Stop(Exception):
        pass

    pob = FakePob(allocated=(1,))
    pob.held = {9: "raw"}
    p = _pipeline(pob)
    p._jewels = {9: "raw"}
    p._jewel_placed = [_placed(9)]

    def boom(_keys):
        assert pob.held == {}, "the stray jewel must be gone before `_finish` measures or exports anything"
        raise Stop

    pob.stats = boom
    with pytest.raises(Stop):
        p._finish(_result(), SimpleNamespace(), time.perf_counter())


# -- the step stays only when it beats the build ------------------------------------------------------------------


def _step_with(monkeypatch: pytest.MonkeyPatch, pob: FakePob, p: BuildPipeline, *, value_with_jewel: float, value_after_lanes: float) -> BuildResult:
    jewel = _placed(5)

    def fake_step(_probe, _candidates, *, count_max):
        assert count_max == 2
        pob.value, pob.held = value_with_jewel, {5: "raw jewel"}
        return JewelStepResult(jewels=[jewel], measured=11, stopped_reason="count_max 2 reached")

    monkeypatch.setattr(pipeline_module, "run_jewel_step", fake_step)
    monkeypatch.setattr(pipeline_module, "jewel_line_candidates", lambda: ())
    p._jewel_probe = lambda *_a, **_k: object()
    p.judging.rejudge = lambda *_a, **_k: setattr(pob, "value", value_after_lanes) or p.objective
    result = _result()
    p._jewel_step(result, SimpleNamespace(keystones=[]), SimpleNamespace(), 10, 6)
    return result


def test_the_step_is_loaded_back_when_the_lanes_take_the_gain_away(monkeypatch: pytest.MonkeyPatch) -> None:
    pob = FakePob()
    p = _pipeline(pob)
    result = _step_with(monkeypatch, pob, p, value_with_jewel=150.0, value_after_lanes=90.0)
    assert pob.loaded == ["xml-0"]  # the pre-step XML
    assert p._jewels == {} and p._jewel_placed == []
    assert any(line.startswith("jewel: socket 5") for line in p.logged)
    assert any("jewels: reverted (100 -> 90)" in line for line in p.logged), p.logged
    assert result.stages[-1].name == "jewels" and "reverted" in result.stages[-1].notes


def test_the_step_stays_when_the_build_scores_above_before(monkeypatch: pytest.MonkeyPatch) -> None:
    pob = FakePob()
    p = _pipeline(pob)
    result = _step_with(monkeypatch, pob, p, value_with_jewel=150.0, value_after_lanes=140.0)
    assert pob.loaded == []
    assert p._jewels == {5: "raw jewel"} and [j.socket_id for j in p._jewel_placed] == [5]
    assert result.stages[-1].name == "jewels" and "socket 5" in result.stages[-1].notes
    assert not any("reverted" in line for line in p.logged)


def test_the_step_is_skipped_without_jewel_support_or_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline_module, "run_jewel_step", lambda *_a, **_k: pytest.fail("the step must not run"))
    bare = FakePob()
    p = _pipeline(bare)
    p.pob = SimpleNamespace(stats=bare.stats)  # a session that cannot hold jewels
    p._jewel_step(_result(), SimpleNamespace(keystones=[]), SimpleNamespace(), 10, 6)
    q = _pipeline(FakePob(), count_max=0)
    q._jewel_step(_result(), SimpleNamespace(keystones=[]), SimpleNamespace(), 10, 6)


# -- the end re-pick keeps the ledger identity ----------------------------------------------------------------------


def test_repick_writes_one_move_row_per_jewel_and_the_rows_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    pob = FakePob(value=100.0, allocated=(1, 5, 6))
    pob.held = {5: "life", 6: "life2"}
    best = {"life": 100.0, "better": 130.0}

    class Probe:
        def score(self):
            return pob.value

        def remove_jewel(self, socket):
            pob.held.pop(socket, None)

        def put_jewel(self, socket, candidate):
            pob.held[socket] = candidate.id
            pob.value = 100.0 + (best.get(candidate.id, 0.0) - 100.0 if candidate.id == "better" else 0.0)

    p = _pipeline(pob)
    p._jewel_probe = lambda *_a, **_k: Probe()
    p.judging.rejudge = lambda *_a, **_k: p.objective
    first = PlacedJewel(5, Line("life"), 90.0, 100.0, 2, ((Line("better"), 130.0), (Line("life"), 100.0)))
    second = PlacedJewel(6, Line("life2"), 100.0, 100.0, 2, ((Line("life2"), 100.0),))
    p._jewels = dict(pob.held)
    p._jewel_placed = [first, second]
    result = _result()
    p._jewel_repick(result, SimpleNamespace(keystones=[]), SimpleNamespace(), 10, 6)
    assert [m["where"] for m in result.moves] == ["jewel re-pick"] * 2
    assert set(result.moves[0]) == {"pass", "where", "move", "seconds", "before", "after", "kept", "reverted_by_judge", "violation_before", "violation_after"}
    assert result.moves[0]["kept"] is True and result.moves[0]["before"] == 100.0 and result.moves[0]["after"] == 130.0
    assert result.moves[1]["before"] == result.moves[0]["after"] and result.moves[1]["kept"] is False
    assert [j.candidate.id for j in p._jewel_placed] == ["better", "life2"]
    assert all(j.seconds > 0 for j in p._jewel_placed)
    assert any("(was 'life')" in line for line in p.logged) and any("(line kept)" in line for line in p.logged)


# -- PoB ----------------------------------------------------------------------------------------------------------------

SOCKET = 36634  # the cheapest reachable jewel socket of the Stormbrand fixture (tests/test_jewel_socket_pob.py)
KEYS = ("Life", "CombinedDPS", "TotalEHP", "Armour", "Evasion", "EnergyShield", "Mana")


def _xml_sockets(xml: str) -> dict[int, int]:
    return {int(s.get("nodeId")): int(s.get("itemId")) for s in ElementTree.fromstring(xml).iter("Socket")}


def _xml_allocated(xml: str) -> set[int]:
    nodes: set[int] = set()
    for spec in ElementTree.fromstring(xml).iter("Spec"):
        nodes |= {int(n) for n in (spec.get("nodes") or "").split(",") if n.strip().isdigit()}
    return nodes


@needs_pob
def test_short_stormbrand_build_places_a_jewel_only_when_it_beats_the_build() -> None:
    from build_from_skeleton import skeleton_from_xml
    from junkroan.optimizer.rails import Rails

    xml = decode_import_code((FIXTURES / "stormbrand.pob.txt").read_text(encoding="utf-8").strip())
    rails = Rails.load()
    one = dataclasses.replace(rails, gear=dataclasses.replace(rails.gear, jewels=dataclasses.replace(rails.gear.jewels, count_max=1)))
    lines: list[str] = []
    with PobSession(run_id="test-jewel-pipeline", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as pob:
        pob.load_xml(xml)
        skeleton = skeleton_from_xml(xml, pob=pob)
        started = time.perf_counter()
        result = BuildPipeline(pob, one, log=lines.append).run(
            skeleton, loot_n=20, gear_passes=1, gear_mode="wishlist", pick_utilities=False, tree_max_trials=60,
            loop_max_passes=1, loop_max_seconds=60.0, fixed_point_check=False)
        elapsed = time.perf_counter() - started
        held = pob.socketed_jewels()
    print(f"\nshort build: {elapsed:.0f} s")
    for line in lines:
        if "jewel" in line:
            print("  ", line)
    stage = next(s for s in result.stages if s.name == "jewels")
    # the cluster step (#433) runs before the jewels and holds its own sockets; count_max 1 binds the regular jewels only
    clusters = {socket for socket, raw in held.items() if is_cluster_jewel_raw(raw)}
    held = {socket: raw for socket, raw in held.items() if socket not in clusters}
    assert len(held) <= 1
    exported = {socket: item for socket, item in _xml_sockets(result.xml).items() if socket not in clusters}
    allocated = _xml_allocated(result.xml)
    placed = [line for line in lines if line.startswith("jewel: socket")]
    if held:
        (socket,) = held
        assert placed and f"jewel: socket {socket} " in placed[0]
        assert "reverted" not in stage.notes
        assert socket in allocated and exported.get(socket, 0) > 0
        items = {int(i.get("id")): "".join(i.itertext()) for i in ElementTree.fromstring(result.xml).iter("Item")}
        assert "Jewel" in items[exported[socket]] and "Rarity: RARE" in items[exported[socket]]
        before = result.stages[[s.name for s in result.stages].index("jewels") - 1]  # the stage the jewel step starts from
        # a jewel stays only when it beats the build under the objective's order: floors first (a smaller violation
        # wins), then the value (measured 2026-10-01: viol 0.154 -> 0.056 at 572,900 -> 519,907, the floor paid by the jewel)
        assert (-stage.violation, stage.score_value) > (-before.violation, before.score_value)
    else:
        assert not any(socket in allocated and exported.get(socket, 0) for socket in exported)  # no jewel in the export
        assert "none placed" in stage.notes or "reverted" in stage.notes
    assert not any(socket not in allocated for socket in exported if exported[socket])  # never a jewel in an unallocated socket
    assert result.ledger_identity_error is None or abs(result.ledger_identity_error) < 1e-6 * max(1.0, result.ledger_value_before_final_lanes or 1.0)


@needs_pob
def test_probe_restore_gives_the_score_back() -> None:
    from junkroan.optimizer.jewel_probe import PobJewelProbe
    from junkroan.optimizer.rails import Rails
    from junkroan.optimizer.tree_graph import TreeGraph

    xml = decode_import_code((FIXTURES / "stormbrand.pob.txt").read_text(encoding="utf-8").strip())
    objective = Objective(maximize="CombinedDPS")
    with PobSession(run_id="test-jewel-probe", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as pob:
        pob.load_xml(xml)
        used = int(pob.mutate_nodes()["points_used"])
        probe = PobJewelProbe(pob, lambda: objective, TreeGraph.load(), points=used + 4, max_depth=6)
        before = probe.score()
        snap = probe.snapshot()
        options = probe.sockets()
        assert options, "the fixture reaches a jewel socket"
        option = options[0]
        probe.allocate(option.path)
        probe.put_jewel(option.node_id, jewel_line_candidates()[0])
        with_jewel = probe.score()  # the jewel may or may not move this objective: only the way back is asserted
        probe.restore(snap)
        after = probe.score()
        assert pob.socketed_jewels() == {}
    print(f"\nprobe restore: {before} -> with jewel {with_jewel} -> {after}  (fast {probe.restore_fast}, reload {probe.restore_fallback})")
    assert after == before


@needs_pob
def test_the_seven_hybrid_lines_parse_in_pob_like_craft_rare_writes_them() -> None:
    hybrids = [c for c in jewel_line_candidates() if len(c.lines) > 1]
    assert len(hybrids) == 7
    xml = decode_import_code((FIXTURES / "stormbrand.pob.txt").read_text(encoding="utf-8").strip())
    with PobSession(run_id="test-jewel-hybrid", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as pob:
        pob.load_xml(xml)
        pob.add_nodes([SOCKET])
        for cand in hybrids:
            slot = {"prefixes": [cand.mod_id]} if cand.affix_type == "Prefix" else {"suffixes": [cand.mod_id]}
            crafted = pob.craft_rare(cand.base, ilvl=72, **slot)
            assert not crafted["problems"], (cand.mod_id, crafted["problems"])
            assert [_plain(x) for x in crafted["explicit_lines"]] == list(cand.lines), (cand.mod_id, crafted["explicit_lines"], cand.lines)
            pob.put_jewel(SOCKET, crafted["raw"])
            theirs = pob.stats(KEYS)
            pob.put_jewel(SOCKET, rare_jewel_raw(cand))
            ours = pob.stats(KEYS)
            print(f"{cand.mod_id}: {cand.lines} -> same stats {theirs == ours}")
            assert ours == theirs, cand.mod_id
            pob.remove_jewel(SOCKET)


def _plain(line: str) -> str:
    import re

    return re.sub(r"^\{[^}]*\}", "", str(line)).strip()


# -- the probe protects the request's forced nodes (#434 unit 10) ---------------------------------------------


def test_jewel_probe_protects_forced_nodes_and_keystones() -> None:
    pob = FakePob()
    pob.tree_light = lambda: {"mastery_effect_ids": []}
    p = _pipeline(pob)
    tree_full = SimpleNamespace(graph=object(), excluded_nodes=())
    forced = SimpleNamespace(keystones=[555], forced_nodes=[777])
    assert p._jewel_probe(forced, tree_full, 5, 6).protected == frozenset({555, 777})
    plain = SimpleNamespace(keystones=[555], forced_nodes=())
    assert p._jewel_probe(plain, tree_full, 5, 6).protected == frozenset({555})
