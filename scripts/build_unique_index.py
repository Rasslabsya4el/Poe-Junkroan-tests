"""Build the uniques corpus from the running PoB: every unique with its base, slot
type, level requirement, mod lines and PoB-parsed structured mods (stat name,
type, value, flags, tags such as PerStat / Condition / Multiplier).

Out: src/junkroan/pob/corpus_data/uniques.json
Run: python scripts/build_unique_index.py
"""

from __future__ import annotations

import json
import sys
import time
import re
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from junkroan.pob.session import PobSession  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "src" / "junkroan" / "pob" / "corpus_data" / "uniques.json"

# PoB's own "Source:" line, classified. No source line = a regular world drop.
AVAILABILITY_RULES = (
    ("legacy", r"no longer obtainable"),
    ("boss_uber", r"\(uber"),
    ("upgrade", r"upgraded from|blessing of|vial of|use currency\{vaal orb\}|prophecy|fated"),
    ("vendor", r"vendor recipe"),
    ("mechanic", r"grand heist|blighted|delirium|ritual|labyrinth|breach|opening |incursion|temple|sanctum|ultimatum|expedition|legion|harbinger|synthesis|delve|azurite|betrayal|syndicate|abyss|beyond|kalandra|affliction|necropolis|settlers|mercenar|simulacrum|maven|scourge|crucible|tota|ancestor"),
    ("boss", r"drops from"),
)


TIERS_PATH = OUT.with_name("unique_tiers.json")


def wiki_tiers() -> tuple[dict, set[str]]:
    """Community drop-rate tiers (T0 rarest .. T5 most common) and drop_enabled from the
    wiki, fetched through a browser (the wiki blocks bots): corpus_data/unique_tiers.json."""

    if not TIERS_PATH.is_file():
        return {}, set()
    raw = json.loads(TIERS_PATH.read_text(encoding="utf-8"))
    return raw.get("tiers", {}), set(raw.get("drop_disabled", []))


def classify_source(source: str | None) -> str:
    if not source:
        return "core"
    text = source.lower()
    for label, pattern in AVAILABILITY_RULES:
        if re.search(pattern, text):
            return label
    return "other"


def main() -> int:
    t0 = time.perf_counter()
    with PobSession(run_id="unique-index") as pob:
        rows = pob.list_uniques()
        print(f"{len(rows)} uniques from PoB in {time.perf_counter() - t0:.1f}s")
        # parse every distinct line once
        lines = sorted({line for r in rows for line in r["lines"]})
        parsed: dict[str, dict] = {}
        for i in range(0, len(lines), 400):
            for res in pob.parse_mods(lines[i:i + 400]):
                parsed[res["line"]] = res
        print(f"parsed {len(lines)} distinct mod lines in {time.perf_counter() - t0:.1f}s; unsupported: {sum(1 for r in parsed.values() if r['unsupported'])}")

    tiers, drop_disabled = wiki_tiers()
    records = []
    per_stats: Counter = Counter()
    conditions: Counter = Counter()
    for r in rows:
        plain = r["name"][: -len(", " + r["base"])] if r["name"].endswith(", " + r["base"]) else r["name"]  # wiki keys are plain names
        mods = []
        unsupported = []
        for line in r["lines"]:
            res = parsed.get(line, {"ok": False, "unsupported": True, "mods": []})
            if res.get("unsupported"):
                unsupported.append(line)
            for m in res.get("mods", []):
                mods.append({"line": line, **{k: m.get(k) for k in ("name", "type", "value", "flags", "keyword_flags", "tags")}})
                for tag in m.get("tags", []):
                    if tag.get("type") in ("PerStat", "Multiplier", "MultiplierThreshold", "StatThreshold"):
                        per_stats[str(tag.get("stat") or tag.get("var") or "?")] += 1
                    if tag.get("type") in ("Condition", "ActorCondition"):
                        conditions[str(tag.get("var") or tag.get("varList") or "?")] += 1
        records.append({
            "key": r["key"], "name": r["name"], "base": r["base"], "type": r["type"], "req_level": r["req_level"],
            "lines": r["lines"], "templates": r.get("templates", r["lines"]), "mods": mods, "unsupported_lines": unsupported,
            "source": r.get("source"), "league": r.get("league"), "availability": classify_source(r.get("source")),
            "tier": (tiers.get(plain) or {}).get("tier"), "tier_note": (tiers.get(plain) or {}).get("notes") or None,
            "drop_enabled_wiki": (None if not drop_disabled and not tiers else plain not in drop_disabled),
        })
        if records[-1]["drop_enabled_wiki"] is False and records[-1]["availability"] != "legacy":
            records[-1]["availability"] = "legacy"  # the wiki says drop disabled; PoB still lists it
        elif records[-1]["availability"] == "core" and re.search(r"boss drop|boss unique|mercenary unique", records[-1]["tier_note"] or "", re.I):  # Bestiary uniques stay core: Tuadh ran Natural Hierarchy on day 1
            records[-1]["availability"] = "boss" if "boss" in (records[-1]["tier_note"] or "").lower() else "mechanic"  # wiki tier-list note; PoB has no Source line
    OUT.write_text(json.dumps({"corpus_id": "pob_uniques", "record_count": len(records), "source": "main.uniqueDB inside the pinned PoB; mods via modLib.parseMod", "records": records}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")
    print("uniques with unsupported lines:", sum(1 for r in records if r["unsupported_lines"]))
    print("availability:", Counter(r["availability"] for r in records).most_common())
    print("other (unclassified sources):", sorted({r["source"] for r in records if r["availability"] == "other"})[:15])
    print("top per-stat/multiplier scaling keys:", per_stats.most_common(20))
    print("top condition keys:", conditions.most_common(12))
    print("uniques with a PerStat/Multiplier tag:", sum(1 for r in records if any(t.get("type") in ("PerStat", "Multiplier") for m in r["mods"] for t in m["tags"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
