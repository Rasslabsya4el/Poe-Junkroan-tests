"""Dump the skeleton (`Skeleton.to_json()`) every reference fixture produces through
`benchmark.prepare_author`, one file per fixture, one PoB session reused sequentially.

Used to prove a skeleton-derivation change touches only the fixtures it is meant to touch
(spec 2026-09-22-fixture-skeleton-loads-and-rails, requirement 6): run once on the code
before the change, once after, diff the two folders.

Run:  python scripts/dump_fixture_skeletons.py --out artifacts/skeleton_dump/before --sets ziz,new18,core14
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from benchmark import SETS  # noqa: E402
from junkroan.report_format import human_duration  # noqa: E402


def _log_to(lines: list[str]):
    def log(msg: str) -> None:
        lines.append(msg)
    return log


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="folder to write <slug>.json (+ <slug>.log) into")
    ap.add_argument("--sets", default="ziz,new18,core14", help="comma-separated SETS keys, or 'all'")
    ap.add_argument("--slug", action="append", help="run only these slugs (repeatable); overrides --sets")
    args = ap.parse_args()

    from junkroan.pob.session import PobSession
    from benchmark import prepare_author

    if args.slug:
        slugs = list(dict.fromkeys(args.slug))
    else:
        keys = list(SETS) if args.sets == "all" else [s.strip() for s in args.sets.split(",") if s.strip()]
        slugs: list[str] = []
        for key in keys:
            for slug in SETS[key]:
                if slug not in slugs:
                    slugs.append(slug)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    ok, failed = 0, 0
    with PobSession(run_id=f"dump-skeletons-{__import__('os').getpid()}") as pob:
        for i, slug in enumerate(slugs, start=1):
            lines: list[str] = []
            log = _log_to(lines)
            t1 = time.perf_counter()
            try:
                prepared = prepare_author(pob, slug, log=log)
                (out_dir / f"{slug}.json").write_text(prepared.skeleton.to_json(), encoding="utf-8")
                ok += 1
                status = "ok"
            except Exception as exc:  # noqa: BLE001 - one bad fixture must not stop the dump
                failed += 1
                status = f"FAILED: {type(exc).__name__}: {exc}"
                lines.append(status)
                lines.append(traceback.format_exc())
            (out_dir / f"{slug}.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
            print(f"[{i}/{len(slugs)}] {slug}: {status} ({human_duration(time.perf_counter() - t1)})")

    print(f"{ok} ok, {failed} failed, {len(slugs)} total, {human_duration(time.perf_counter() - t0)}")
    return 0 if failed == 0 or True else 1  # a fixture that cannot load is itself a finding, not a script failure


if __name__ == "__main__":
    raise SystemExit(main())
