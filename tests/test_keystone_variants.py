"""Forbidden keystones (D40): never allocated, never pathed through."""

from junkroan.optimizer.objective import Objective
from junkroan.optimizer.tree_graph import Candidate, TreeGraph
from junkroan.optimizer.tree_optimizer import TreeOptimizer


class _FakePob:
    def read_state(self) -> dict:
        return {"tree_state": {"mastery_effect_ids": []}}


def test_forbid_removes_the_keystone_and_paths_through_it() -> None:
    graph = TreeGraph.load()
    opt = TreeOptimizer(_FakePob(), Objective(maximize="CombinedDPS"), graph=graph)
    ids = opt.forbid(["Blood Magic"])
    bm = next(n for n in graph.nodes.values() if n.name == "Blood Magic" and n.kind == "keystone")
    assert bm.node_id in ids
    other = next(n for n in graph.nodes.values() if n.kind == "notable")
    direct = Candidate(node_id=bm.node_id, name=bm.name, kind="keystone", cost=1, path=(bm.node_id,))
    through = Candidate(node_id=other.node_id, name=other.name, kind="notable", cost=2, path=(bm.node_id, other.node_id))
    clean = Candidate(node_id=other.node_id, name=other.name, kind="notable", cost=1, path=(other.node_id,))
    kept = [t["candidate"].node_id for t in opt._trials_for([direct, through, clean])]
    assert kept == [other.node_id]
    assert opt.forbid([]) == set() and opt.forbid(["No Such Keystone"]) == set()


def test_weapon_alternatives_round_trip_and_default() -> None:
    from junkroan.search.skeleton import Skeleton

    sk = Skeleton(class_name="Shadow", ascendancy="Trickster", rare_bases={"Weapon 1": "Midnight Blade", "Weapon 2": "Supreme Spiked Shield"},
                  weapon_alternatives=[{"Weapon 1": "Terror Claw", "Weapon 2": "Supreme Spiked Shield"}, {"Weapon 1": "Demon Dagger"}])
    back = Skeleton.from_json(sk.to_json())
    assert back.weapon_alternatives == sk.weapon_alternatives
    assert Skeleton.from_json('{"class_name": "Shadow", "ascendancy": "Trickster"}').weapon_alternatives == []
