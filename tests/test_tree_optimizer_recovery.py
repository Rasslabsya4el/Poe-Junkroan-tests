"""Phase 2 acceptance: the tree optimizer recovers stripped points on reference builds.

For each selected reference build: remove ~N points as whole branches, then let
the optimizer re-spend the same number of points maximizing CombinedDPS under
Life / EHP / resist floors at the original values. Pass = recovered DPS within
the tolerance of the original. Slow (minutes); skipped without the PoB runtime.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from junkroan.optimizer.objective import Objective  # noqa: E402
from junkroan.optimizer.tree_graph import TreeGraph, parse_allocated_from_xml  # noqa: E402
from junkroan.optimizer.tree_optimizer import TreeOptimizer  # noqa: E402
from junkroan.pob.session import PobSession, decode_import_code  # noqa: E402
from recover_tree import KEYS, strip_branches  # noqa: E402

FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]

pytestmark = [pytest.mark.pob, pytest.mark.skipif(
    not (RUNTIME_ROOT / "lua51.dll").is_file(),
    reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}",
)]

# (slug, points to strip, minimum recovered fraction of original CombinedDPS)
CASES = [
    ("stormbrand", 30, 0.95),
    ("poison_spectral_throw", 30, 0.95),
    # cold_dot measured 92.4 % since 1db3fed (2026-09-12, D31: one effect per mastery, #496 bisect):
    # the old >= 95 % took Cold Mastery effect 33129 on three masteries at once (112.4 % with the
    # filter off, probe j-20261002-1642-08c8), which the game forbids.
    ("cold_dot", 30, 0.92),
]


@pytest.mark.slow
@pytest.mark.parametrize("slug,points,min_ratio", CASES)
def test_optimizer_recovers_stripped_points(slug: str, points: int, min_ratio: float, tmp_path: Path) -> None:
    code = (FIXTURES / f"{slug}.pob.txt").read_text(encoding="utf-8").strip()
    xml = decode_import_code(code)
    graph = TreeGraph.load()
    original_nodes = set(parse_allocated_from_xml(xml))

    with PobSession(run_id=f"test-recover-{slug}", artifacts_root=tmp_path) as pob:
        pob.load_xml(xml)
        original = pob.stats(KEYS)
        remaining, _groups = strip_branches(graph, original_nodes, points, seed=1)
        removed = pob.mutate_nodes(remove=sorted(original_nodes - remaining))["removed_node_ids"]
        assert len(removed) >= points - 2

        objective = Objective(
            maximize="CombinedDPS",
            floors={"Life": original["Life"] * 0.97, "TotalEHP": original["TotalEHP"] * 0.95},
        )
        opt = TreeOptimizer(pob, objective, graph=graph, max_depth=6)
        result = opt.allocate(len(removed), allocated=original_nodes - set(removed))
        final = pob.stats(KEYS)

    ratio = final["CombinedDPS"] / original["CombinedDPS"]
    assert result.final_score is not None and result.final_score.feasible, result.summary()
    assert ratio >= min_ratio, f"{slug}: recovered {ratio:.1%} of original DPS\n{result.summary()}"
