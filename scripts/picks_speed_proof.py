"""Proof that the picks move's repeated-work rules (speed audit 2026-09-18) changed no number.

Runs `SkeletonGenerator.rejudge_picks` -- the improvement loop's "picks" move -- on a finished
build, once with the two rules off and once with them on, in one process and against the same
starting build, and compares the kept swaps (same swaps, same order, same before/after values) and
the final objective value. Reports the PoB round trips and the seconds of each run.

The two rules:

* `Skeleton.brand_attach_extra` remembers the build's "additional Brand Attached to an Enemy" count
  while neither the items, the passives nor the gems that grant an active skill have changed, so a
  support trial no longer buys a whole `read_state` export plus a `build_text` rebuild for a number
  it cannot move;
* the worker's in-place skills writer remembers which gem a name resolved to, so
  `SkillsTab:ProcessSocketGroup` reaches the gem by id instead of scanning the gem database
  (`JUNKROAN_GEM_ID_MEMO=0` turns it off).

    python scripts/picks_speed_proof.py [stormbrand] [bleed_bow]

Exits 1 on any mismatch. Skips (exit 0) when the pinned PoB runtime is not present.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.append(str(PROJECT_ROOT / "scripts"))

# the finished seed-1 builds of the rules-smoke campaign: the state the loop's picks move really runs on
BUILDS = PROJECT_ROOT / "artifacts" / "benchmark" / "20260918-0723-rules-smoke"
SLUGS = ("stormbrand", "bleed_bow")
COUNTED = ("set_skills", "stats", "read_state", "set_config", "config_options", "config_inputs",
           "export_xml", "load_xml", "equip", "trial_stats", "tree_light", "calc")


def runtime_present() -> bool:
    lock = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
    return (PROJECT_ROOT / "var" / "cache" / "pob" / lock["tag"] / lock["extract_subdir"] / "lua51.dll").is_file()


def run(slug: str, *, before: bool) -> dict:
    """One picks move on `slug`'s finished build. `before` = both rules off."""

    os.environ["JUNKROAN_GEM_ID_MEMO"] = "0" if before else "1"  # read by the worker this call starts
    import junkroan.search.skeleton as skeleton_mod
    from build_from_skeleton import skeleton_from_xml
    from junkroan.optimizer.objective_select import objective_for
    from junkroan.optimizer.pipeline import BuildPipeline
    from junkroan.optimizer.rails import Rails
    from junkroan.pob.session import PobSession, decode_import_code
    from junkroan.search.generator import SkeletonGenerator
    from junkroan.search.hypothesis import active_gems

    memoized = skeleton_mod.brand_attach_extra
    if before:
        def unmemoized(pob, names, links=None) -> int:
            from junkroan.optimizer.config_rules import build_text

            return len(skeleton_mod._BRAND_ATTACHED_LINE.findall(build_text(pob)))

        skeleton_mod.brand_attach_extra = unmemoized

    calls: Counter = Counter()
    rails = Rails.load()
    xml = decode_import_code((BUILDS / f"{slug}-s1.pob.txt").read_text(encoding="utf-8").strip())
    try:
        with PobSession(run_id=f"picks-speed-proof-{slug}") as pob:
            pob.load_xml(xml)
            skeleton = skeleton_from_xml(xml, pob=pob)
            for group in skeleton.extra_groups:
                group.picked = True  # every utility group is one the picker chose: the move judges them all
            pipe = BuildPipeline(pob, rails, log=lambda _m: None)
            pipe.objective = objective_for(rails, skeleton.main_link[0], pipe.objective, mode=skeleton.mode)
            pipe.judging.main_tags = frozenset(active_gems().get(skeleton.main_link[0].lower(), {}).get("tag_keys") or [])
            pipe.judging.rejudge(skeleton)
            gen = SkeletonGenerator(pob, rails, objective=pipe.objective, log=lambda _m: None)
            gen.legal_supports(skeleton)  # the legality readback is cached to disk: not part of the move's cost

            for name in COUNTED:  # counted after the setup, so the numbers are the move's own
                original = getattr(pob, name)

                def counting(*a, _n=name, _o=original, **kw):
                    calls[_n] += 1
                    return _o(*a, **kw)

                setattr(pob, name, counting)

            t0 = time.perf_counter()
            changes = gen.rejudge_picks(skeleton, reconfigure=lambda *, full, castability_context: pipe.judging.rejudge(skeleton), min_gain=0.005, max_sweeps=1)
            seconds = time.perf_counter() - t0
            final = pipe.objective.score(pob.stats(pipe.objective.stat_keys))
            return {
                "changes": [(c["what"], c["was"], c["now"], round(float(c["before"]), 4), round(float(c["after"]), 4)) for c in changes],
                "link": list(skeleton.main_link),
                "groups": [list(g.gems) for g in skeleton.extra_groups],
                "value": round(float(final.value), 4),
                "violation": round(float(final.violation), 6),
                "seconds": seconds,
                "calls": dict(calls),
            }
    finally:
        skeleton_mod.brand_attach_extra = memoized


def report(slug: str, before: dict, after: dict) -> bool:
    ok = all(before[k] == after[k] for k in ("changes", "link", "groups", "value", "violation"))
    print(f"\n{slug}: {'OK' if ok else 'MISMATCH'}  {len(after['changes'])} swaps kept, "
          f"final {after['value']:,.0f} (viol {after['violation']:.3f})")
    for what, was, now, v0, v1 in after["changes"]:
        print(f"             {what} {was} -> {now}: {v0:,.0f} -> {v1:,.0f}")
    if not ok:
        for key in ("changes", "link", "groups", "value", "violation"):
            if before[key] != after[key]:
                print(f"             {key}: before {before[key]!r} != after {after[key]!r}")
    print(f"             seconds {before['seconds']:7.1f} -> {after['seconds']:7.1f} "
          f"({after['seconds'] / before['seconds'] - 1:+.0%})")
    for name in sorted(set(before["calls"]) | set(after["calls"])):
        b, a = before["calls"].get(name, 0), after["calls"].get(name, 0)
        flag = "" if b == a else f"   ({a - b:+d})"
        print(f"             {name:14s} {b:6d} -> {a:6d}{flag}")
    return ok


def main() -> int:
    if not runtime_present():
        print("pinned PoB runtime not present: skipped")
        return 0
    if not BUILDS.is_dir():
        print(f"finished builds not present at {BUILDS}: skipped")
        return 0
    slugs = [s for s in sys.argv[1:] if s in SLUGS] or list(SLUGS)
    print("picks speed proof (before = the memos off, after = on)")
    ok = True
    for slug in slugs:
        ok &= report(slug, run(slug, before=True), run(slug, before=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
