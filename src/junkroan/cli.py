"""`junkroan`: one entry point over the scripts (ROADMAP Phase 6).

    junkroan build request.json                 # a request file (docs/REQUEST.md)
    junkroan build --skill "Storm Brand" --mode hit --ascendancy Hierophant,Inquisitor --level 80
    junkroan build ... --dry-run                # echo how the request was understood, run nothing
    junkroan probe "Blade Vortex"               # what damage the skill deals by itself (modes)
    junkroan audit "artifacts/search-smite/*.pob.txt"
    junkroan describe "artifacts/search-smite/01 *.pob.txt"
    junkroan benchmark --seeds 3 --no-variants

`build` turns the flags into a request (every flag is a checklist item of
docs/REQUEST.md) and hands it to scripts/search.py; the other commands are
thin wrappers. Without installing the package: `python -m junkroan.cli ...`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = PROJECT_ROOT / "scripts"


def _csv(value: str | None) -> list[str] | None:
    return [v.strip() for v in value.split(",") if v.strip()] if value else None


def _pairs(values: list[str] | None) -> dict[str, str] | None:
    """slot=name pairs ("Body Armour=Hyrri's Ire") into a dict."""

    if not values:
        return None
    out: dict[str, str] = {}
    for v in values:
        if "=" not in v:
            raise SystemExit(f"expected slot=name, got {v!r}")
        slot, name = v.split("=", 1)
        out[slot.strip()] = name.strip()
    return out


def _multi_pairs(values: list[str] | None) -> dict[str, list[str]] | None:
    """key=line pairs ("Wand=+1 to Level of all Fire Spell Skill Gems") into {key: [line, ...]}; a repeated key accumulates."""

    if not values:
        return None
    out: dict[str, list[str]] = {}
    for v in values:
        if "=" not in v:
            raise SystemExit(f"expected key=line, got {v!r}")
        key, line = v.split("=", 1)
        out.setdefault(key.strip(), []).append(line.strip())
    return out


def request_from_args(args: argparse.Namespace) -> dict:
    """The request dict (docs/REQUEST.md) a `build` invocation describes; flags
    override the file's fields when both are given."""

    req: dict = {}
    if args.request:
        req = json.loads(Path(args.request).read_text(encoding="utf-8-sig"))
    flags = {
        "why": args.why, "skill": args.skill, "mode": args.mode, "delivery": args.delivery, "trigger_with": args.trigger_with, "part": args.part,
        "ascendancy": _csv(args.ascendancy) if args.ascendancy and args.ascendancy.lower() != "auto" else ("auto" if args.ascendancy else None),
        "ascendancy_nodes": _csv(args.ascendancy_nodes), "level": args.level,
        "keystones": _csv(args.keystones), "nodes": _csv(args.nodes), "affixes": _multi_pairs(args.affixes), "forbid_keystones": _csv(args.forbid_keystones),
        "uniques": _pairs(args.unique), "unique_slots": args.unique_slots, "rare_bases": _pairs(args.rare_base), "weapon_types": _csv(args.weapon_types), "spectres": args.spectre,
        "supports": _csv(args.supports), "forbid_supports": _csv(args.forbid_supports), "utilities": _csv(args.utilities), "forbid_utilities": _csv(args.forbid_utilities),
        "utility_groups": args.utility_groups, "top": args.top, "seeds": args.seeds, "workers": args.workers, "max_builds": args.max_builds, "gear": args.gear,
    }
    if args.scaling:
        stat, _, share = args.scaling.partition(":")
        flags["scaling"] = {"stat": stat.strip(), **({"seed_points": float(share)} if share else {})}
    if args.config:
        cfg: dict = {}
        for item in args.config:
            k, _, v = item.partition("=")
            try:
                cfg[k.strip()] = json.loads(v)
            except json.JSONDecodeError:
                cfg[k.strip()] = v
        flags["config"] = cfg
    for k, v in flags.items():
        if v is not None:
            req[k] = v
    if not req.get("skill"):
        raise SystemExit("a request needs a skill: --skill or a request file with \"skill\"")
    req.setdefault("why", f"{req['skill']} via junkroan build")
    return req


def _rulebook_level_range(stage: str) -> tuple[int, int] | None:
    """The (low, high) level of rulebook row `c-level` for a stage (machine.level.<stage>), None when absent."""

    path = PROJECT_ROOT / "docs" / "rulebook" / "loadout-rulebook.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    stack = [data]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            if o.get("id") == "c-level":
                rng = ((o.get("machine") or {}).get("level") or {}).get(stage)
                return (int(rng[0]), int(rng[1])) if rng else None
            stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)
    return None


def check_level(req: dict) -> None:
    """Refuse a day-1 request whose level is outside the rulebook's `c-level` range (75-80)."""

    stage = req.get("stage", "day1")
    level = req.get("level")
    if stage != "day1" or level is None:
        return
    lo, hi = _rulebook_level_range("day1") or (75, 80)  # fallback: c-level day1 = 75-80
    if not lo <= int(level) <= hi:
        raise SystemExit(f"--level {level} is outside {lo}-{hi}, the day-1 level range of rulebook row c-level")


