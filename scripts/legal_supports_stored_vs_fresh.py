"""Saved legal-supports lists against fresh ones, one row per skill (#980 unit 2).

For each `legal_supports-<skill>.json` in --stored, `SkeletonGenerator.legal_supports` builds the list again
with PoB: a bare skeleton of that skill on one PobSession for the whole run. The fresh files go to --out
(`LEGAL_SUPPORTS_CACHE_DIR` points there); artifacts/cache is never read or written. Each row prints the skill,
the names stored, the names fresh, the names added and removed (the diff only, never the whole list), and the
time the fresh build took. The end line counts the skills whose lists differ.

    python scripts/legal_supports_stored_vs_fresh.py --stored <dir with the saved files> --out <scratch dir>
        [--only <skill-file-stem substring> ...] [--limit N]

The stored files may be the old plain JSON list or the new {"key", "legal"} dict. The skill's real name is
resolved from `active_gems()` by `name.lower().replace(" ", "_") == stem`; a stem with no name is printed
as skipped. Needs PoB: run `python scripts/machine_load.py --need 1 --role other` before, and a run past
~5 min through `runs submit`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

PREFIX = "legal_supports-"
SKIP_NOT_FOUND = "skipped (name not found)"
SKIP_AMBIGUOUS = "skipped (more than one name)"
BARE_CLASS = "Witch"  # legality depends on the skill's tags only; the class is metadata for the bare skeleton


def stem_of(path: Path) -> str:
    """`legal_supports-shrapnel_ballista.json` -> `shrapnel_ballista`."""

    return path.stem[len(PREFIX):] if path.stem.startswith(PREFIX) else path.stem


def read_stored(path: Path) -> list[str]:
    """The saved list: the old plain JSON list, or the new {"key", "legal"} dict (#980 unit 1)."""

    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("legal")
    if not isinstance(raw, list):
        raise ValueError(f"{path.name}: neither a list nor a dict with a 'legal' list")
    return [str(name) for name in raw]


def resolve_skill(stem: str, names: Iterable[str]) -> list[str]:
    """The gem names whose lowercase, underscored form is `stem`: [] = no such skill, one name = the skill."""

    return sorted({name for name in names if name.lower().replace(" ", "_") == stem})


def compare(stored: Iterable[str], fresh: Iterable[str]) -> dict:
    """Counts and the names added (in fresh only) and removed (in stored only), both sorted."""

    stored_list, fresh_list = list(stored), list(fresh)
    return {
        "stored_n": len(stored_list),
        "fresh_n": len(fresh_list),
        "added": sorted(set(fresh_list) - set(stored_list)),
        "removed": sorted(set(stored_list) - set(fresh_list)),
    }


def skill_names() -> list[str]:
    from junkroan.search.hypothesis import active_gems

    return sorted({rec["name"] for rec in active_gems().values()})


def run(args: argparse.Namespace) -> int:
    from junkroan.optimizer.rails import Rails
    from junkroan.pob.session import PobSession
    from junkroan.report_format import human_duration
    from junkroan.search import generator
    from junkroan.search.generator import SkeletonGenerator, legal_supports_cache_path
    from junkroan.search.skeleton import Skeleton

    stored_dir = args.stored.resolve()
    out = args.out.resolve()
    files = sorted(p for p in stored_dir.glob(f"{PREFIX}*.json") if p.is_file())
    if args.only:
        files = [p for p in files if any(part in stem_of(p) for part in args.only)]
    if args.limit:
        files = files[: args.limit]
    out.mkdir(parents=True, exist_ok=True)
    generator.LEGAL_SUPPORTS_CACHE_DIR = out  # the fresh files land here; artifacts/cache is not touched
    names = skill_names()
    rails = Rails.load()

    print(f"stored: {stored_dir}  ({len(files)} files)")
    print(f"fresh:  {out}")
    print(f"{'skill':<30} {'stored':>6} {'fresh':>6}  added / removed (names)  (took)")
    compared = differ = skipped = 0
    t_all = time.perf_counter()
    with PobSession(run_id="legal-supports-stored-vs-fresh") as pob:
        gen = SkeletonGenerator(pob, rails, log=lambda _m: None)
        for path in files:
            stem = stem_of(path)
            found = resolve_skill(stem, names)
            if len(found) != 1:
                print(f"{stem:<30} {SKIP_NOT_FOUND if not found else SKIP_AMBIGUOUS}")
                skipped += 1
                continue
            skill = found[0]
            try:
                stored = read_stored(path)
            except (OSError, ValueError) as exc:
                print(f"{skill:<30} skipped (unreadable: {type(exc).__name__})")
                skipped += 1
                continue
            target = legal_supports_cache_path(skill)
            if target.is_file():
                target.unlink()  # an earlier run's fresh copy in --out: built again, not read back
            t0 = time.perf_counter()
            fresh = gen.legal_supports(Skeleton(class_name=BARE_CLASS, ascendancy="None", main_link=[skill]))
            took = human_duration(time.perf_counter() - t0)
            row = compare(stored, fresh)
            compared += 1
            changed = bool(row["added"] or row["removed"])
            differ += changed
            added = ", ".join(row["added"]) or "-"
            removed = ", ".join(row["removed"]) or "-"
            print(f"{skill:<30} {row['stored_n']:>6} {row['fresh_n']:>6}  added: {added}  removed: {removed}  ({took})", flush=True)
    print(f"lists that differ: {differ} of {compared} compared ({skipped} skipped)")
    print(f"total {human_duration(time.perf_counter() - t_all)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Saved legal-supports lists against fresh PoB builds, one row per skill (#980).")
    ap.add_argument("--stored", type=Path, required=True, metavar="DIR", help="the folder with the saved legal_supports-<skill>.json files")
    ap.add_argument("--out", type=Path, required=True, metavar="DIR", help="scratch folder for the fresh files (never artifacts/cache)")
    ap.add_argument("--only", nargs="+", metavar="STEM", help="only the files whose stem contains one of these substrings (arc, bow ...)")
    ap.add_argument("--limit", type=int, metavar="N", help="at most N files, after --only")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
