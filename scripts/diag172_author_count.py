"""#172 finding 8: which author memos carry the derived minion/totem count on the wrong gem.

At @42565a9 `flag_main_group_for_full_dps` wrote the derived count onto `gems[0]` of the
author's main socket group. When the group's first gem is a support (Zizaran's Raise Spectre
links start with Minion Damage), the author's own typed-in count survived on the main skill's
gem untouched while the log said it was replaced -- and `author_lane` / `ratio_lane` of that
row were scored over the author's count, not the derived one.

Item 1 (read-only, no PoB): over the memo `author/<slug>.json`, `state_xml` field, of the five
runs in #172, list the slugs where BOTH hold: the main socket group's first `<Gem>` is not the
gem PoB's `mainActiveSkill` names (`build_from_skeleton.main_active_gem_index`, the same
resolution `normalize_author_gems` uses), and some gem of that group carries a typed `count` > 1.

`new18-tpl` ran on the laptop and left no `author/` folder; its author builds are the reference
PoBs of the `new18` set (`scripts.benchmark.SETS["new18"]`, all 18 in `tests/fixtures/tuadh_329`,
the same files `benchmark.fixture_path` loads as a slug's author). For that run the same
criterion is checked directly over those 18 fixtures (`decode_import_code`, no PoB session), the
build's own `mainSocketGroup` and gems as authored -- the same read-only rule, over the files the
run loaded rather than a memo it never wrote.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_from_skeleton import main_active_gem_index  # noqa: E402
from benchmark import SETS, fixture_path  # noqa: E402
from junkroan.pob.session import decode_import_code  # noqa: E402

RUNS = {
    "ziz-tpl": "20260927-0322-ziz-tpl-main3-s4",
    "ziz": "20260926-0200-ziz-main3-s4",
    "new18-tpl": "20260926-0920-new18-tpl-main3-s4-lap",
    "core14-tpl": "20260926-1759-core14-tpl-main3-s4",
    "core14": "20260925-1943-core14-main3-s4",
}


def main_group_gems(state_xml: str) -> tuple[list[ET.Element], int | None] | None:
    root = ET.fromstring(state_xml)
    build = root.find("Build")
    skills = root.find("Skills")
    if build is None or skills is None:
        return None
    active = skills.get("activeSkillSet") or "1"
    skill_set = next((s for s in skills.findall("SkillSet") if s.get("id") == active), None)
    groups = skill_set.findall("Skill") if skill_set is not None else skills.findall("Skill")
    main_idx = int(build.get("mainSocketGroup") or 1)
    if not (1 <= main_idx <= len(groups)):
        return None
    group = groups[main_idx - 1]
    gems = group.findall("Gem")
    live = [g for g in gems if g.get("enabled", "true") == "true" and (g.get("nameSpec") or "").strip()]
    head = main_active_gem_index([g.get("nameSpec") for g in live], int(group.get("mainActiveSkill") or 1))
    return live, head


def check_xml(name: str, xml_text: str) -> dict | None:
    result = main_group_gems(xml_text)
    if result is None:
        return None
    live, head = result
    if not live or head is None:
        return None
    main_gem = live[head]
    first_gem = live[0]
    same_gem = (first_gem.get("nameSpec") or "") == (main_gem.get("nameSpec") or "") and first_gem is main_gem
    if same_gem:
        return None
    typed = [(g.get("nameSpec"), int(g.get("count") or 1)) for g in live if int(g.get("count") or 1) > 1]
    if not typed:
        return None
    return {
        "slug": name,
        "first_gem": first_gem.get("nameSpec"),
        "main_gem": main_gem.get("nameSpec"),
        "typed_counts": typed,
    }


def check_slug(memo_path: Path) -> dict | None:
    memo = json.loads(memo_path.read_text(encoding="utf-8"))
    state_xml = memo.get("state_xml")
    if not state_xml:
        return None
    return check_xml(memo_path.stem, state_xml)


def _report(short: str, run: str, checked: int, affected: list[dict]) -> None:
    print(f"== {short} ({run}) ==")
    print(f"checked {checked}, affected {len(affected)}")
    for hit in affected:
        counts = ", ".join(f"{name}={count}" for name, count in hit["typed_counts"])
        print(f"  {hit['slug']}: gems[0]={hit['first_gem']!r} main={hit['main_gem']!r} typed counts: {counts}")
    print()


def main() -> None:
    for short, run in RUNS.items():
        author_dir = ROOT / "artifacts" / "benchmark" / run / "author"
        if author_dir.is_dir():
            memos = sorted(author_dir.glob("*.json"))
            checked = 0
            affected = []
            for memo_path in memos:
                checked += 1
                hit = check_slug(memo_path)
                if hit:
                    affected.append(hit)
            _report(short, run, checked, affected)
            continue

        if short != "new18-tpl":
            _report(short, run, 0, [])
            continue

        # no author/ folder was written (the run happened on the laptop): check the same criterion
        # directly over the new18 set's own reference fixtures (as authored, no PoB).
        checked = 0
        affected = []
        for slug in SETS["new18"]:
            checked += 1
            xml_text = decode_import_code(fixture_path(slug).read_text(encoding="utf-8").strip())
            hit = check_xml(slug, xml_text)
            if hit:
                affected.append(hit)
        _report(short, f"{run}, fixtures as authored", checked, affected)


if __name__ == "__main__":
    main()
