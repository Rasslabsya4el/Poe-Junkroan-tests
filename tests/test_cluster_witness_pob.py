"""#433 unit 8: the witness for the cluster rule (kind A): the allowed option is the known-best move and selection keeps it.

Build: the Zizaran Trickster "blight of contagion" fixture (level 97). Its author's Large Cluster (L10) in socket 32763
is removed (`remove_jewel`; its inner nodes >= 65536 go with it), then `run_cluster_step` runs through a real
`PobJewelProbe` on the build, `max_passive_points` of the fixture's own level. Unit 3 measured a generated Large-12 at
that socket paying (CombinedDPS 1,099,247 -> 1,371,538), so a paying cluster exists; the step must find one, pay its
points by removing leaves, and keep it.

Narrowed here against the pipeline's rails: `count_max` 1 (one round) and `screen_keep` 2 (two screened options get the
notable trials), to keep the run under ~5 min. Everything else is the pipeline's call: both sizes, every enchant of
`cluster_enchants`, `notables_max` 2, item level 72, the sockets the probe offers, socket sizes from the tree graph.
"""

from __future__ import annotations

import re
import time

from junkroan.optimizer.cluster_lines import DAY1_PASSIVES, ClusterCandidate, cluster_enchants, cluster_notables
from junkroan.optimizer.cluster_step import run_cluster_step
from junkroan.optimizer.jewel_probe import PobJewelProbe
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import max_passive_points
from junkroan.optimizer.tree_graph import TreeGraph
from junkroan.pob.session import PobSession, decode_import_code
from junkroan.report_format import human_duration
from tests.test_cluster_pob import FIXTURE, PROJECT_ROOT, SOCKET, needs_pob

ITEM_LEVEL = 72
INNER = 65536


@needs_pob
def test_the_step_places_a_paying_cluster_on_the_trickster_without_its_own() -> None:
    xml = decode_import_code(FIXTURE.read_text(encoding="utf-8").strip())
    level = int(re.search(r'<Build level="(\d+)"', xml).group(1))
    graph = TreeGraph.load()
    objective = Objective(maximize="CombinedDPS")
    with PobSession(run_id="test-cluster-witness", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as pob:
        pob.load_xml(xml)
        assert SOCKET in pob.socketed_jewels()
        pob.remove_jewel(SOCKET)
        state = pob.read_state()["tree_state"]
        assert not state.get("cluster_jewel_items"), state.get("cluster_jewel_items")
        assert not [n for n in state["user_allocated_node_ids"] if int(n) >= INNER]

        probe = PobJewelProbe(pob, lambda: objective, graph, points=max_passive_points(level), item_level=ITEM_LEVEL)
        # what hung only on the author's cluster (a node PoB leaves allocated, now cut off from the class start) goes with it
        allocated = probe.allocated()
        orphans = sorted(allocated - graph._connected_from(graph.roots(allocated), allocated))
        print(f"\nnodes cut off by removing the author's cluster: {orphans}")
        if orphans:
            pob.remove_nodes(orphans)
        assert not sorted(probe.allocated() - graph._connected_from(graph.roots(probe.allocated()), probe.allocated()))
        enchants = {size: cluster_enchants(size) for size in ("large", "medium")}

        def notables_for(enchant, size):
            return [n.name for n in cluster_notables(enchant, ITEM_LEVEL)]

        def make_candidate(size, enchant, names):
            return ClusterCandidate(size, enchant, tuple(names), DAY1_PASSIVES[size])

        def socket_size(node_id):
            node = graph.node(node_id)
            return None if node is None else node.expansion_size

        started = time.perf_counter()
        step = run_cluster_step(probe, enchants, notables_for, make_candidate, count_max=1, notables_max=2,
                                screen_keep=2, socket_size=socket_size)
        wall = time.perf_counter() - started

        print(f"\nlevel {level}, points {probe.points}, stop: {step.stopped_reason}")
        for p in step.placed:
            c = p.candidate
            print(f"cluster: socket {p.socket_id} size {c.size} enchant {c.enchant.id} notables {c.notables} "
                  f"score {p.score_before:,.0f} -> {p.score_after:,.0f}, removed leaves {len(p.removed_leaves)}")
        print(f"Score {step.score_before:,.0f} -> {step.score_after:,.0f}, {step.trials} trials, wall {human_duration(wall)}")

        assert step.placed, step.stopped_reason
        assert any(graph.node(p.socket_id).expansion_size == 2 and p.score_after > p.score_before for p in step.placed)
        assert probe.points_over() <= 0
        held = {e["node_id"] for e in pob.read_state()["tree_state"]["cluster_jewel_items"]}
        assert {p.socket_id for p in step.placed} <= held
