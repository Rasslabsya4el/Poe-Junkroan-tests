"""Build the game's mod-family index from RePoE.

An item cannot carry two mods of the same game mod *family*. PoB's own mod
tables carry a `group` field which is NOT that family: PoB splits 185 of the
512 families into several groups (the Chaos / Physical / Cold / Fire "Damage
over Time Multiplier" suffixes are one family, `DamageOverTimeMultiplier`, but
four PoB groups), and 10 PoB groups span two families (a mod occupies ALL of
its families, e.g. `AddedFireDamageEnhancedMod` is both `FireDamage` and
`ConvertPhysicalToFire`). Rolling loot or bench-crafting on PoB's group alone
produces items the game cannot drop.

Source: RePoE (https://repoe-fork.github.io/mods.json), a JSON export of the
game's mod data keyed by the same mod ids PoB uses.

A second corpus comes out of the same export: `bench_mods.json`, every mod of
the `crafted` domain with its affix type, level, mod text and stats. PoB's
crafting-bench rows (`data.masterMods`) carry no mod id at all, so
`pob/bench_mod_ids.py` has to recognise a bench craft by its text before its
family can be looked up.

Out: src/junkroan/pob/corpus_data/mod_families.json
     src/junkroan/pob/corpus_data/bench_mods.json
Run: python scripts/build_mod_families.py --source path/to/mods.json
     python scripts/build_mod_families.py            # fetches the URL
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "src" / "junkroan" / "pob" / "corpus_data" / "mod_families.json"
BENCH_OUT = PROJECT_ROOT / "src" / "junkroan" / "pob" / "corpus_data" / "bench_mods.json"
POB_DATA = PROJECT_ROOT / "vendor" / "pob" / "source" / "src" / "Data"
POB_MOD_FILES = ("ModExplicit.lua", "ModMaster.lua")
DEFAULT_URL = "https://repoe-fork.github.io/mods.json"
KEPT_DOMAINS = ("item", "crafted")
BENCH_DOMAIN = "crafted"
BENCH_TYPES = ("prefix", "suffix")

_MOD_ID = re.compile(r'\["(?P<id>[^"]+)"\]\s*=\s*\{')


def pob_mod_ids(data_dir: Path = POB_DATA) -> set[str]:
    """Every mod id PoB's own tables key: `["<id>"] = {` in ModExplicit / ModMaster."""

    ids: set[str] = set()
    found = False
    for name in POB_MOD_FILES:
        path = data_dir / name
        if not path.is_file():
            continue
        found = True
        ids |= set(_MOD_ID.findall(path.read_text(encoding="utf-8", errors="replace")))
    if not found:
        raise SystemExit(f"none of {', '.join(POB_MOD_FILES)} found under {data_dir} (vendor/pob/source is gitignored; re-clone it at the pinned tag)")
    return ids


def read_source(source: str | None, url: str) -> tuple[str, bytes]:
    """(origin, raw bytes) of the RePoE export: a local path if given, else the URL."""

    if source:
        return source, Path(source).read_bytes()
    from urllib.request import urlopen  # only the URL branch needs the network

    with urlopen(url) as response:  # noqa: S310 - the URL is ours, pinned in the corpus
        return url, response.read()


def families(mods: dict, keep_ids: Iterable[str]) -> dict[str, list[str]]:
    """{mod id: [family, ...]} for the item / crafted pool plus every id PoB knows."""

    keep = {mod_id for mod_id, mod in mods.items() if mod.get("domain") in KEPT_DOMAINS}
    keep |= {mod_id for mod_id in keep_ids if mod_id in mods}
    return {mod_id: sorted(mods[mod_id].get("groups") or []) for mod_id in keep}


