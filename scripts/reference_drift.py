"""Is a reference build's concept still alive under the pinned PoB? Every fixture XML carries the
numbers the author's own PoB computed when the build was exported (PlayerStat); our pinned PoB
recomputes the same build under the current game data (tests/fixtures/<set>/stats.json, from
scripts/fixture_stats.py). A reference from an older league whose recomputed number fell far
below the saved one was reworked or nerfed in between and is flagged: read it in PoB before
using it as a benchmark. No PoB needed.

    python scripts/reference_drift.py [tuadh_329] [--flag 0.7]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from junkroan.pob.session import decode_import_code  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from build_from_skeleton import skeleton_from_xml  # noqa: E402
from junkroan.optimizer.objective_select import objective_for  # noqa: E402
from junkroan.optimizer.rails import Rails  # noqa: E402


def saved_stats(xml_text: str) -> tuple[str, dict[str, float]]:
    root = ET.fromstring(xml_text)
    versions = [s.get("treeVersion") or "?" for s in root.find("Tree").iter("Spec")] if root.find("Tree") is not None else []
    stats = {}
    build = root.find("Build")
    for ps in (build.iter("PlayerStat") if build is not None else []):
        try:
            stats[ps.get("stat")] = float(ps.get("value"))
        except (TypeError, ValueError):
            pass
    return (versions[0] if versions else "?"), stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("set", nargs="?", default="tuadh_329")
    ap.add_argument("--flag", type=float, default=0.7, help="flag a reference whose recomputed number is below this share of the saved one")
    args = ap.parse_args()
    folder = ROOT / "tests" / "fixtures" / args.set
    ours = {r["slug"]: r for r in json.loads((folder / "stats.json").read_text(encoding="utf-8"))}
    rails = Rails.load()
    print(f"| reference | tree | saved by the author | under the pinned PoB | ratio | life saved / ours | flag |")
    print("|---|---|---|---|---|---|---|")
    flagged = 0
    for path in sorted(folder.glob("*.pob.txt")):
        slug = path.name[: -len(".pob.txt")]
        xml = decode_import_code(path.read_text(encoding="utf-8").strip())
        version, saved = saved_stats(xml)
        rec = ours.get(slug)
        key = objective_for(rails, skeleton_from_xml(xml).main_link[0]).maximize  # FullDPS for minion builds (D37)
        then = saved.get(key) or 0.0
        now = float((rec or {}).get(key) or 0.0)
        ratio = now / then if then else float("nan")
        flag = ""
        if rec is None:
            flag = "no stats.json row: run scripts/fixture_stats.py"
        elif then and ratio < args.flag:
            flag = "reworked or nerfed since: read it in PoB"
            flagged += 1
        print(f"| {slug} | {version} | {then:,.0f} {key} | {now:,.0f} | {ratio:.2f} | {saved.get('Life', 0):,.0f} / {float((rec or {}).get('Life') or 0):,.0f} | {flag} |")
    print(f"\n{flagged} flagged below {args.flag:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
