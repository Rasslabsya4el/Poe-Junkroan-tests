"""Builds the canonical loadout rulebook: docs/rulebook/loadout-rulebook.json.

The hand-written part (systems, the user's rulings) lives in docs/rulebook/loadout-rulebook.entries.json and is
edited there; this script adds the unique-jewel entries (the user's answers from the jewel form + mods from PoB's
unique index), validates ids / loadouts and writes the single file the page and, later, the rails read.

    python scripts/build_rulebook.py [--jewels <dir with the form's answers as <id>.json>]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
BOOK = ROOT / "docs" / "rulebook"
LOADOUT_IDS = ("day1", "t16", "endgame", "uber", "uber_plus", "mirror")
FORM_TO_ID = {"day1": "day1", "t16": "t16", "endgame": "endgame", "uber": "uber", "mirror": "mirror"}


def jewel_id(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]


def jewel_kind(base: str) -> str:
    b = base.lower()
    if "cluster jewel" in b:
        return "кластерный"
    if "eye jewel" in b:
        return "abyss"
    if "timeless jewel" in b:
        return "timeless"
    return "обычный"


def jewel_entries(answers_dir: Path | None, saved: Path) -> tuple[list[dict], dict]:
    from junkroan.search.hypothesis import uniques_by_name

    answers: dict[str, dict] = {}
    if answers_dir and answers_dir.is_dir():
        for f in answers_dir.glob("*.json"):
            answers[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        saved.write_text(json.dumps(answers, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    elif saved.is_file():
        answers = json.loads(saved.read_text(encoding="utf-8"))
    recs = [r for rs in uniques_by_name().values() for r in rs if str(r.get("type") or "") == "Jewel"]
    seen: set[str] = set()
    out: list[dict] = []
    stats = {"legacy_skipped": 0, "unanswered": [], "never": 0}
    for r in sorted(recs, key=lambda x: x["plain_name"]):
        name = r["plain_name"]
        if name in seen:
            continue
        seen.add(name)
        legacy = str(r.get("availability") or "") == "legacy" or "No longer obtainable" in str(r.get("source") or "")
        if legacy:
            stats["legacy_skipped"] += 1
            continue
        jid = jewel_id(name)
        a = answers.get(jid) or {}
        first = FORM_TO_ID.get(str(a.get("loadout") or ""))
        never = str(a.get("loadout") or "") == "never"
        lines = [re.sub(r"\s+", " ", str(l)) for l in (r.get("lines") or [])]
        entry = {
            "id": "jewel-" + jid, "category": "unique_jewels", "scope": "narrow", "title": name, "title_en": str(r.get("base") or ""),
            "tags": [jewel_kind(str(r.get("base") or "")), {"core": "обычный дроп", "boss": "босс-дроп", "uber": "убер-босс"}.get(str(r.get("availability")), str(r.get("availability")))]
                    + ([f"вики T{r.get('tier')}"] if r.get("tier") not in (None, "None") else []),
            "explain": " / ".join(lines) or "-",
            "source": "форма уник-джевелов, 19.09",
            "user_note": str(a.get("note") or "").strip(),
        }
        if never:
            entry["status"], entry["rules"] = "never", {}
            stats["never"] += 1
        elif first:
            entry["status"], entry["rules"] = "rule", {first: "разрешён"}
        else:
            entry["status"], entry["rules"] = "open", {}
            if not entry["user_note"]:
                stats["unanswered"].append(name)
        out.append(entry)
    return out, stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jewels", type=Path)
    args = ap.parse_args()
    src = json.loads((BOOK / "loadout-rulebook.entries.json").read_text(encoding="utf-8"))
    jewels, stats = jewel_entries(args.jewels, BOOK / "2026-09-19-unique-jewels.json")
    overrides = src.get("jewel_overrides") or {}
    for e in jewels:
        o = overrides.get(e["id"])
        if o:
            e.update(o)
    entries = list(src["entries"]) + jewels
    cats = {c["id"] for c in src["categories"]}
    ids: set[str] = set()
    for e in entries:
        assert e["id"] not in ids, f"duplicate id {e['id']}"
        ids.add(e["id"])
        assert e["category"] in cats, f"{e['id']}: unknown category {e['category']}"
        assert set(e.get("rules") or {}) <= set(LOADOUT_IDS), f"{e['id']}: unknown loadout in rules"
        assert set(e.get("assumed") or []) <= set(LOADOUT_IDS), f"{e['id']}: unknown loadout in assumed"
    unknown = set(overrides) - {e["id"] for e in jewels}
    assert not unknown, f"jewel_overrides for unknown jewels: {sorted(unknown)}"
    book = {"version": src["version"], "updated": src["updated"], "about": src["about"], "loadouts": src["loadouts"],
            "categories": src["categories"], "entries": entries}
    (BOOK / "loadout-rulebook.json").write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
    by = {}
    for e in entries:
        by[e["category"]] = by.get(e["category"], 0) + 1
    print("entries", len(entries), by)
    print("jewels:", len(jewels), stats)


if __name__ == "__main__":
    main()