def bench_mods(mods: dict) -> dict[str, dict]:
    """{mod id: {type, level, lines, stats, families}} for every craftable bench mod.

    The `crafted` domain is what the crafting bench (and the unveil-into-craft
    path) can put on an item; its prefixes and suffixes are the rows PoB shows in
    `data.masterMods`. `lines` is the mod text, the only handle on a PoB bench row.
    """

    out: dict[str, dict] = {}
    for mod_id, mod in mods.items():
        if mod.get("domain") != BENCH_DOMAIN or mod.get("generation_type") not in BENCH_TYPES:
            continue
        out[mod_id] = {
            "type": mod["generation_type"],
            "level": int(mod.get("required_level") or 0),
            "lines": [line for line in (mod.get("text") or "").split("\n") if line.strip()],
            "stats": [[s.get("id"), s.get("min"), s.get("max")] for s in (mod.get("stats") or [])],
            "families": sorted(mod.get("groups") or []),
        }
    return out


def render_bench(meta: dict, index: dict[str, dict]) -> str:
    """One bench mod per line: ~1.6k entries, readable in a diff."""

    lines = ["{"]
    lines += [f" {json.dumps(key)}: {json.dumps(meta[key])}," for key in sorted(meta)]
    lines.append(' "mods": {')
    ids = sorted(index)
    for i, mod_id in enumerate(ids):
        tail = "" if i == len(ids) - 1 else ","
        lines.append(f"  {json.dumps(mod_id)}: {json.dumps(index[mod_id], separators=(',', ':'))}{tail}")
    lines += [" }", "}"]
    return "\n".join(lines) + "\n"


def render(meta: dict, index: dict[str, list[str]]) -> str:
    """One mod id per line: 26k entries, readable in a diff, still small."""

    lines = ["{"]
    lines += [f" {json.dumps(key)}: {json.dumps(meta[key])}," for key in sorted(meta)]
    lines.append(' "families": {')
    ids = sorted(index)
    for i, mod_id in enumerate(ids):
        tail = "" if i == len(ids) - 1 else ","
        lines.append(f"  {json.dumps(mod_id)}: {json.dumps(index[mod_id], separators=(',', ':'))}{tail}")
    lines += [" }", "}"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", help="local RePoE mods.json (skips the download)")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"RePoE mods.json URL (default {DEFAULT_URL})")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--bench-out", type=Path, default=BENCH_OUT, help="crafting-bench mod corpus (crafted domain)")
    args = parser.parse_args(argv)

    origin, raw = read_source(args.source, args.url)
    mods = json.loads(raw.decode("utf-8"))
    pob_ids = pob_mod_ids()
    missing = sorted(pob_ids - set(mods))
    index = families(mods, pob_ids)

    meta = {
        # the URL is the provenance even when the bytes came from a local copy; sha256 pins them
        "source": args.url if not args.source else f"{args.url} (local copy {Path(origin).name})",
        "fetched": date.today().isoformat(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "count": len(index),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(meta, index), encoding="utf-8")

    bench = bench_mods(mods)
    bench_meta = {**meta, "count": len(bench)}
    args.bench_out.parent.mkdir(parents=True, exist_ok=True)
    args.bench_out.write_text(render_bench(bench_meta, bench), encoding="utf-8")

    print(f"read {len(mods)} mods from {origin} (sha256 {meta['sha256'][:12]})")
    print(f"PoB mod ids: {len(pob_ids)} found in RePoE, {len(missing)} not found")
    if missing:
        print("  not found: " + ", ".join(missing[:20]) + (" ..." if len(missing) > 20 else ""))
    multi = sum(1 for f in index.values() if len(f) > 1)
    print(f"wrote {args.out} ({args.out.stat().st_size / 1024:.0f} KB): {len(index)} mods, {len({f for fams in index.values() for f in fams})} families, {multi} mods in more than one family")
    off_group = sum(1 for m in bench.values() if len(m["families"]) != 1)
    print(f"wrote {args.bench_out} ({args.bench_out.stat().st_size / 1024:.0f} KB): {len(bench)} crafting-bench mods, {off_group} of them not in exactly one family")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
