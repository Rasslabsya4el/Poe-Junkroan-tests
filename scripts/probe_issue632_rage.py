"""Issue #632 probe: what node 55420 (Rage on Hit) is worth with its Rage, ours (smite-s4) and the author's.

    python scripts/probe_issue632_rage.py

One PobSession. Prints a table of CombinedDPS by config `multiplierRage`, with and without the node.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from junkroan.pob.session import PobSession, decode_import_code  # noqa: E402
from junkroan.report_format import human_duration  # noqa: E402

NODE = 55420
GATE = ROOT / "artifacts" / "benchmark" / "20261005-1220-gate-20261005"
RAGE = (0, 5, 12, 30)


def dps(pob: PobSession, rage: int, extra: tuple[str, ...] = ()) -> dict:
    pob.set_config(inputs={"multiplierRage": rage})
    return pob.stats(["CombinedDPS", *extra])


def main() -> int:
    t0 = time.monotonic()
    with PobSession(run_id="probe-issue632") as pob:
        # (a) ours
        pob.load_import_code((GATE / "smite-s4.pob.txt").read_text(encoding="utf-8").strip())
        own = pob.config_inputs()
        base = pob.stats(["CombinedDPS", "Speed"])
        print(f"(a) ours, build as is (config inputs: multiplierRage={own.get('multiplierRage')}): CombinedDPS {base['CombinedDPS']:,.2f}  Speed {base['Speed']}  (expected 737,408.39 / 5.0358)")
        before = set(pob.tree_light()["user_allocated_node_ids"])
        print(f"    allocated before: {len(before)}; node {NODE} allocated: {NODE in before}")
        without = {r: dps(pob, r)["CombinedDPS"] for r in RAGE}
        res = pob.add_nodes([NODE])
        after = set(pob.tree_light()["user_allocated_node_ids"])
        path = sorted(after - before)
        print(f"    path added (node ids): {path}; point cost {len(path)}; add_nodes keys: {sorted(res)}")
        with_ = {}
        for r in RAGE:
            with_[r] = dps(pob, r, ("MaximumRage",))
        print("    rage  without-node      with-node       delta        delta%   MaximumRage(with)")
        for r in RAGE:
            w, n = without[r], with_[r]["CombinedDPS"]
            print(f"    {r:>4}  {w:>14,.0f}  {n:>14,.0f}  {n - w:>+11,.0f}  {100 * (n / w - 1):>+6.2f}%   {with_[r].get('MaximumRage')}")

        # (b) author
        art = json.loads((GATE / "author" / "smite-flasks-active.json").read_text(encoding="utf-8"))
        pob.load_xml(art["state_xml"])
        ids = set(pob.tree_light()["user_allocated_node_ids"])
        print(f"(b) author: {len(ids)} nodes, allocates {NODE}: {NODE in ids}, config multiplierRage={pob.config_inputs().get('multiplierRage')}")
        with_a = dps(pob, 30, ("MaximumRage",))
        res = pob.remove_nodes([NODE])
        left = set(pob.tree_light()["user_allocated_node_ids"])
        lost = sorted(ids - left - {NODE})
        a_without = dps(pob, 30, ("MaximumRage",))
        print(f"    removal cascaded other nodes: {lost if lost else 'none (rest still connected)'}")
        print("    multiplierRage 30   with-node      without-node    delta")
        print(f"                       {with_a['CombinedDPS']:>14,.0f}  {a_without['CombinedDPS']:>14,.0f}  {with_a['CombinedDPS'] - a_without['CombinedDPS']:>+11,.0f}  (MaximumRage with {with_a.get('MaximumRage')}, without {a_without.get('MaximumRage')})")
    print(f"took {human_duration(time.monotonic() - t0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
