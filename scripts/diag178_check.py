"""#178: an import-only check that the probe's hooks exist on the pinned code (no PobSession)."""
from __future__ import annotations

import inspect
import os
import sys

ROOT = os.path.abspath(os.getcwd())
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "src"))

from junkroan.optimizer import judging as jd  # noqa: E402
from junkroan.optimizer import pipeline as pl  # noqa: E402
from junkroan.optimizer import wishlist_gear as wg  # noqa: E402
from junkroan.pob.session import PobSession  # noqa: E402

print("root", ROOT)
print("TreeOptimizer.allocate", bool(pl.TreeOptimizer.allocate))
for m in ("set_config", "load_xml", "set_items", "equip", "set_tree", "set_skills", "set_identity",
          "mutate_nodes", "config_inputs", "export_xml", "trial_stats", "stats"):
    print(" ", m, hasattr(PobSession, m))
print("fill_slot", inspect.signature(wg.WishlistGear.fill_slot))
print("_keep_incumbent", inspect.signature(wg.WishlistGear._keep_incumbent))
print("_record", inspect.signature(pl.BuildPipeline._record))
print("Judging.rejudge", inspect.signature(jd.Judging.rejudge))
print("PobLanes.write", inspect.signature(jd.PobLanes.write))
print("read_lanes", inspect.signature(jd.read_lanes))
print("write_lanes", inspect.signature(jd.write_lanes))
print("apply_custom_mods / caps in judging ns", hasattr(jd, "apply_custom_mods"), hasattr(jd, "apply_ailment_stack_caps"))
print("allocate", inspect.signature(pl.TreeOptimizer.allocate))
import benchmark  # noqa: E402

print("benchmark.run_one", bool(benchmark.run_one))
