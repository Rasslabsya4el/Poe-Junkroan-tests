"""#1157 unit 1: the audit measures every allocated ascendancy node and flags a dead one.

The PoB-free half uses a fake session: the 0.1 % rule on both the objective and TotalEHP, and the
points-spent condition. The `pob` half decodes the two saved builds of the owner's reading (A1 Contagion,
B1 Searing Bond) and checks that the audit flags Unhallowed Rite and Instruments of Virtue.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from junkroan.optimizer.audit import audit_dead_tree_nodes
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.tree_graph import TreeGraph
from junkroan.optimizer.tree_hygiene import ascendancy_node_names, ascendancy_removals, dead_ascendancy_nodes

PROJECT_ROOT = Path(__file__).resolve().parents[1]
A1 = PROJECT_ROOT / "artifacts" / "search-contagion" / "20261015-0336" / "01 witch_occultist_no_iron_will_prophecy_wand.pob.txt"
B1 = PROJECT_ROOT / "artifacts" / "search-searing_bond" / "20261015-0004" / "01 templar_inquisitor_demon_dagger.pob.txt"
OBJECTIVE = Objective(maximize="TotalDotDPS")
BASE = {"TotalDotDPS": 1000.0, "CombinedDPS": 1000.0, "TotalEHP": 5000.0}


def _asc_ids(count: int) -> list[int]:
    ids = sorted(ascendancy_node_names())
    assert len(ids) >= count
    return ids[:count]


class _AscPob:
    """`tree_light`, `stats` and `trial_stats` only. `removals[node] = (objective change, TotalEHP change)`,
    as fractions; a passive node is allocated too, to show it is never measured here."""

    def __init__(self, allocated: list[int], removals: dict[int, tuple[float, float]]) -> None:
        self.allocated = list(allocated)
        self.removals = removals
        self.trial_calls: list[tuple[list, tuple, str]] = []

    def tree_light(self) -> dict:
        return {"class_id": "Witch", "user_allocated_node_ids": sorted(self.allocated)}

    def stats(self, keys) -> dict:
        return {k: BASE[k] for k in keys if k in BASE}

    def trial_stats(self, trials, keys, *, mode="full") -> list[dict]:
        self.trial_calls.append((list(trials), tuple(keys), mode))
        out = []
        for trial in trials:
            node = int(trial["remove"][0])
            obj, ehp = self.removals[node]
            stats = {**BASE, "TotalDotDPS": BASE["TotalDotDPS"] * (1 + obj), "TotalEHP": BASE["TotalEHP"] * (1 + ehp)}
            out.append({"ok": True, "error": None, "removed_node_ids": [node], "stats": stats})
        return out


def test_the_zero_point_one_percent_rule_needs_both_stats_under_it() -> None:
    a, b, c, d = _asc_ids(4)
    pob = _AscPob([a, b, c, d], {
        a: (0.0, 0.0),        # dead: nothing moves
        b: (0.005, 0.0),      # 0.5 % of the objective: live
        c: (0.0, 0.002),      # 0.2 % TotalEHP alone: live
        d: (0.0004, -0.0009), # under 0.1 % on both: dead
    })
    rows = dead_ascendancy_nodes(pob, objective=OBJECTIVE, points_budget=4)
    assert [r.node_id for r in rows] == [a, d]
    assert rows[1].judged_stat == "TotalDotDPS"
    assert rows[1].judged_change == pytest.approx(0.0004)
    assert rows[1].ehp_change == pytest.approx(-0.0009)


def test_dead_nodes_are_listed_only_once_the_ascendancy_points_are_spent() -> None:
    a, b, c, d = _asc_ids(4)
    removals = {a: (0.0, 0.0), b: (0.1, 0.1), c: (0.0, 0.0), d: (0.0, 0.0)}
    pob = _AscPob([a, b, c, d], removals)
    assert dead_ascendancy_nodes(pob, objective=OBJECTIVE, points_budget=8) == []  # 4 of 8 points spent: no finding
    assert dead_ascendancy_nodes(pob, objective=OBJECTIVE, points_budget=4) != []


def test_only_allocated_ascendancy_nodes_are_trialled_and_all_of_them_get_a_removal_value() -> None:
    graph = TreeGraph.load()
    a, b = _asc_ids(2)
    passive = next(n for n in sorted(graph.allocatable) if graph.node(n) is not None and graph.node(n).kind == "normal")
    pob = _AscPob([a, b, passive], {a: (0.0, 0.0), b: (0.3, 0.0)})
    rows = ascendancy_removals(pob, objective=OBJECTIVE)
    assert [r.node_id for r in rows] == [a, b]
    assert [r.judged_change for r in rows] == [0.0, pytest.approx(0.3)]
    trialled = [t["remove"] for call in pob.trial_calls for t in call[0]]
    assert trialled == [[a], [b]]
    assert all(call[2] == "full" for call in pob.trial_calls)  # a real removal: PoB cascades the dependants


def test_the_audit_reports_a_dead_ascendancy_node_as_its_own_finding_kind() -> None:
    a, b, c, d = _asc_ids(4)
    pob = _AscPob([a, b, c, d], {a: (0.0, 0.0), b: (0.2, 0.2), c: (0.2, 0.2), d: (0.2, 0.2)})
    findings = audit_dead_tree_nodes(pob, OBJECTIVE, rows=[], points_budget=4)
    dead = [f for f in findings if f.check == "dead ascendancy node"]
    assert len(dead) == 1 and f"node {a}" in dead[0].detail
    assert dead[0].severity == "warning"  # an error would drop the row from the benchmark medians (#1157 review)


def test_the_audit_takes_its_budget_from_the_caller_never_from_the_default_rails() -> None:
    a, b, c, d = _asc_ids(4)
    pob = _AscPob([a, b, c, d], {a: (0.0, 0.0), b: (0.2, 0.2), c: (0.2, 0.2), d: (0.2, 0.2)})
    with pytest.raises(TypeError):
        audit_dead_tree_nodes(pob, OBJECTIVE, rows=[])  # no budget given: refused, not read from Rails.load()
    assert pob.trial_calls == []


def test_below_the_budget_the_audit_never_runs_the_ascendancy_trials() -> None:
    a, b, c, d = _asc_ids(4)
    pob = _AscPob([a, b, c, d], {a: (0.0, 0.0), b: (0.0, 0.0), c: (0.0, 0.0), d: (0.0, 0.0)})
    assert audit_dead_tree_nodes(pob, OBJECTIVE, rows=[], points_budget=8) == []
    assert pob.trial_calls == []  # 4 of 8 points spent: the ~8 full removals are not run at all


def test_the_finding_text_takes_its_share_from_the_constant(monkeypatch) -> None:
    from junkroan.optimizer import tree_hygiene

    monkeypatch.setattr(tree_hygiene, "DEAD_ASCENDANCY_SHARE", 0.005)
    a, b, c, d = _asc_ids(4)
    pob = _AscPob([a, b, c, d], {a: (0.002, 0.0), b: (0.2, 0.2), c: (0.2, 0.2), d: (0.2, 0.2)})
    dead = [f for f in audit_dead_tree_nodes(pob, OBJECTIVE, rows=[], points_budget=4) if f.check == "dead ascendancy node"]
    assert len(dead) == 1 and "0.5%" in dead[0].detail and "0.1%" not in dead[0].detail


@pytest.mark.pob
def test_the_audit_flags_unhallowed_rite_on_A1_and_instruments_of_virtue_on_B1() -> None:
    from junkroan.pob.session import PobSession, decode_import_code

    named = {name: node_id for node_id, name in ascendancy_node_names().items()}
    with PobSession(run_id="issue1157-asc-audit") as pob:
        pob.load_xml(decode_import_code(A1.read_text(encoding="utf-8").strip()))
        rows_a1 = ascendancy_removals(pob, objective=OBJECTIVE)
        dead_a1 = dead_ascendancy_nodes(pob, objective=OBJECTIVE, points_budget=8)
        pob.load_xml(decode_import_code(B1.read_text(encoding="utf-8").strip()))
        rows_b1 = ascendancy_removals(pob, objective=OBJECTIVE)
        dead_b1 = dead_ascendancy_nodes(pob, objective=OBJECTIVE, points_budget=8)
    print("\nA1 removals:", [(r.name, f"{r.judged_change:+.4%}", f"{r.ehp_change:+.4%}") for r in rows_a1])
    print("B1 removals:", [(r.name, f"{r.judged_change:+.4%}", f"{r.ehp_change:+.4%}") for r in rows_b1])
    assert named["Unhallowed Rite"] in {r.node_id for r in dead_a1}
    assert named["Instruments of Virtue"] in {r.node_id for r in dead_b1}
