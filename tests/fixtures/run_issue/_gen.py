"""Regenerates the two small fixture runs (6 references x 3 seeds)."""

import json
from pathlib import Path

HERE = Path(__file__).parent
SLUGS = ["arc_archmage", "bow_poison", "fireball_ignite", "cyclone_slayer", "spark_inquis", "ba_raider"]


def make(name: str, delta: float) -> None:
    rows = [
        {"ok": True, "slug": s, "seed": sd, "gear_mode": "loot", "variant": "", "ratio_lane": round(0.90 + 0.05 * i + 0.01 * (sd - 7) + delta, 4),
         "audit": [], "audit_errors": 0}
        for i, s in enumerate(SLUGS) for sd in (7, 8, 9)
    ]
    d = HERE / name
    d.mkdir(exist_ok=True)
    (d / "results.json").write_text(json.dumps({"rows": rows}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    make("20261001-0100-filler-smoke-loot-s7", 0.0)
    make("20260930-0100-filler-smoke-loot-s7", -0.02)
    make("20260929-0100-filler-smoke-loot-s7", -0.10)
