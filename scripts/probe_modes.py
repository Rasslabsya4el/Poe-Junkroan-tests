"""Show how the system reads a skill: damage modes by PoB and which ascendancies
serve each mode. Text only, nothing is built.

    python scripts/probe_modes.py "Essence Drain"
    python scripts/probe_modes.py "Lightning Arrow" --ascendancies Deadeye,Pathfinder,Assassin
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from junkroan.optimizer.rails import Rails  # noqa: E402
from junkroan.pob.session import PobSession  # noqa: E402
from junkroan.search.modes import probe_skill  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("skill")
    ap.add_argument("--ascendancies", help="comma-separated ascendancy ids (default: all)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    ids = [a.strip() for a in args.ascendancies.split(",")] if args.ascendancies else None
    with PobSession(run_id="probe-modes") as pob:
        report = probe_skill(pob, args.skill, Rails.load(), ascendancy_ids=ids, log=print if args.verbose else None)
    print(report.text())
    out = Path(__file__).resolve().parents[1] / "artifacts" / "modes"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.skill.lower().replace(' ', '_')}.md").write_text(report.text() + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
