"""How many of an author's day-1 rares actually pay an attribute (D79 rule 4).

The template set may spend attribute affixes on at most N of its items, and N is
the authors' own median, not a guess. This counts, per reference, the wearable
rare items (weapons, armour, jewellery -- never flasks or jewels) that carry at
least one attribute affix, rolled or crafted, and prints the distribution and
the median that goes into `rails_default.json`.

"Attribute affix" is PoB's own verdict: the explicit line is matched back to the
base's mod ladder (or, for a `{crafted}` line, to the bench list) and the mod
must carry PoB's `attribute` tag. A line PoB cannot match falls back to reading
the grant out of the text with `attribute_grants`, and the count of those is
reported so the number stays auditable.

Run:  python scripts/fixture_attribute_affixes.py [fixture_set]
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from fixture_gear_tiers import META_PREFIXES, range_to_regex, template_ranges  # noqa: E402
from gear_transplant import active_items, active_rare_slots  # noqa: E402
from junkroan.optimizer.wishlist_gear import attribute_grants  # noqa: E402
from junkroan.pob.session import PobSession, decode_import_code  # noqa: E402


def explicit_lines(raw: str) -> list[str]:
    """The item's explicit lines, implicits and metadata removed."""

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    implicits = next((int(line.split(":")[1]) for line in lines if line.startswith("Implicits:")), 0)
    start = next((index for index, line in enumerate(lines) if line.startswith("Implicits:")), None)
    if start is None:
        return []
    return [line for line in lines[start + 1 + implicits:] if not line.startswith(META_PREFIXES)]


def matches(line: str, templates: list[str]) -> bool:
    """One rolled line against one mod's templates, values inside their ranges."""

    for template in templates:
        found = range_to_regex(template).match(line)
        if not found:
            continue
        ranges = template_ranges(template)
        values = [float(value) for value in found.groups()]
        if len(values) == len(ranges) and all(low - 1e-9 <= value <= high + 1e-9 for value, (low, high) in zip(values, ranges)):
            return True
    return False


def line_is_attribute(line: str, explicit: list[dict], bench: list[dict]) -> tuple[bool, bool]:
    """(is an attribute affix, PoB matched the line). Crafted lines are read from the bench."""

    crafted = line.startswith("{crafted}")
    clean = line.split("}")[-1] if line.startswith("{") else line
    for mod in (bench if crafted else explicit):
        templates = [str(value) for value in (mod.get("lines") or mod.get("rolled_lines") or ())]
        if matches(clean, templates):
            return "attribute" in {str(tag).lower() for tag in (mod.get("mod_tags") or ())}, True
    return bool(attribute_grants([clean])), False


def main(fixture_set: str = "tuadh_329") -> int:
    directory = ROOT / "tests" / "fixtures" / fixture_set
    sources = json.loads((directory / "sources.json").read_text(encoding="utf-8"))
    per_build: list[tuple[str, int, int]] = []
    unmatched = Counter()
    with PobSession(run_id="attribute-affixes") as pob:
        explicit_cache: dict[str, list[dict]] = {}
        bench_cache: dict[str, list[dict]] = {}
        for build in sources["builds"]:
            slug = str(build["slug"])
            xml = decode_import_code((directory / f"{slug}.pob.txt").read_text(encoding="utf-8").strip())
            raws = active_items(xml)
            paying, items, detail = 0, 0, []
            for slot in active_rare_slots(xml):
                raw = raws[slot]
                base = [line.strip() for line in raw.splitlines() if line.strip()][2]
                if base not in explicit_cache:
                    try:
                        explicit_cache[base] = pob.list_item_mods(base)["mods"]
                        bench_cache[base] = pob.list_bench_mods(base)["mods"]
                    except Exception as exc:  # a base PoB does not know
                        print(f"  ! {slug} {slot}: {exc}")
                        explicit_cache[base], bench_cache[base] = [], []
                items += 1
                hits = []
                for line in explicit_lines(raw):
                    attribute, matched = line_is_attribute(line, explicit_cache[base], bench_cache[base])
                    if not matched:
                        unmatched[line[:60]] += 1
                    if attribute:
                        hits.append(line)
                if hits:
                    paying += 1
                    detail.append(f"{slot}: " + " ; ".join(hits))
            per_build.append((slug, paying, items))
            print(f"{slug:24s} {paying}/{items} rares pay an attribute" + ("" if not detail else "  | " + " | ".join(detail)))
    counts = [paying for _slug, paying, _items in per_build]
    distribution = Counter(counts)
    print("\nrare items with an attribute affix, per reference:")
    for value in sorted(distribution):
        print(f"  {value}: {distribution[value]} references")
    print(f"references: {len(counts)}  median: {statistics.median(counts):g}  mean: {statistics.mean(counts):.2f}  max: {max(counts)}")
    print(f"unmatched lines PoB could not place (read from text instead): {sum(unmatched.values())}")
    for line, count in unmatched.most_common(10):
        print(f"  {count}x {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "tuadh_329"))
