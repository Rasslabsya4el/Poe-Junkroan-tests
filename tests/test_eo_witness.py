"""The headless wrapper publishes `HaveElementalOverload` after every `calcs.perform`, so the
objective's Elemental Overload floor (`keystone_floors.eo_uptime_stat`) sees the keystone in a
real readback and in the what-if trial that allocates or drops it."""

from __future__ import annotations

import glob
import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")
EO_NODE = 22088


def _fixture(slug: str) -> str:
    path = next(iter(glob.glob(str(PROJECT_ROOT / "tests" / "fixtures" / "**" / f"{slug}.pob.txt"), recursive=True)))
    return Path(path).read_text(encoding="utf-8").strip()


@pytest.mark.pob
@needs_pob
def test_the_keystone_witness_follows_the_tree_in_real_and_what_if_readbacks(tmp_path: Path) -> None:
    from junkroan.optimizer.keystone_floors import EO_WITNESS, elemental_overload_uptime
    from junkroan.optimizer.objective_select import objective_for
    from junkroan.optimizer.rails import Rails
    from junkroan.pob.session import PobSession

    with PobSession(run_id="test-eo-witness", artifacts_root=tmp_path) as pob:
        # the author's Burning Arrow (the reading's case): the keystone on 10.6% effective crit at 0.97 hits/s
        pob.load_import_code(_fixture("burning_arrow_snipe"))
        stats = pob.stats([EO_WITNESS, "CritChance", "Speed", "HitSpeed"])
        assert stats[EO_WITNESS] == 1 and 0.5 < elemental_overload_uptime(stats) < 0.7
        objective = objective_for(Rails.load(), "Burning Arrow")
        assert EO_WITNESS in objective.stat_keys
        assert objective.violations(pob.stats(objective.stat_keys)).get("ElementalOverloadUptime", 0.0) > 0.2  # the floor sees it
        trial = pob.trial_stats([{"remove": [EO_NODE]}], [EO_WITNESS, "CritChance"], mode="fast")[0]
        assert trial["ok"] and trial["stats"][EO_WITNESS] == 0 and EO_NODE in trial["removed_node_ids"]
        assert pob.stats([EO_WITNESS])[EO_WITNESS] == 1  # the build itself is untouched

        # Storm Brand at 99% crit and 7 hits/s: without the keystone the stat is neutral, with it the uptime is 100%
        pob.load_import_code(_fixture("stormbrand"))
        assert pob.stats([EO_WITNESS])[EO_WITNESS] == 0
        trial = pob.trial_stats([{"add": [EO_NODE]}], [EO_WITNESS, "CritChance", "Speed", "HitSpeed"], mode="fast")[0]
        assert trial["ok"] and trial["stats"][EO_WITNESS] == 1 and elemental_overload_uptime(trial["stats"]) > 0.999
