"""Tree-leaf findings and reader table formatting without a PoB runtime."""

from types import SimpleNamespace

from junkroan.optimizer import tree_hygiene
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.tree_hygiene import TreeLeaf, _check_config_proof, _xml_with_mastery_effect, audit_findings, render_tree_leaf_table


def test_tree_leaf_audit_and_reader_table_name_dead_weak_and_proof_nodes() -> None:
    rows = [
        TreeLeaf(1, "Minion Life", "normal", (), status="dead"),
        TreeLeaf(2, "Thin Damage", "normal", (), changes={"CombinedDPS": -0.001, "Life": -0.002}, judged_change=-0.001, status="weak"),
        TreeLeaf(3, "Caster Mastery", "mastery", (), status="proof", proof_inputs=("usePowerCharges",)),
    ]
    objective = Objective(maximize="CombinedDPS")

    findings = audit_findings(rows, objective=objective)
    table = render_tree_leaf_table(rows, objective=objective)

    assert findings[0] == ("error", "Minion Life (node 1) moves none of the objective or floor stats when removed")
    assert findings[1][0] == "warning" and "Thin Damage" in findings[1][1]
    assert "PoB's node tooltip can show a smaller FullDPS percentage" in table
    assert "holds the proof of usePowerCharges" in table


def test_mastery_effect_xml_swap_replaces_only_the_selected_effect() -> None:
    xml = '<Spec masteryEffects="{10,20},{30,40}"/>'
    assert _xml_with_mastery_effect(xml, 10, 20, 50) == '<Spec masteryEffects="{10,50},{30,40}"/>'


class _LeafPob:
    """Only the surfaces `_check_config_proof` touches, in call order, no PoB.

    `stats` answers in the order the check asks: the frozen removal first, the
    post-re-derive build second. `cascade` drops one more allocated node, the way
    PoB's own removal takes a bridge node's neighbours with it.
    """

    def __init__(self, stats_sequence: list[dict], *, cascade: int | None = None) -> None:
        self.allocated = {1, 2, 3}
        self.cascade = cascade
        self._stats = list(stats_sequence)
        self._snapshots: dict[str, set[int]] = {}

    def config_inputs(self) -> dict:
        return {"usePowerCharges": True}

    def tree_light(self) -> dict:
        return {"class_id": "Witch", "user_allocated_node_ids": sorted(self.allocated)}

    def mutate_nodes(self, add=None, remove=None, mastery_effects=None) -> dict:
        for node_id in remove or ():
            self.allocated.discard(int(node_id))
        if self.cascade is not None:
            self.allocated.discard(self.cascade)
        return {"removed_node_ids": [int(n) for n in remove or ()]}

    def stats(self, keys) -> dict:
        return dict(self._stats.pop(0))

    def export_xml(self) -> str:
        token = f"snap{len(self._snapshots) + 1}"
        self._snapshots[token] = set(self.allocated)
        return token

    def load_xml(self, token: str) -> None:
        self.allocated = set(self._snapshots[token])


def _derived(*, conservative: dict, optimistic: dict | None = None, custom: tuple = ()) -> SimpleNamespace:
    return SimpleNamespace(
        conservative=SimpleNamespace(inputs=conservative),
        optimistic=SimpleNamespace(inputs=optimistic if optimistic is not None else {}),
        custom_mods=custom,
    )


def test_dead_node_check_demotes_to_travel_live_or_proof_and_keeps_a_real_dead(monkeypatch) -> None:
    monkeypatch.setattr(tree_hygiene, "write_lanes_preserving_numbers", lambda pob, derived: None)
    before_lane = tree_hygiene._lane_fingerprint(_derived(conservative={"usePowerCharges": True}))
    keys = ("CombinedDPS",)
    base = {"CombinedDPS": 1000.0}

    def judge(stats_sequence: list[dict], *, cascade: int | None = None, derived=None):
        monkeypatch.setattr(tree_hygiene, "_derive_config",
                            lambda pob: derived if derived is not None else _derived(conservative={"usePowerCharges": True}))
        row = TreeLeaf(9, "Minion Life", "normal", (), status="dead")
        _check_config_proof(_LeafPob(stats_sequence, cascade=cascade), row, base, keys, None, before_lane=before_lane)
        return row

    travel = judge([{"CombinedDPS": 900.0}, {"CombinedDPS": 900.0}], cascade=3)
    assert travel.status == "travel" and "disconnects 1 allocated node(s): 3" in travel.reason

    live = judge([{"CombinedDPS": 900.0}, {"CombinedDPS": 900.0}])
    assert live.status == "live"

    proof = judge([{"CombinedDPS": 1000.0}, {"CombinedDPS": 900.0}], derived=_derived(conservative={"usePowerCharges": False}))
    assert proof.status == "proof" and proof.proof_inputs == ("re-derived lane",)

    dead = judge([{"CombinedDPS": 1000.0}, {"CombinedDPS": 1000.0}])
    assert dead.status == "dead"