def search_argv(args: argparse.Namespace, request_path: Path | str, skill: str) -> list[str]:
    """The `scripts/search.py` command line a `build` invocation runs. Every budget knob
    of the request travels in the request file (top, seeds, workers, max_builds); the ones
    that are search-level are passed as flags too, and a flag wins over the file (`--seeds`
    reaches the echo through the request and the run through the flag)."""

    argv = [str(skill), "--request", str(request_path)]
    if args.dry_run:
        argv.append("--dry-run")
    if getattr(args, "seeds", None):  # full builds per finalist; the request file carries it too, the flag wins
        argv += ["--seeds", str(args.seeds)]
    if getattr(args, "full_ranks", None):
        argv += ["--full-ranks", str(args.full_ranks)]
    if getattr(args, "loop_seconds", None) is not None:
        argv += ["--loop-seconds", str(args.loop_seconds)]
    if getattr(args, "no_variants", False):  # one full build per candidate: no unique variants, no mutation round
        argv += ["--no-unique-variants", "--no-mutation"]
    if getattr(args, "gear", None):
        argv += ["--gear", str(args.gear)]
    if getattr(args, "trace_out", None):
        argv += ["--trace-out", str(args.trace_out)]
    return argv


def _run(script: str, argv: list[str]) -> int:
    return subprocess.call([sys.executable, str(SCRIPTS / script), *argv], cwd=str(PROJECT_ROOT))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="junkroan", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="search builds for a request (docs/REQUEST.md)")
    b.add_argument("request", nargs="?", help="request JSON file; flags override its fields")
    b.add_argument("--why"); b.add_argument("--skill"); b.add_argument("--mode", help="hit | dot | ignite | poison | bleed | minion | auto")
    b.add_argument("--delivery"); b.add_argument("--trigger-with", dest="trigger_with"); b.add_argument("--part", type=int)
    b.add_argument("--ascendancy", help="comma-separated ids, or auto (all)"); b.add_argument("--ascendancy-nodes", dest="ascendancy_nodes")
    b.add_argument("--level", type=int); b.add_argument("--keystones"); b.add_argument("--forbid-keystones", dest="forbid_keystones")
    b.add_argument("--nodes", help="comma-separated passive names (notable, keystone, mastery effect) the build must allocate")
    b.add_argument("--affixes", action="append", help="Key=mod line, repeatable; Key is a slot or item class (Wand=+1 to Level of all Fire Spell Skill Gems)")
    b.add_argument("--unique", action="append", help="slot=name, repeatable"); b.add_argument("--unique-slots", dest="unique_slots", help="auto | none")
    b.add_argument("--rare-base", dest="rare_base", action="append", help="slot=base, repeatable"); b.add_argument("--weapon-types", dest="weapon_types")
    b.add_argument("--spectre", action="append", help="Raise Spectre only: a spectre id (Metadata/Monsters/...) or name from PoB's Spectres.lua, repeatable; the first is the gem's minion")
    b.add_argument("--supports"); b.add_argument("--forbid-supports", dest="forbid_supports"); b.add_argument("--utilities"); b.add_argument("--forbid-utilities", dest="forbid_utilities")
    b.add_argument("--utility-groups", dest="utility_groups", type=int); b.add_argument("--scaling", help="stat or stat:seed_share, e.g. Dex or Int:0.4")
    b.add_argument("--config", action="append", help="var=value the user vouches for, repeatable")
    b.add_argument("--top", type=int); b.add_argument("--seeds", type=int, help="full builds per finalist skeleton, the best delivered (default 3)")
    b.add_argument("--full-ranks", dest="full_ranks", help="one-based screen ranks to optimize in full, e.g. 1,3,9; disables variants")
    b.add_argument("--trace-out", dest="trace_out", help="write the search's summed trace counters as JSON to this path")
    b.add_argument("--loop-seconds", dest="loop_seconds", type=float, help="maximum seconds for each full improvement loop")
    b.add_argument("--workers", type=int); b.add_argument("--max-builds", dest="max_builds", type=int); b.add_argument("--gear", choices=("loot", "wishlist"), default=None, help="day-1 gear model")
    b.add_argument("--dry-run", action="store_true", help="print how the request was understood and stop")
    b.add_argument("--no-variants", dest="no_variants", action="store_true", help="cheapest run: no unique variants, no mutation round (one full build per candidate)")
    b.add_argument("--print-request", action="store_true", help="print the request JSON and stop")

    for name, help_text in (("probe", "what damage a skill deals by itself (modes)"), ("audit", "machine audit of build files"), ("describe", "read a build like a person"), ("benchmark", "rebuild the references and compare")):
        s = sub.add_parser(name, help=help_text)
        s.add_argument("args", nargs=argparse.REMAINDER)

    args = ap.parse_args(argv)
    if args.command == "build":
        req = request_from_args(args)
        check_level(req)
        if args.print_request:
            print(json.dumps(req, ensure_ascii=False, indent=2))
            return 0
        tmp = Path(tempfile.gettempdir()) / f"junkroan-request-{abs(hash(json.dumps(req, sort_keys=True)))}.json"
        tmp.write_text(json.dumps(req, ensure_ascii=False, indent=2), encoding="utf-8")
        return _run("search.py", search_argv(args, tmp, str(req["skill"])))
    script = {"probe": "probe_modes.py", "audit": "audit_build.py", "describe": "describe_build.py", "benchmark": "benchmark.py"}[args.command]
    return _run(script, list(args.args))


if __name__ == "__main__":
    raise SystemExit(main())
