"""Build the current league's crafting-bench unlock index from the saved wiki join."""

from __future__ import annotations

import argparse
import html
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "junkroan" / "mechanics" / "bench_unlocks.json"


def default_cache() -> Path:
    """The shared wiki cache lives beside Git's common directory in linked worktrees."""

    try:
        raw = Path(subprocess.check_output(["git", "rev-parse", "--git-common-dir"], cwd=ROOT, text=True).strip())
        common_dir = raw.resolve() if raw.is_absolute() else (ROOT / raw).resolve()
    except (OSError, subprocess.CalledProcessError):
        return ROOT / "var" / "cache" / "wiki" / "2026-09-19-crafting-bench-unlocks.json"
    return common_dir.parent / "var" / "cache" / "wiki" / "2026-09-19-crafting-bench-unlocks.json"


def _text(value: object) -> str:
    return html.unescape(str(value))


def _entry(option: dict[str, Any]) -> dict[str, Any]:
    kind = str(option.get("kind") or "")
    tier = option.get("tier_3_29")
    rank = option.get("rank")
    return {
        "where": kind,
        "location": _text(option.get("location") or ""),
        "tier": int(tier) if kind == "map" and tier not in (None, 0) else None,
        "rank": int(rank) if str(rank or "").lstrip("-").isdigit() else rank,
        "cost": [_text(cost) for cost in (option.get("cost") or [])],
    }


def build(cache: Path) -> dict[str, Any]:
    raw = json.loads(cache.read_text(encoding="utf-8"))
    series = list(raw.get("series") or [])
    current = next((row for row in series if row.get("id") == "Deepwater"), series[-1])
    by_mod_id: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for option in raw.get("options") or []:
        key = "mod_id" if option.get("mod_id") else "name"
        value = option.get(key)
        if value is None:
            continue
        target = by_mod_id if key == "mod_id" else by_name
        target[_text(value)] = _entry(option)
    return {
        "league": _text(current.get("name") or ""),
        "series_id": str(current.get("id") or "Deepwater"),
        "fetched": str(raw.get("fetched") or "2026-09-19"),
        "source": str(raw.get("source") or "poewiki Cargo tables"),
        "by_mod_id": dict(sorted(by_mod_id.items())),
        "by_name": dict(sorted(by_name.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=default_cache())
    args = parser.parse_args()
    result = build(args.cache)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"wrote {OUT}: {len(result['by_mod_id'])} mod ids, {len(result['by_name'])} names")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
